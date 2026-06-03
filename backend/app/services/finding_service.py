"""
Finding service — MITRE ATT&CK ID validation and severity ordering helpers.

MITRE technique IDs must follow the pattern ``^T\\d{4,5}$`` (the letter T
followed by exactly 4 or 5 decimal digits).  Sub-techniques such as
``T1059.001`` are **not** accepted under requirement 5.6.

Severity ordering maps each severity label to a sort weight so that Critical
findings sort before High, Medium, Low, and Info in list queries and PDF
reports (requirement 5.6, 5.8).

Requirements: 5.2, 5.3, 5.6
"""

from __future__ import annotations

import re

from fastapi import HTTPException

# ---------------------------------------------------------------------------
# MITRE ATT&CK technique ID pattern
# ---------------------------------------------------------------------------

# Matches T followed by 4-5 digits, optionally followed by .NNN sub-technique.
# Examples that match : T1059, T10059, T1059.001, T1059.999
# Examples that do NOT match : T999 (too few), t1059 (wrong case)
MITRE_PATTERN: re.Pattern[str] = re.compile(r"^T\d{4,5}(\.\d{3})?$")


def validate_mitre_id(mitre_id: str) -> None:
    """Raise HTTPException(400) when *mitre_id* does not match the pattern.

    A valid MITRE ATT&CK technique ID is the uppercase letter ``T`` followed
    by exactly 4 or 5 decimal digits (e.g. ``T1059``, ``T10059``).
    Sub-techniques (e.g. ``T1059.001``) and any other format are rejected.

    Parameters
    ----------
    mitre_id:
        The MITRE ATT&CK technique ID string to validate.

    Raises
    ------
    HTTPException(400)
        When *mitre_id* does not match ``^T\\d{4,5}$``.
    """
    if not MITRE_PATTERN.match(mitre_id):
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_MITRE_ID",
                "message": (
                    f"Invalid MITRE ATT&CK technique ID '{mitre_id}'. "
                    "Expected format: T followed by 4-5 digits, optionally "
                    "followed by .NNN for sub-techniques (e.g. T1059, T1059.001)."
                ),
            },
        )


# ---------------------------------------------------------------------------
# Severity ordering
# ---------------------------------------------------------------------------

# Maps each severity label to an integer weight.  Lower numbers sort first,
# so Critical (1) appears before High (2), Medium (3), Low (4), and Info (5).
SEVERITY_ORDER: dict[str, int] = {
    "Critical": 1,
    "High": 2,
    "Medium": 3,
    "Low": 4,
    "Info": 5,
}


def severity_sort_key(severity: str) -> int:
    """Return the sort weight for *severity*.

    The weight is used when ordering findings by severity — Critical is first
    (weight 1), Info is last (weight 5).  If an unrecognised value is
    supplied the function returns ``len(SEVERITY_ORDER) + 1`` so that unknown
    severities sort to the end rather than raising an exception.

    Parameters
    ----------
    severity:
        A severity label string (one of Critical, High, Medium, Low, Info).

    Returns
    -------
    int
        The ordering integer for *severity*.
    """
    return SEVERITY_ORDER.get(severity, len(SEVERITY_ORDER) + 1)
