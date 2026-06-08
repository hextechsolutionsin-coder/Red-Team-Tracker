"""risk_scoring

Adds risk scoring columns to the findings table to support ISO 27001:2022
and NIST CSF 2.0 framework-based risk assessment.

New columns:
  - likelihood          Integer (1-5), nullable
  - impact              Integer (1-5), nullable
  - asset_criticality   Integer (1-5), nullable
  - risk_score          Integer, nullable (computed: likelihood × impact × asset_criticality)
  - risk_rating         String(16), nullable (Critical/High/Medium/Low)
  - affected_asset_type String(32), nullable
  - nist_csf_function   String(16), nullable
  - iso_control         String(16), nullable

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-15 00:00:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# upgrade — add risk scoring columns
# ---------------------------------------------------------------------------

def upgrade() -> None:
    op.add_column("findings", sa.Column("likelihood", sa.Integer(), nullable=True))
    op.add_column("findings", sa.Column("impact", sa.Integer(), nullable=True))
    op.add_column("findings", sa.Column("asset_criticality", sa.Integer(), nullable=True))
    op.add_column("findings", sa.Column("risk_score", sa.Integer(), nullable=True))
    op.add_column("findings", sa.Column("risk_rating", sa.String(16), nullable=True))
    op.add_column("findings", sa.Column("affected_asset_type", sa.String(32), nullable=True))
    op.add_column("findings", sa.Column("nist_csf_function", sa.String(16), nullable=True))
    op.add_column("findings", sa.Column("iso_control", sa.String(16), nullable=True))


# ---------------------------------------------------------------------------
# downgrade — remove risk scoring columns
# ---------------------------------------------------------------------------

def downgrade() -> None:
    op.drop_column("findings", "iso_control")
    op.drop_column("findings", "nist_csf_function")
    op.drop_column("findings", "affected_asset_type")
    op.drop_column("findings", "risk_rating")
    op.drop_column("findings", "risk_score")
    op.drop_column("findings", "asset_criticality")
    op.drop_column("findings", "impact")
    op.drop_column("findings", "likelihood")
