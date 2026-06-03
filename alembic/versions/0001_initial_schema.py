"""initial_schema

Creates all tables for the Red Team Operations Tracker with every CHECK
constraint, foreign key, default value, and index as specified in the
design document.

Tables created:
  - users
  - sessions
  - engagements
  - engagement_operators
  - findings
  - evidence_files
  - operator_log

Revision ID: 0001
Revises: (none — this is the first migration)
Create Date: 2025-01-01 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# upgrade — create schema
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ------------------------------------------------------------------
    # users
    # Role is restricted to exactly three values.
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # CHECK: role must be one of the three defined values
        sa.CheckConstraint(
            "role IN ('admin', 'lead', 'operator')",
            name="ck_users_role",
        ),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )

    # ------------------------------------------------------------------
    # sessions
    # Server-side session store; cascades on user deletion.
    # ------------------------------------------------------------------
    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_sessions_user_id"),
            nullable=False,
        ),
        sa.Column(
            "last_activity",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    # Index to speed up session lookup by user (e.g. invalidation on role change)
    op.create_index(
        "ix_sessions_user_id",
        "sessions",
        ["user_id"],
    )

    # ------------------------------------------------------------------
    # engagements
    # CHECK constraints:
    #   - description length ≤ 2000 characters
    #   - scope length ≤ 5000 characters
    #   - end_date must be on or after start_date
    #   - status must be one of the four lifecycle values
    # ------------------------------------------------------------------
    op.create_table(
        "engagements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'planned'"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", name="fk_engagements_created_by"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # CHECK: description length
        sa.CheckConstraint(
            "char_length(description) <= 2000",
            name="ck_engagements_description_len",
        ),
        # CHECK: scope length
        sa.CheckConstraint(
            "char_length(scope) <= 5000",
            name="ck_engagements_scope_len",
        ),
        # CHECK: end_date must not precede start_date
        sa.CheckConstraint(
            "end_date >= start_date",
            name="ck_engagements_dates",
        ),
        # CHECK: status lifecycle values
        sa.CheckConstraint(
            "status IN ('planned', 'active', 'completed', 'archived')",
            name="ck_engagements_status",
        ),
    )
    # Index for common list queries: filter by status, sort by start_date asc
    op.create_index(
        "ix_engagements_status",
        "engagements",
        ["status"],
    )
    op.create_index(
        "ix_engagements_start_date",
        "engagements",
        ["start_date"],
    )

    # ------------------------------------------------------------------
    # engagement_operators  (many-to-many join table)
    # Composite PK; cascades on both sides.
    # ------------------------------------------------------------------
    op.create_table(
        "engagement_operators",
        sa.Column(
            "engagement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "engagements.id",
                ondelete="CASCADE",
                name="fk_engagement_operators_engagement_id",
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                ondelete="CASCADE",
                name="fk_engagement_operators_user_id",
            ),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "assigned_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # ------------------------------------------------------------------
    # findings
    # CHECK constraints:
    #   - severity must be one of the five defined values (case-sensitive)
    #   - status must be one of the four defined values
    #   - reproduction_steps length ≤ 10 000 characters
    #   - remediation_recs length ≤ 10 000 characters
    # Cascades from engagements.
    # ------------------------------------------------------------------
    op.create_table(
        "findings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "engagement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "engagements.id",
                ondelete="CASCADE",
                name="fk_findings_engagement_id",
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mitre_id", sa.String(16), nullable=True),
        sa.Column("mitre_name", sa.String(256), nullable=True),
        sa.Column("reproduction_steps", sa.Text(), nullable=True),
        sa.Column("remediation_recs", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", name="fk_findings_created_by"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # CHECK: severity must be one of exactly five values (case-sensitive)
        sa.CheckConstraint(
            "severity IN ('Critical', 'High', 'Medium', 'Low', 'Info')",
            name="ck_findings_severity",
        ),
        # CHECK: status must be one of exactly four values
        sa.CheckConstraint(
            "status IN ('open', 'in-progress', 'remediated', 'verified')",
            name="ck_findings_status",
        ),
        # CHECK: reproduction_steps length
        sa.CheckConstraint(
            "char_length(reproduction_steps) <= 10000",
            name="ck_findings_reproduction_steps_len",
        ),
        # CHECK: remediation_recs length
        sa.CheckConstraint(
            "char_length(remediation_recs) <= 10000",
            name="ck_findings_remediation_recs_len",
        ),
    )
    # Index for common list queries: filter by engagement, severity, status
    op.create_index(
        "ix_findings_engagement_id",
        "findings",
        ["engagement_id"],
    )
    op.create_index(
        "ix_findings_severity",
        "findings",
        ["severity"],
    )
    op.create_index(
        "ix_findings_status",
        "findings",
        ["status"],
    )
    # Default sort is created_at DESC
    op.create_index(
        "ix_findings_created_at",
        "findings",
        ["created_at"],
    )

    # ------------------------------------------------------------------
    # evidence_files
    # RESTRICT prevents orphaned files; cascade is handled at the
    # application layer (two-phase delete) per requirement 5.9.
    # ------------------------------------------------------------------
    op.create_table(
        "evidence_files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "findings.id",
                ondelete="RESTRICT",
                name="fk_evidence_files_finding_id",
            ),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(256), nullable=False),
        sa.Column(
            "stored_filename",
            sa.String(512),
            nullable=False,
            comment="{evidence_id}_{original_filename}",
        ),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", name="fk_evidence_files_uploaded_by"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_evidence_files_finding_id",
        "evidence_files",
        ["finding_id"],
    )

    # ------------------------------------------------------------------
    # operator_log  (append-only audit trail)
    # No UPDATE or DELETE is issued at the application layer.
    # engagement_id uses SET NULL so log entries survive engagement deletion.
    # ------------------------------------------------------------------
    op.create_table(
        "operator_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("actor_username", sa.String(64), nullable=False),
        sa.Column(
            "engagement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "engagements.id",
                ondelete="SET NULL",
                name="fk_operator_log_engagement_id",
            ),
            nullable=True,
        ),
        sa.Column("target_entity_type", sa.String(64), nullable=True),
        sa.Column("target_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    # Index to support dashboard recent-logs query and filtered log queries
    op.create_index(
        "ix_operator_log_occurred_at",
        "operator_log",
        ["occurred_at"],
    )
    op.create_index(
        "ix_operator_log_engagement_id",
        "operator_log",
        ["engagement_id"],
    )
    op.create_index(
        "ix_operator_log_actor_username",
        "operator_log",
        ["actor_username"],
    )
    op.create_index(
        "ix_operator_log_action_type",
        "operator_log",
        ["action_type"],
    )


# ---------------------------------------------------------------------------
# downgrade — drop schema in reverse dependency order
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Drop indexes and tables in reverse FK dependency order.

    # operator_log has no dependents
    op.drop_index("ix_operator_log_action_type", table_name="operator_log")
    op.drop_index("ix_operator_log_actor_username", table_name="operator_log")
    op.drop_index("ix_operator_log_engagement_id", table_name="operator_log")
    op.drop_index("ix_operator_log_occurred_at", table_name="operator_log")
    op.drop_table("operator_log")

    # evidence_files references findings
    op.drop_index("ix_evidence_files_finding_id", table_name="evidence_files")
    op.drop_table("evidence_files")

    # findings references engagements and users
    op.drop_index("ix_findings_created_at", table_name="findings")
    op.drop_index("ix_findings_status", table_name="findings")
    op.drop_index("ix_findings_severity", table_name="findings")
    op.drop_index("ix_findings_engagement_id", table_name="findings")
    op.drop_table("findings")

    # engagement_operators references engagements and users
    op.drop_table("engagement_operators")

    # engagements references users
    op.drop_index("ix_engagements_start_date", table_name="engagements")
    op.drop_index("ix_engagements_status", table_name="engagements")
    op.drop_table("engagements")

    # sessions references users
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")

    # users has no FK dependencies
    op.drop_table("users")
