"""purchase order priority

Revision ID: 0016
Revises: 0015

Adds `purchase_orders.priority` (Urgent / High / Medium / Low), shown on the
list and printed on the order. Existing orders get Medium.
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_orders",
                  sa.Column("priority", sa.String(20), nullable=False, server_default="Medium"))


def downgrade() -> None:
    op.drop_column("purchase_orders", "priority")