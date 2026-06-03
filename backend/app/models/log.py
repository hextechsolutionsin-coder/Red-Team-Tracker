import uuid

from sqlalchemy import ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OperatorLog(Base):
    """Maps to the ``operator_log`` table — append-only audit trail.

    No UPDATE or DELETE is performed on this table at the application layer.
    """

    __tablename__ = "operator_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    action_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Machine-readable action label, e.g. 'finding_created'",
    )
    actor_username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    engagement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("engagements.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_entity_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="e.g. 'finding', 'user'",
    )
    target_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    occurred_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
