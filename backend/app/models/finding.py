import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Finding(Base):
    """Maps to the ``findings`` table."""

    __tablename__ = "findings"

    __table_args__ = (
        CheckConstraint(
            "severity IN ('Critical', 'High', 'Medium', 'Low', 'Info')",
            name="ck_findings_severity",
        ),
        CheckConstraint(
            "status IN ('open', 'in-progress', 'remediated', 'verified')",
            name="ck_findings_status",
        ),
        CheckConstraint(
            "char_length(reproduction_steps) <= 10000",
            name="ck_findings_reproduction_steps_len",
        ),
        CheckConstraint(
            "char_length(remediation_recs) <= 10000",
            name="ck_findings_remediation_recs_len",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    engagement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("engagements.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    mitre_id: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )
    mitre_name: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )
    reproduction_steps: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    remediation_recs: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
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
