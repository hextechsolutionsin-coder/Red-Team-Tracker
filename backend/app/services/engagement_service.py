"""
Engagement service — status machine and field-edit guard helpers.

The engagement lifecycle supports the following transitions:

    planned → active → on-hold → remediation → completed → archived

With additional flexibility:
    on-hold → active (resume)
    remediation → active (reopen)
    completed → reopened → active

Requirements: 4.3, 4.9
"""

from __future__ import annotations

from fastapi import HTTPException

# Canonical order of engagement statuses (for reference/display).
STATUS_ORDER: list[str] = ["planned", "active", "on-hold", "remediation", "completed", "reopened", "archived"]

# Valid transitions: maps current status to a list of allowed next statuses.
VALID_TRANSITIONS: dict[str, list[str]] = {
    "planned":     ["active"],
    "active":      ["on-hold", "remediation", "completed"],
    "on-hold":     ["active"],
    "remediation": ["active", "completed"],
    "completed":   ["archived", "reopened"],
    "reopened":    ["active"],
    "archived":    [],  # final state
}


def validate_transition(current: str, requested: str) -> None:
    """Raise HTTPException(400) unless *requested* is a valid transition from *current*.

    Parameters
    ----------
    current:
        The engagement's current status value (must be in STATUS_ORDER).
    requested:
        The status value being requested (must be in STATUS_ORDER).

    Raises
    ------
    HTTPException(400)
        When the transition is not valid.
    """
    if current not in VALID_TRANSITIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_STATUS",
                "message": f"Current status '{current}' is not a recognised engagement status.",
            },
        )

    if requested not in STATUS_ORDER:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_STATUS",
                "message": f"Requested status '{requested}' is not a recognised engagement status.",
            },
        )

    allowed = VALID_TRANSITIONS.get(current, [])
    if requested not in allowed:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_STATUS_TRANSITION",
                "message": (
                    f"Invalid transition: '{current}' → '{requested}'. "
                    f"Allowed: {', '.join(allowed) or 'none (final state)'}."
                ),
            },
        )


def is_editable_status(status: str) -> bool:
    """Return whether non-status fields may be updated for the given status.

    Non-status fields (name, description, scope, start_date, end_date) are
    frozen once an engagement reaches "completed" or "archived" — requirement 4.9.

    Parameters
    ----------
    status:
        The engagement's current status value.

    Returns
    -------
    bool
        ``True`` if the engagement's non-status fields may be modified;
        ``False`` for 'completed' and 'archived' engagements.
    """
    return status not in {"completed", "archived"}
