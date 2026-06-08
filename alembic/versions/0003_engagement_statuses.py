"""engagement_statuses

Expands the engagement status CHECK constraint to support additional lifecycle
states: on-hold, remediation, reopened.

Revision ID: 0003
Revises: 0002
Create Date: 2025-01-20 00:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# upgrade — expand engagement status constraint
# ---------------------------------------------------------------------------

def upgrade() -> None:
    op.drop_constraint("ck_engagements_status", "engagements", type_="check")
    op.create_check_constraint(
        "ck_engagements_status",
        "engagements",
        "status IN ('planned', 'active', 'on-hold', 'remediation', 'completed', 'reopened', 'archived')"
    )


# ---------------------------------------------------------------------------
# downgrade — restore original 4-state constraint
# ---------------------------------------------------------------------------

def downgrade() -> None:
    op.drop_constraint("ck_engagements_status", "engagements", type_="check")
    op.create_check_constraint(
        "ck_engagements_status",
        "engagements",
        "status IN ('planned', 'active', 'completed', 'archived')"
    )
