"""tax withheld by the customer on a receipt

Revision ID: 0013
Revises: 0012

Adds `customer_receipts.wht_amount`: the part of a receipt the customer kept
back as withholding tax. The receipt's amount stays what the customer is
credited with; the bank is debited with the amount less the tax. Existing
receipts get 0.
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customer_receipts",
                  sa.Column("wht_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("customer_receipts", "wht_amount")
