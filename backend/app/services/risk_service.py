"""
Risk calculation service — ISO 27001:2022 / NIST CSF 2.0 framework-based scoring.

Risk Score = likelihood × impact × asset_criticality (max 125)

Rating thresholds:
  Critical: 80–125
  High:     45–79
  Medium:   15–44
  Low:      1–14
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.finding import Finding


# ---------------------------------------------------------------------------
# Valid values for risk-related fields
# ---------------------------------------------------------------------------

VALID_AFFECTED_ASSET_TYPES = {"Network", "Application", "Data", "Personnel", "Physical", "Cloud", "Endpoint", "IoT", "Identity", "Supply Chain"}
VALID_NIST_CSF_FUNCTIONS = {"Govern", "Identify", "Protect", "Detect", "Respond", "Recover"}
VALID_ISO_CONTROLS = {"A.5", "A.6", "A.7", "A.8"}

# Severity weights for engagement-level risk aggregation
SEVERITY_WEIGHT = {"Critical": 5, "High": 4, "Medium": 3, "Low": 2, "Info": 1}


# ---------------------------------------------------------------------------
# Individual finding risk score
# ---------------------------------------------------------------------------


def calculate_risk_score(
    likelihood: int | None,
    impact: int | None,
    asset_criticality: int | None,
) -> tuple[int | None, str | None]:
    """
    Calculate risk score and rating for a single finding.

    Returns (score, rating) tuple.  Both are None if any input is None.
    """
    if any(v is None for v in [likelihood, impact, asset_criticality]):
        return None, None

    score = likelihood * impact * asset_criticality

    if score >= 80:
        rating = "Critical"
    elif score >= 45:
        rating = "High"
    elif score >= 15:
        rating = "Medium"
    else:
        rating = "Low"

    return score, rating


# ---------------------------------------------------------------------------
# Engagement-level risk (weighted average)
# ---------------------------------------------------------------------------


def calculate_engagement_risk(
    findings: list[Finding],
) -> tuple[float | None, str | None]:
    """
    Calculate weighted average risk for an engagement based on its findings.

    Weight by severity: Critical=5, High=4, Medium=3, Low=2, Info=1.
    Returns (average_score, rating) or (None, None) if no scored findings.
    """
    scored_findings = [f for f in findings if f.risk_score is not None]
    if not scored_findings:
        return None, None

    total_weighted = sum(
        f.risk_score * SEVERITY_WEIGHT.get(f.severity, 1) for f in scored_findings
    )
    total_weight = sum(SEVERITY_WEIGHT.get(f.severity, 1) for f in scored_findings)
    avg_score = total_weighted / total_weight

    if avg_score >= 80:
        rating = "Critical"
    elif avg_score >= 45:
        rating = "High"
    elif avg_score >= 15:
        rating = "Medium"
    else:
        rating = "Low"

    return round(avg_score, 1), rating


# ---------------------------------------------------------------------------
# Organization-level risk
# ---------------------------------------------------------------------------


def calculate_org_risk(
    engagements_with_scores: list[float | None],
) -> tuple[float | None, str | None]:
    """
    Calculate org-wide risk from all active engagement scores.

    Returns (average_score, rating) or (None, None) if no scored engagements.
    """
    scores = [s for s in engagements_with_scores if s is not None]
    if not scores:
        return None, None

    avg = sum(scores) / len(scores)

    if avg >= 80:
        rating = "Critical"
    elif avg >= 45:
        rating = "High"
    elif avg >= 15:
        rating = "Medium"
    else:
        rating = "Low"

    return round(avg, 1), rating
