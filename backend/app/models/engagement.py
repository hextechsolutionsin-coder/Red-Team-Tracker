import uuid

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Engagement(Base):
    """Maps to the ``engagements`` table."""

    __tablename__ = "engagements"

    __table_args__ = (
        CheckConstraint(
            "char_length(description) <= 2000",
            name="ck_engagements_description_len",
        ),
        CheckConstraint(
            "char_length(scope) <= 5000",
            name="ck_engagements_scope_len",
        ),
        CheckConstraint(
            "end_date >= start_date",
            name="ck_engagements_dates",
        ),
        CheckConstraint(
            "status IN ('planned', 'active', 'on-hold', 'remediation', 'completed', 'reopened', 'archived')",
            name="ck_engagements_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    scope: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    start_date: Mapped[object] = mapped_column(
        Date,
        nullable=False,
    )
    end_date: Mapped[object] = mapped_column(
        Date,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default=text("'planned'"),
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    created_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
    updated_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )


class EngagementOperator(Base):
    """Maps to the ``engagement_operators`` join table (many-to-many)."""

    __tablename__ = "engagement_operators"

    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("engagements.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    assigned_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
