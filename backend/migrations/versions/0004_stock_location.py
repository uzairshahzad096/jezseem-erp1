"""stock movements record the location they happened at

Revision ID: 0004
Revises: 0003

Stock was tracked per item and company only, so "how much is at Jezseem FSD"
could not be answered — every movement landed in one undifferentiated pool.
A sales order already names the location it ships from, so the ledger now
records it and the Product Stock report can break the balance down.

The column is nullable: existing movements have no location, and a document
whose location text matches nothing in Item Locations still posts its
movement rather than failing. Those show as "Unassigned" in the report.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stock_ledger_entries",
        sa.Column("location_id", UUID(as_uuid=True), sa.ForeignKey("item_locations.id"),
                  nullable=True),
    )
    # The stock report groups by item and location, so both sides of that
    # lookup want an index.
    op.create_index(
        "ix_stock_ledger_entries_location_id", "stock_ledger_entries", ["location_id"]
    )
    op.create_index(
        "ix_stock_ledger_item_location", "stock_ledger_entries", ["item_id", "location_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_stock_ledger_item_location", table_name="stock_ledger_entries")
    op.drop_index("ix_stock_ledger_entries_location_id", table_name="stock_ledger_entries")
    op.drop_column("stock_ledger_entries", "location_id")
