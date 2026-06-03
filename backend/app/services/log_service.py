"""
Log service — single write path to the ``operator_log`` table.

Every module that triggers a loggable action calls ``record_log(...)``
instead of inserting ``OperatorLog`` rows directly.  This ensures
Property 22 coverage without duplication.

Requirements: 7.1, 7.2, 7.3
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.log import OperatorLog

logger = logging.getLogger("redboard.log_service")


async def record_log(
    db: AsyncSession,
    action_type: str,
    actor_username: str,
    description: str,
    engagement_id: uuid.UUID | None = None,
    target_entity_type: str | None = None,
    target_entity_id: uuid.UUID | None = None,
    **_kwargs: Any,  # absorb any extra keyword args from call sites
) -> None:
    """
    Insert a single append-only ``OperatorLog`` row.

    Parameters
    ----------
    db:
        Active ``AsyncSession`` for the current request.
    action_type:
        Machine-readable label such as ``'user_created'`` or
        ``'finding_deleted'``.  Maximum 64 characters.
    actor_username:
        Username of the authenticated user who triggered the action.
    description:
        Human-readable description of the event.
    engagement_id:
        UUID of the related engagement, or ``None`` when the action is
        not engagement-scoped (Requirement 7.3).
    target_entity_type:
        Optional entity type string, e.g. ``'user'``, ``'finding'``.
    target_entity_id:
        Optional UUID of the target entity.

    Notes
    -----
    - This function does **not** commit the session.  The caller is
      responsible for committing (or relying on the enclosing transaction).
    - On unexpected error, the exception is caught and logged so that a
      failed audit write does not abort the primary business transaction.
    """
    try:
        entry = OperatorLog(
            action_type=action_type[:64],
            actor_username=actor_username[:64],
            description=description,
            engagement_id=engagement_id,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
        )
        db.add(entry)
        # Flush so the row gets an ID but do NOT commit here;
        # the caller controls the transaction boundary.
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to write operator log entry (action=%s, actor=%s): %s",
            action_type,
            actor_username,
            exc,
        )
