"""
Engagement service — status machine and field-edit guard helpers.

The engagement lifecycle follows a strict forward-only order:

    planned → active → completed → archived

Requirements: 4.3, 4.9
"""

from __future__ import annotations

from fastapi import HTTPException

# Canonical order of engagement statuses.  Position in the list determines
# what is a valid "next" state: a transition is valid only if the requested
# status is exactly one position ahead of the current status.
STATUS_ORDER: list[str] = ["planned", "active", "completed", "archived"]


def validate_transition(current: str, requested: str) -> None:
    """Raise HTTPException(400) unless *requested* is exactly one step forward.

    Valid transitions:
        planned   → active
        active    → completed
        completed → archived

    Any attempt to skip a step, stay on the same status, or move backwards
    is rejected.

    Parameters
    ----------
    current:
        The engagement's current status value (must be in STATUS_ORDER).
    requested:
        The status value being requested (must be in STATUS_ORDER).

    Raises
    ------
    HTTPException(400)
        When the transition is not exactly one forward step.
    """
    try:
        current_index = STATUS_ORDER.index(current)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_STATUS",
                "message": f"Current status '{current}' is not a recognised engagement status.",
            },
        )

    try:
        requested_index = STATUS_ORDER.index(requested)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_STATUS",
                "message": f"Requested status '{requested}' is not a recognised engagement status.",
            },
        )

    if requested_index != current_index + 1:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_STATUS_TRANSITION",
                "message": (
                    f"Invalid status transition: '{current}' → '{requested}'. "
                    f"Expected next status: '{STATUS_ORDER[current_index + 1]}'"
                    if current_index + 1 < len(STATUS_ORDER)
                    else f"Invalid status transition: '{current}' is already the final status."
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
