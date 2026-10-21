"""goods receipt note: acceptance and inspection

Revision ID: 0017
Revises: 0016

The goods receipt follows the company's GRN template:
- per line, `accepted_quantity` (what passed inspection and goes into stock)
  and `condition` (Good / Damaged / Short / Excess / Under Inspection);
- on the note, the delivery note / challan and its date, the transporter, the
  import / GD reference, inspection notes, discrepancy / damage details,
  whether the supplier's bill has gone to Finance, and who checked it.

Existing lines are set accepted = received - rejected, which is what they
already put into stock, and condition Good.
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mrn_lines", sa.Column("accepted_quantity", sa.Numeric(18, 4), nullable=False, server_default="0"))
    op.add_column("mrn_lines", sa.Column("condition", sa.String(30), nullable=False, server_default="Good"))
    op.execute("update mrn_lines set accepted_quantity = greatest(received_quantity - rejected_quantity, 0)")
    for name, kind in [("delivery_note_number", sa.String(100)), ("delivery_date", sa.Date()),
                       ("transporter", sa.String(150)), ("gd_reference", sa.String(100)),
                       ("inspection_notes", sa.Text()), ("discrepancy_notes", sa.Text()),
                       ("checked_by", sa.String(150))]:
        op.add_column("material_receiving_notes", sa.Column(name, kind, nullable=True))
    op.add_column("material_receiving_notes",
                  sa.Column("bill_to_finance", sa.String(10), nullable=False, server_default="No"))


def downgrade() -> None:
    for name in ["bill_to_finance", "checked_by", "discrepancy_notes", "inspection_notes", "gd_reference",
                 "transporter", "delivery_date", "delivery_note_number"]:
        op.drop_column("material_receiving_notes", name)
    op.drop_column("mrn_lines", "condition")
    op.drop_column("mrn_lines", "accepted_quantity")