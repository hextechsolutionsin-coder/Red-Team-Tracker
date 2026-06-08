"""finding_statuses

Expands the finding status CHECK constraint to support additional statuses:
reopened, on-hold, false-positive.

Revision ID: 0004
Revises: 0003
Create Date: 2025-01-20 00:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# upgrade — expand finding status constraint
# ---------------------------------------------------------------------------

def upgrade() -> None:
    op.drop_constraint("ck_findings_status", "findings", type_="check")
    op.create_check_constraint(
        "ck_findings_status",
        "findings",
        "status IN ('open', 'in-progress', 'remediated', 'verified', 'reopened', 'on-hold', 'false-positive')"
    )


# ---------------------------------------------------------------------------
# downgrade — restore original 4-state constraint
# ---------------------------------------------------------------------------

def downgrade() -> None:
    op.drop_constraint("ck_findings_status", "findings", type_="check")
    op.create_check_constraint(
        "ck_findings_status",
        "findings",
        "status IN ('open', 'in-progress', 'remediated', 'verified')"
    )
