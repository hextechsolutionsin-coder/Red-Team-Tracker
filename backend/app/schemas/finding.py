"""
Pydantic schemas for finding management endpoints.

Requirements: 5.1, 5.2, 5.3, 5.6, 5.7, 5.8
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Valid enum values
# ---------------------------------------------------------------------------

VALID_SEVERITIES = {"Critical", "High", "Medium", "Low", "Info"}
VALID_STATUSES = {"open", "in-progress", "remediated", "verified", "reopened", "on-hold", "false-positive"}


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class FindingCreate(BaseModel):
    """
    Request body for POST /api/v1/findings.

    Required fields: title, severity, status, engagement_id (Requirement 5.1).
    Severity must be one of Critical/High/Medium/Low/Info (Requirement 5.2).
    Status must be one of open/in-progress/remediated/verified (Requirement 5.3).
    mitre_id validation (pattern ^T\\d{4,5}$) is performed in the router/service
    so that a structured error code can be returned (Requirement 5.6).
    reproduction_steps and remediation_recs are optional free-text up to 10,000
    chars each (Requirement 5.7).
    """

    engagement_id: uuid.UUID = Field(
        ...,
        description="UUID of the engagement this finding belongs to",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Finding title (1–500 characters)",
    )
    severity: str = Field(
        ...,
        description="Severity level: Critical, High, Medium, Low, or Info",
    )
    status: str = Field(
        ...,
        description="Finding status: open, in-progress, remediated, verified, reopened, on-hold, or false-positive",
    )
    mitre_id: str | None = Field(
        default=None,
        max_length=20,
        description="Optional MITRE ATT&CK technique or sub-technique ID (e.g. T1059 or T1059.001)",
    )
    mitre_name: str | None = Field(
        default=None,
        max_length=256,
        description="Optional MITRE ATT&CK technique name",
    )
    reproduction_steps: str | None = Field(
        default=None,
        max_length=10_000,
        description="Optional reproduction steps (max 10,000 characters)",
    )
    remediation_recs: str | None = Field(
        default=None,
        max_length=10_000,
        description="Optional remediation recommendations (max 10,000 characters)",
    )

    # ── Risk scoring fields (ISO 27001:2022 / NIST CSF 2.0) ─────────────────
    likelihood: int | None = Field(
        default=None,
        description="Likelihood rating (1-5): 1=Rare, 2=Unlikely, 3=Possible, 4=Likely, 5=Almost Certain",
    )
    impact: int | None = Field(
        default=None,
        description="Impact rating (1-5): 1=Negligible, 2=Minor, 3=Moderate, 4=Major, 5=Catastrophic",
    )
    asset_criticality: int | None = Field(
        default=None,
        description="Asset criticality (1-5): 1=Very Low, 2=Low, 3=Medium, 4=High, 5=Critical",
    )
    affected_asset_type: str | None = Field(
        default=None,
        max_length=32,
        description="Affected asset type: Network, Application, Data, Personnel, Physical",
    )
    nist_csf_function: str | None = Field(
        default=None,
        max_length=16,
        description="NIST CSF 2.0 function: Govern, Identify, Protect, Detect, Respond, Recover",
    )
    iso_control: str | None = Field(
        default=None,
        max_length=16,
        description="ISO 27001:2022 Annex A control domain: A.5, A.6, A.7, A.8",
    )


class FindingUpdate(BaseModel):
    """
    Request body for PATCH /api/v1/findings/{id}.

    All fields are optional — the router validates enums and MITRE pattern on
    any supplied value.  Operators cannot change engagement assignment or delete
    findings (Requirement 2.7).
    """

    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Updated title (1–500 characters)",
    )
    severity: str | None = Field(
        default=None,
        description="Updated severity: Critical, High, Medium, Low, or Info",
    )
    status: str | None = Field(
        default=None,
        description="Updated status: open, in-progress, remediated, verified, reopened, on-hold, or false-positive",
    )
    mitre_id: str | None = Field(
        default=None,
        max_length=16,
        description="Updated MITRE ATT&CK technique ID (set to null to clear)",
    )
    mitre_name: str | None = Field(
        default=None,
        max_length=256,
        description="Updated MITRE ATT&CK technique name",
    )
    reproduction_steps: str | None = Field(
        default=None,
        max_length=10_000,
        description="Updated reproduction steps",
    )
    remediation_recs: str | None = Field(
        default=None,
        max_length=10_000,
        description="Updated remediation recommendations",
    )

    # ── Risk scoring fields ──────────────────────────────────────────────────
    likelihood: int | None = Field(
        default=None,
        description="Likelihood rating (1-5)",
    )
    impact: int | None = Field(
        default=None,
        description="Impact rating (1-5)",
    )
    asset_criticality: int | None = Field(
        default=None,
        description="Asset criticality (1-5)",
    )
    affected_asset_type: str | None = Field(
        default=None,
        max_length=32,
        description="Affected asset type",
    )
    nist_csf_function: str | None = Field(
        default=None,
        max_length=16,
        description="NIST CSF 2.0 function",
    )
    iso_control: str | None = Field(
        default=None,
        max_length=16,
        description="ISO 27001:2022 Annex A control domain",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class FindingResponse(BaseModel):
    """
    Outgoing JSON representation of a finding.

    Includes all finding fields.  Evidence files are managed through the
    separate evidence endpoints.
    """

    id: uuid.UUID
    engagement_id: uuid.UUID
    title: str
    severity: str
    status: str
    mitre_id: str | None
    mitre_name: str | None
    reproduction_steps: str | None
    remediation_recs: str | None

    # Risk scoring fields
    likelihood: int | None = None
    impact: int | None = None
    asset_criticality: int | None = None
    risk_score: int | None = None
    risk_rating: str | None = None
    affected_asset_type: str | None = None
    nist_csf_function: str | None = None
    iso_control: str | None = None

    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
