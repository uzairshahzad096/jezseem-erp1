"""one live landed costing per shipment

Revision ID: 0021
Revises: 0020

The screen already refuses a second costing for a shipment, but two requests
arriving together (a double click) both passed that check and created
LC-2600006 and LC-2600007 for SHP-2600009 15ms apart. The database now holds
the rule: a shipment has at most one costing that is not cancelled.
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("create unique index uq_landed_cost_live_per_shipment on landed_costs (shipment_id) "
               "where shipment_id is not null and status <> 'Cancelled'")


def downgrade() -> None:
    op.execute("drop index uq_landed_cost_live_per_shipment")
