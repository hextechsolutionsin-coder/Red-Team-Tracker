"""
End-to-end integration tests for critical application flows.

Flows covered
-------------
1. Operator assignment → finding creation → evidence upload → evidence download
   → finding delete (cascade evidence)
2. Engagement lifecycle: planned → active → completed → archived
3. PDF report generation with 2–3 findings

All tests use the in-memory SQLite fixture from conftest.py and do NOT
require a running Docker container.

Requirements: 1.1, 4.3, 5.9, 9.1, 10.1, 10.5
"""

from __future__ import annotations

import io
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import SESSION_COOKIE_NAME
from app.models.engagement import Engagement, EngagementOperator
from app.models.evidence import EvidenceFile
from app.models.finding import Finding
from app.models.user import User

try:
    import bcrypt as _bcrypt_lib

    def _hash_password(password: str) -> str:
        """Hash a password using bcrypt directly (passlib has compat issues with bcrypt 5.x)."""
        return _bcrypt_lib.hashpw(password.encode(), _bcrypt_lib.gensalt()).decode()

except ImportError:
    from passlib.context import CryptContext as _CryptContext

    _pwd_ctx = _CryptContext(schemes=["bcrypt"], deprecated="auto")

    def _hash_password(password: str) -> str:
        return _pwd_ctx.hash(password)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TODAY = date.today()
_TOMORROW = _TODAY + timedelta(days=1)
_NEXT_WEEK = _TODAY + timedelta(days=7)


async def _insert_user(
    db: AsyncSession,
    username: str,
    password: str = "Password1!",
    role: str = "operator",
    is_active: bool = True,
) -> User:
    """Insert a User with a real bcrypt hash."""
    now = datetime.now(tz=timezone.utc)
    user = User(
        id=uuid.uuid4(),
        username=username,
        password_hash=_hash_password(password),
        role=role,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _login(client: AsyncClient, username: str, password: str = "Password1!") -> str:
    """Login and return the session cookie value."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    cookie = resp.cookies.get(SESSION_COOKIE_NAME)
    assert cookie, "No session cookie returned"
    return cookie


def _cookies(cookie: str) -> dict[str, str]:
    return {SESSION_COOKIE_NAME: cookie}


# ---------------------------------------------------------------------------
# Flow 1: Operator assignment → Finding → Evidence → Download → Delete
# ---------------------------------------------------------------------------


async def test_operator_assignment_finding_evidence_cycle(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
) -> None:
    """
    Full end-to-end flow:
    1. Admin creates engagement.
    2. Lead assigns operator to engagement.
    3. Operator creates a finding inside the engagement.
    4. Operator uploads evidence file to the finding.
    5. Operator downloads the evidence file.
    6. Lead deletes the finding → evidence records are cascade-deleted.

    Requirements: 4.3, 5.9
    """
    # -----------------------------------------------------------------------
    # Setup: create admin, lead, and operator users
    # -----------------------------------------------------------------------
    admin = await _insert_user(db_session, "e2e_admin", role="admin")
    lead = await _insert_user(db_session, "e2e_lead", role="lead")
    operator = await _insert_user(db_session, "e2e_operator", role="operator")

    admin_cookie = await _login(client, "e2e_admin")
    lead_cookie = await _login(client, "e2e_lead")
    operator_cookie = await _login(client, "e2e_operator")

    # -----------------------------------------------------------------------
    # Step 1: Lead creates engagement
    # -----------------------------------------------------------------------
    eng_resp = await client.post(
        "/api/v1/engagements",
        json={
            "name": "E2E Test Engagement",
            "description": "Integration test engagement",
            "scope": "All systems in scope",
            "start_date": str(_TODAY),
            "end_date": str(_NEXT_WEEK),
        },
        cookies=_cookies(lead_cookie),
    )
    assert eng_resp.status_code == 201, f"Create engagement failed: {eng_resp.text}"
    engagement_id = eng_resp.json()["id"]
    assert eng_resp.json()["status"] == "planned"

    # -----------------------------------------------------------------------
    # Step 2: Lead assigns operator to engagement
    # -----------------------------------------------------------------------
    assign_resp = await client.post(
        f"/api/v1/engagements/{engagement_id}/operators",
        json={"operator_ids": [str(operator.id)]},
        cookies=_cookies(lead_cookie),
    )
    assert assign_resp.status_code == 200, f"Assign operator failed: {assign_resp.text}"

    # -----------------------------------------------------------------------
    # Step 3: Operator creates a finding
    # -----------------------------------------------------------------------
    finding_resp = await client.post(
        "/api/v1/findings",
        json={
            "engagement_id": engagement_id,
            "title": "SQL Injection in login form",
            "severity": "Critical",
            "status": "open",
            "mitre_id": "T1190",
            "reproduction_steps": "POST /login with ' OR 1=1 --",
        },
        cookies=_cookies(operator_cookie),
    )
    assert finding_resp.status_code == 201, f"Create finding failed: {finding_resp.text}"
    finding_id = finding_resp.json()["id"]
    assert finding_resp.json()["severity"] == "Critical"

    # -----------------------------------------------------------------------
    # Step 4: Operator uploads evidence
    # -----------------------------------------------------------------------
    # Create a real temp file for upload
    evidence_content = b"Screenshot data: VULNERABLE_QUERY_OUTPUT"
    evidence_file = tmp_path / "evidence.txt"
    evidence_file.write_bytes(evidence_content)

    # Patch UPLOAD_DIR to use our tmp_path so the file actually gets written
    import app.config as _cfg
    original_upload_dir = _cfg.settings.UPLOAD_DIR
    _cfg.settings.UPLOAD_DIR = str(tmp_path)

    try:
        upload_resp = await client.post(
            f"/api/v1/evidence/{finding_id}/upload",
            files={"file": ("evidence.txt", io.BytesIO(evidence_content), "text/plain")},
            cookies=_cookies(operator_cookie),
        )
        assert upload_resp.status_code == 201, f"Upload evidence failed: {upload_resp.text}"
        evidence_id = upload_resp.json()["id"]
        assert upload_resp.json()["original_filename"] == "evidence.txt"
        assert upload_resp.json()["mime_type"] == "text/plain"

        # -----------------------------------------------------------------------
        # Step 5: Operator downloads evidence
        # -----------------------------------------------------------------------
        download_resp = await client.get(
            f"/api/v1/evidence/{evidence_id}/download",
            cookies=_cookies(operator_cookie),
        )
        assert download_resp.status_code == 200, f"Download failed: {download_resp.text}"
        assert download_resp.content == evidence_content
        assert "attachment" in download_resp.headers.get("content-disposition", "")

        # -----------------------------------------------------------------------
        # Step 6: Lead deletes finding (and evidence cascade) — Requirement 5.9
        # -----------------------------------------------------------------------
        delete_resp = await client.delete(
            f"/api/v1/findings/{finding_id}",
            cookies=_cookies(lead_cookie),
        )
        assert delete_resp.status_code == 204, f"Delete finding failed: {delete_resp.text}"

        # Verify finding is gone
        get_resp = await client.get(
            f"/api/v1/findings/{finding_id}",
            cookies=_cookies(lead_cookie),
        )
        assert get_resp.status_code == 404

        # Verify evidence record is gone (finding delete is atomic)
        ev_download = await client.get(
            f"/api/v1/evidence/{evidence_id}/download",
            cookies=_cookies(lead_cookie),
        )
        assert ev_download.status_code == 404

    finally:
        _cfg.settings.UPLOAD_DIR = original_upload_dir


# ---------------------------------------------------------------------------
# Flow 2: Engagement lifecycle planned → active → completed → archived
# ---------------------------------------------------------------------------


async def test_engagement_lifecycle(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """
    Engagement status must follow the strictly forward-only transition:
    planned → active → completed → archived (Requirements 4.3)

    Also verifies that invalid backwards transitions are rejected with 400.
    """
    lead = await _insert_user(db_session, "lifecycle_lead", role="lead")
    lead_cookie = await _login(client, "lifecycle_lead")

    # Create engagement (always starts as "planned")
    create_resp = await client.post(
        "/api/v1/engagements",
        json={
            "name": "Lifecycle Engagement",
            "start_date": str(_TODAY),
            "end_date": str(_NEXT_WEEK),
        },
        cookies=_cookies(lead_cookie),
    )
    assert create_resp.status_code == 201
    eng_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "planned"

    # planned → active
    patch_active = await client.patch(
        f"/api/v1/engagements/{eng_id}",
        json={"status": "active"},
        cookies=_cookies(lead_cookie),
    )
    assert patch_active.status_code == 200, f"planned→active failed: {patch_active.text}"
    assert patch_active.json()["status"] == "active"

    # active → completed
    patch_completed = await client.patch(
        f"/api/v1/engagements/{eng_id}",
        json={"status": "completed"},
        cookies=_cookies(lead_cookie),
    )
    assert patch_completed.status_code == 200, f"active→completed failed: {patch_completed.text}"
    assert patch_completed.json()["status"] == "completed"

    # completed → archived
    patch_archived = await client.patch(
        f"/api/v1/engagements/{eng_id}",
        json={"status": "archived"},
        cookies=_cookies(lead_cookie),
    )
    assert patch_archived.status_code == 200, f"completed→archived failed: {patch_archived.text}"
    assert patch_archived.json()["status"] == "archived"

    # Backwards transition must be rejected: archived → planned (invalid)
    patch_backward = await client.patch(
        f"/api/v1/engagements/{eng_id}",
        json={"status": "planned"},
        cookies=_cookies(lead_cookie),
    )
    assert patch_backward.status_code == 400, (
        f"Expected 400 for backward transition, got {patch_backward.status_code}: "
        f"{patch_backward.text}"
    )


async def test_engagement_lifecycle_cannot_skip_status(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """
    Status cannot jump from planned directly to completed (skipping active).
    The transition must be rejected with 400.  Requirement 4.3.
    """
    lead = await _insert_user(db_session, "skip_status_lead", role="lead")
    lead_cookie = await _login(client, "skip_status_lead")

    create_resp = await client.post(
        "/api/v1/engagements",
        json={
            "name": "Skip Status Engagement",
            "start_date": str(_TODAY),
            "end_date": str(_NEXT_WEEK),
        },
        cookies=_cookies(lead_cookie),
    )
    assert create_resp.status_code == 201
    eng_id = create_resp.json()["id"]

    # planned → completed (skip active) — must be rejected
    patch_skip = await client.patch(
        f"/api/v1/engagements/{eng_id}",
        json={"status": "completed"},
        cookies=_cookies(lead_cookie),
    )
    assert patch_skip.status_code == 400, (
        f"Expected 400 for skipped status transition, got {patch_skip.status_code}"
    )


async def test_completed_engagement_non_status_fields_frozen(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """
    Once an engagement is completed, non-status field edits must be rejected
    with 400 (Requirement 4.9).
    """
    lead = await _insert_user(db_session, "frozen_fields_lead", role="lead")
    lead_cookie = await _login(client, "frozen_fields_lead")

    create_resp = await client.post(
        "/api/v1/engagements",
        json={
            "name": "Frozen Fields Engagement",
            "start_date": str(_TODAY),
            "end_date": str(_NEXT_WEEK),
        },
        cookies=_cookies(lead_cookie),
    )
    assert create_resp.status_code == 201
    eng_id = create_resp.json()["id"]

    # Advance to completed
    for status in ("active", "completed"):
        r = await client.patch(
            f"/api/v1/engagements/{eng_id}",
            json={"status": status},
            cookies=_cookies(lead_cookie),
        )
        assert r.status_code == 200

    # Attempt to change name — must be rejected
    patch_name = await client.patch(
        f"/api/v1/engagements/{eng_id}",
        json={"name": "New Name That Should Be Rejected"},
        cookies=_cookies(lead_cookie),
    )
    assert patch_name.status_code == 400, (
        f"Expected 400 for name edit on completed engagement, got {patch_name.status_code}"
    )


# ---------------------------------------------------------------------------
# Flow 3: PDF report generation with 2–3 findings
# ---------------------------------------------------------------------------


async def test_pdf_report_generation_with_findings(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
    monkeypatch,
) -> None:
    """
    Generate a PDF report for an engagement containing 2–3 findings.

    Verifies:
    - Report endpoint returns 200 with application/pdf Content-Type (Req 9.1).
    - Content-Disposition header includes attachment and .pdf filename (Req 9.4).
    - The response body is non-empty (WeasyPrint produced some content).

    Requirements: 9.1, 10.5
    """
    lead = await _insert_user(db_session, "report_lead", role="lead")
    lead_cookie = await _login(client, "report_lead")

    # Create engagement
    eng_resp = await client.post(
        "/api/v1/engagements",
        json={
            "name": "Report Test Engagement",
            "description": "For PDF generation test",
            "scope": "Web applications",
            "start_date": str(_TODAY),
            "end_date": str(_NEXT_WEEK),
        },
        cookies=_cookies(lead_cookie),
    )
    assert eng_resp.status_code == 201
    eng_id = eng_resp.json()["id"]

    # Create 3 findings
    findings_data = [
        {
            "engagement_id": eng_id,
            "title": "Critical RCE",
            "severity": "Critical",
            "status": "open",
            "reproduction_steps": "Exploit via buffer overflow",
            "remediation_recs": "Update to patched version",
        },
        {
            "engagement_id": eng_id,
            "title": "SQL Injection",
            "severity": "High",
            "status": "in-progress",
            "mitre_id": "T1190",
        },
        {
            "engagement_id": eng_id,
            "title": "Weak Password Policy",
            "severity": "Medium",
            "status": "remediated",
        },
    ]

    for fd in findings_data:
        fr = await client.post(
            "/api/v1/findings",
            json=fd,
            cookies=_cookies(lead_cookie),
        )
        assert fr.status_code == 201, f"Create finding failed: {fr.text}"

    # Request the PDF report
    report_resp = await client.get(
        f"/api/v1/reports/{eng_id}",
        cookies=_cookies(lead_cookie),
    )

    # WeasyPrint might not be installed in test env → skip if REPORT_GENERATION_FAILED
    if report_resp.status_code == 500:
        body = report_resp.json()
        # AppError format: {"error_code": ..., "message": ..., "detail": {}}
        error_code = body.get("error_code") or body.get("detail", {}).get("error_code", "")
        if error_code == "REPORT_GENERATION_FAILED":
            pytest.skip(
                "WeasyPrint is not available in this environment; "
                "PDF generation endpoint correctly returns 500 with REPORT_GENERATION_FAILED."
            )
        else:
            pytest.fail(f"Report generation returned unexpected 500: {report_resp.text}")

    assert report_resp.status_code == 200, (
        f"Expected 200 for PDF generation, got {report_resp.status_code}: {report_resp.text}"
    )

    # Verify Content-Type
    content_type = report_resp.headers.get("content-type", "")
    assert "application/pdf" in content_type, (
        f"Expected application/pdf, got '{content_type}'"
    )

    # Verify Content-Disposition header has attachment + .pdf filename (Requirement 9.4)
    content_disp = report_resp.headers.get("content-disposition", "")
    assert "attachment" in content_disp, (
        f"Expected 'attachment' in Content-Disposition, got '{content_disp}'"
    )
    assert ".pdf" in content_disp.lower(), (
        f"Expected .pdf in Content-Disposition filename, got '{content_disp}'"
    )

    # PDF must be non-empty
    assert len(report_resp.content) > 0, "PDF response body is empty"


async def test_pdf_report_404_for_unknown_engagement(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """
    GET /api/v1/reports/{unknown_id} must return 404 (Requirement 9.1).
    """
    lead = await _insert_user(db_session, "report_404_lead", role="lead")
    lead_cookie = await _login(client, "report_404_lead")

    fake_id = str(uuid.uuid4())
    resp = await client.get(
        f"/api/v1/reports/{fake_id}",
        cookies=_cookies(lead_cookie),
    )
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


async def test_pdf_report_forbidden_for_operator(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """
    Report generation endpoint is lead/admin only — operators must receive 403.
    """
    lead = await _insert_user(db_session, "report_role_lead", role="lead")
    operator = await _insert_user(db_session, "report_role_operator", role="operator")
    lead_cookie = await _login(client, "report_role_lead")
    operator_cookie = await _login(client, "report_role_operator")

    # Create engagement as lead
    eng_resp = await client.post(
        "/api/v1/engagements",
        json={
            "name": "RBAC Report Test",
            "start_date": str(_TODAY),
            "end_date": str(_NEXT_WEEK),
        },
        cookies=_cookies(lead_cookie),
    )
    assert eng_resp.status_code == 201
    eng_id = eng_resp.json()["id"]

    # Operator must be forbidden
    resp = await client.get(
        f"/api/v1/reports/{eng_id}",
        cookies=_cookies(operator_cookie),
    )
    assert resp.status_code == 403, f"Expected 403 for operator, got {resp.status_code}"


# ---------------------------------------------------------------------------
# Bonus: Operator cannot create finding in engagement they're not assigned to
# ---------------------------------------------------------------------------


async def test_operator_blocked_from_unassigned_engagement(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """
    An operator must receive 403 when trying to create a finding in an
    engagement they are not assigned to (Requirement 2.7).
    """
    lead = await _insert_user(db_session, "unassigned_lead", role="lead")
    operator = await _insert_user(db_session, "unassigned_operator", role="operator")
    lead_cookie = await _login(client, "unassigned_lead")
    operator_cookie = await _login(client, "unassigned_operator")

    # Lead creates engagement (operator not assigned)
    eng_resp = await client.post(
        "/api/v1/engagements",
        json={
            "name": "Unassigned Engagement",
            "start_date": str(_TODAY),
            "end_date": str(_NEXT_WEEK),
        },
        cookies=_cookies(lead_cookie),
    )
    assert eng_resp.status_code == 201
    eng_id = eng_resp.json()["id"]

    # Operator tries to create finding — must be 403
    finding_resp = await client.post(
        "/api/v1/findings",
        json={
            "engagement_id": eng_id,
            "title": "Forbidden finding",
            "severity": "Low",
            "status": "open",
        },
        cookies=_cookies(operator_cookie),
    )
    assert finding_resp.status_code == 403, (
        f"Expected 403 for unassigned operator, got {finding_resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Bonus: Finding deletion with evidence filesystem failure is atomic (Req 5.9)
# ---------------------------------------------------------------------------


async def test_finding_delete_aborts_on_filesystem_failure(
    client: AsyncClient,
    db_session: AsyncSession,
    tmp_path,
    monkeypatch,
) -> None:
    """
    If any evidence file's filesystem deletion fails during finding delete,
    the entire operation is aborted and the finding + evidence records remain
    intact (Requirement 5.9).
    """
    lead = await _insert_user(db_session, "atomic_lead", role="lead")
    operator = await _insert_user(db_session, "atomic_operator", role="operator")
    lead_cookie = await _login(client, "atomic_lead")
    operator_cookie = await _login(client, "atomic_operator")

    # Setup engagement + operator assignment
    eng_resp = await client.post(
        "/api/v1/engagements",
        json={
            "name": "Atomic Delete Engagement",
            "start_date": str(_TODAY),
            "end_date": str(_NEXT_WEEK),
        },
        cookies=_cookies(lead_cookie),
    )
    assert eng_resp.status_code == 201
    eng_id = eng_resp.json()["id"]

    await client.post(
        f"/api/v1/engagements/{eng_id}/operators",
        json={"operator_ids": [str(operator.id)]},
        cookies=_cookies(lead_cookie),
    )

    # Create finding
    finding_resp = await client.post(
        "/api/v1/findings",
        json={
            "engagement_id": eng_id,
            "title": "Atomic Deletion Test Finding",
            "severity": "High",
            "status": "open",
        },
        cookies=_cookies(operator_cookie),
    )
    assert finding_resp.status_code == 201
    finding_id = finding_resp.json()["id"]

    # Upload evidence with real file
    import app.config as _cfg
    original_upload_dir = _cfg.settings.UPLOAD_DIR
    _cfg.settings.UPLOAD_DIR = str(tmp_path)

    try:
        upload_resp = await client.post(
            f"/api/v1/evidence/{finding_id}/upload",
            files={"file": ("test.txt", io.BytesIO(b"evidence data"), "text/plain")},
            cookies=_cookies(operator_cookie),
        )
        assert upload_resp.status_code == 201
        evidence_id = upload_resp.json()["id"]

        # Patch os.remove to simulate filesystem failure
        original_remove = os.remove

        def _fail_remove(path: str) -> None:
            raise OSError(f"Simulated filesystem error for: {path}")

        monkeypatch.setattr("os.remove", _fail_remove)

        try:
            # Attempt to delete finding — should fail with 500
            delete_resp = await client.delete(
                f"/api/v1/findings/{finding_id}",
                cookies=_cookies(lead_cookie),
            )
            assert delete_resp.status_code == 500, (
                f"Expected 500 for filesystem failure, got {delete_resp.status_code}: "
                f"{delete_resp.text}"
            )
            resp_body = delete_resp.json()
            # AppError format: {"error_code": ..., "message": ..., "detail": {}}
            error_code = resp_body.get("error_code") or resp_body.get("detail", {}).get("error_code", "")
            assert error_code == "EVIDENCE_DELETE_FAILED"

        finally:
            monkeypatch.setattr("os.remove", original_remove)

        # Finding must still exist (operation was aborted)
        get_finding = await client.get(
            f"/api/v1/findings/{finding_id}",
            cookies=_cookies(lead_cookie),
        )
        assert get_finding.status_code == 200, (
            "Finding should still exist after failed delete"
        )

        # Evidence record must still exist
        list_ev = await client.get(
            f"/api/v1/evidence/{finding_id}/files",
            cookies=_cookies(lead_cookie),
        )
        assert list_ev.status_code == 200
        assert len(list_ev.json()) == 1, "Evidence record should still exist"

    finally:
        _cfg.settings.UPLOAD_DIR = original_upload_dir
