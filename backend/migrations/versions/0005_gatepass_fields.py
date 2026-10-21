"""gate pass fields from the column mapping

Revision ID: 0005
Revises: 0004

Brings gate_passes and gate_pass_lines in line with the supplied OGP/IGP
column mapping: the location the goods leave from or return to, the party's
tax registrations as printed on the pass, the payment and reference fields,
and HS code / remarks per line.

All nullable — a gate pass is a movement note, and most of these are optional
on a real one.
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

HEADER_COLUMNS = [
    ("location", sa.String(150)),
    ("ntn", sa.String(50)),
    ("gst_number", sa.String(50)),
    ("payment_status", sa.String(30)),
    ("payment_reference", sa.String(150)),
    ("po_number", sa.String(100)),
    ("reference_number", sa.String(100)),
]

LINE_COLUMNS = [
    ("hs_code", sa.String(50)),
    ("remarks", sa.Text()),
]


def upgrade() -> None:
    for name, kind in HEADER_COLUMNS:
        op.add_column("gate_passes", sa.Column(name, kind, nullable=True))
    for name, kind in LINE_COLUMNS:
        op.add_column("gate_pass_lines", sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    for name, _ in LINE_COLUMNS:
        op.drop_column("gate_pass_lines", name)
    for name, _ in HEADER_COLUMNS:
        op.drop_column("gate_passes", name)
