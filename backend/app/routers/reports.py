"""
PDF report generation router.

Routes
------
GET /api/v1/reports/{engagement_id}  — generate and stream a PDF report (lead/admin only)

Business rules enforced
-----------------------
- Fetch engagement by ID, raise 404 if not found (Requirement 9.1).
- Fetch all findings for the engagement ordered by SEVERITY_ORDER (Requirement 9.2).
- Fetch evidence filenames per finding (no binary content) (Requirement 9.6).
- Render report.html Jinja2 template with all required fields (Requirements 9.1, 9.5, 9.6).
- Convert rendered HTML to PDF in-memory with WeasyPrint (Requirement 9.7).
- On WeasyPrint failure, return HTTPException(500) without sending partial content (Req 9.7).
- Stream PDF via StreamingResponse with Content-Disposition attachment (Requirements 9.3, 9.4).
- Log ``report_generated`` via log_service (Requirement 9.3).
- Use ``generate_report_filename`` from report_service for the download filename (Req 9.4).

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import date, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_session_db, require_role
from app.models.engagement import Engagement
from app.models.evidence import EvidenceFile
from app.models.finding import Finding
from app.models.user import User
from app.services.finding_service import SEVERITY_ORDER
from app.services.log_service import record_log
from app.services.report_service import generate_report_filename

logger = logging.getLogger("redboard.reports")

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/reports", tags=["reports"])

# ---------------------------------------------------------------------------
# Jinja2 template environment (shared across requests)
# ---------------------------------------------------------------------------

import os
from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")

_jinja_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)

# ---------------------------------------------------------------------------
# Severity case expression for ordering
# ---------------------------------------------------------------------------

_SEVERITY_CASE = case(
    *[
        (Finding.severity == label, weight)
        for label, weight in SEVERITY_ORDER.items()
    ],
    else_=len(SEVERITY_ORDER) + 1,
)


# ---------------------------------------------------------------------------
# GET /reports/{engagement_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{engagement_id}",
    summary="Generate and download a PDF report for an engagement (lead/admin only)",
    responses={
        200: {"description": "PDF report streamed as attachment"},
        401: {"description": "Not authenticated"},
        403: {"description": "Lead or admin role required"},
        404: {"description": "Engagement not found"},
        500: {"description": "PDF generation failed"},
    },
)
async def get_report(
    engagement_id: uuid.UUID,
    current_user: User = Depends(require_role("lead", "admin")),
    db: AsyncSession = Depends(get_session_db),
) -> StreamingResponse:
    """
    Generate a PDF report for the specified engagement and stream it as a download.

    Steps
    -----
    1. Fetch the engagement; return 404 if not found.
    2. Fetch all findings ordered by SEVERITY_ORDER (Critical first).
    3. For each finding fetch evidence filenames (no binary content).
    4. Render ``report.html`` Jinja2 template.
    5. Convert to PDF in-memory via WeasyPrint; on failure return 500.
    6. Log ``report_generated``.
    7. Stream the PDF bytes with ``Content-Disposition: attachment``.

    Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7
    """
    # ------------------------------------------------------------------
    # 1. Fetch engagement (Requirement 9.1)
    # ------------------------------------------------------------------
    eng_result = await db.execute(
        select(Engagement).where(Engagement.id == engagement_id)
    )
    engagement: Engagement | None = eng_result.scalar_one_or_none()
    if engagement is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "ENGAGEMENT_NOT_FOUND",
                "message": f"No engagement found with ID '{engagement_id}'.",
            },
        )

    # ------------------------------------------------------------------
    # 2. Fetch findings ordered by severity (Requirement 9.2)
    # ------------------------------------------------------------------
    findings_result = await db.execute(
        select(Finding)
        .where(Finding.engagement_id == engagement_id)
        .order_by(_SEVERITY_CASE.asc())
    )
    findings: list[Finding] = list(findings_result.scalars().all())

    # ------------------------------------------------------------------
    # 3. Fetch evidence filenames per finding (Requirement 9.6 — no binary)
    # ------------------------------------------------------------------
    # Build a mapping: finding_id → list of original_filename strings
    evidence_map: dict[uuid.UUID, list[str]] = {}
    if findings:
        finding_ids = [f.id for f in findings]
        ev_result = await db.execute(
            select(EvidenceFile).where(EvidenceFile.finding_id.in_(finding_ids))
        )
        for ev in ev_result.scalars().all():
            evidence_map.setdefault(ev.finding_id, []).append(ev.original_filename)

    # Build per-finding context dicts for template rendering
    findings_ctx = []
    for f in findings:
        findings_ctx.append(
            {
                "title": f.title,
                "severity": f.severity,
                "mitre_id": f.mitre_id,
                "mitre_name": f.mitre_name,
                "status": f.status,
                "reproduction_steps": f.reproduction_steps,
                "remediation_recs": f.remediation_recs,
                "evidence_filenames": evidence_map.get(f.id, []),
            }
        )

    # Severity counts for the summary section (Requirement 9.1)
    severity_counts: dict[str, int] = {sev: 0 for sev in SEVERITY_ORDER}
    for f in findings:
        if f.severity in severity_counts:
            severity_counts[f.severity] += 1

    # ------------------------------------------------------------------
    # 4. Render Jinja2 template (Requirements 9.1, 9.5, 9.6)
    # ------------------------------------------------------------------
    template = _jinja_env.get_template("report.html")
    html_content = template.render(
        engagement_name=engagement.name,
        engagement_scope=engagement.scope,
        engagement_start_date=engagement.start_date,
        engagement_end_date=engagement.end_date,
        engagement_status=engagement.status,
        severity_counts=severity_counts,
        findings=findings_ctx,
        has_findings=len(findings_ctx) > 0,
        report_date=date.today(),
    )

    # ------------------------------------------------------------------
    # 5. Convert HTML to PDF in-memory with WeasyPrint (Requirement 9.7)
    # ------------------------------------------------------------------
    try:
        from weasyprint import HTML as WeasyprintHTML  # type: ignore[import]

        pdf_bytes: bytes = WeasyprintHTML(string=html_content).write_pdf()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "WeasyPrint PDF generation failed for engagement %s: %s",
            engagement_id,
            exc,
        )
        # Do NOT send partial content (Requirement 9.7)
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "REPORT_GENERATION_FAILED",
                "message": (
                    "PDF report generation failed. The report could not be created. "
                    "Please try again or contact an administrator."
                ),
            },
        )

    # ------------------------------------------------------------------
    # 6. Log report_generated (Requirement 9.3)
    # ------------------------------------------------------------------
    await record_log(
        db=db,
        action_type="report_generated",
        actor_username=current_user.username,
        description=(
            f"User '{current_user.username}' generated a PDF report for "
            f"engagement '{engagement.name}' ({engagement_id})."
        ),
        engagement_id=engagement_id,
        target_entity_type="engagement",
        target_entity_id=engagement_id,
    )
    await db.commit()

    # ------------------------------------------------------------------
    # 7. Stream the PDF (Requirements 9.3, 9.4)
    # ------------------------------------------------------------------
    # Derive the download filename from the engagement name (Requirement 9.4)
    filename = generate_report_filename(engagement.name, date.today())

    logger.info(
        "PDF report generated for engagement '%s' (%s) by user '%s' — %d finding(s), %d bytes",
        engagement.name,
        engagement_id,
        current_user.username,
        len(findings),
        len(pdf_bytes),
    )

    return StreamingResponse(
        content=io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
