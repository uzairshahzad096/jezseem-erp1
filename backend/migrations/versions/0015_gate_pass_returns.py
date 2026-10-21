"""gate pass returns

Revision ID: 0015
Revises: 0014

- `gate_passes.expected_return_date`: when goods on a returnable outward pass
  are due back.
- `gate_pass_lines.reference_line_id`: on an inward pass, the outward pass
  line the goods are returning against, so returns are counted per item and
  can never exceed what went out.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gate_passes", sa.Column("expected_return_date", sa.Date(), nullable=True))
    op.add_column("gate_pass_lines", sa.Column(
        "reference_line_id", postgresql.UUID(as_uuid=True),
        sa.ForeignKey("gate_pass_lines.id", name="fk_gate_pass_line_reference"), nullable=True))
    op.create_index("ix_gate_pass_lines_reference_line_id", "gate_pass_lines", ["reference_line_id"])


def downgrade() -> None:
    op.drop_index("ix_gate_pass_lines_reference_line_id", table_name="gate_pass_lines")
    op.drop_column("gate_pass_lines", "reference_line_id")
    op.drop_column("gate_passes", "expected_return_date")