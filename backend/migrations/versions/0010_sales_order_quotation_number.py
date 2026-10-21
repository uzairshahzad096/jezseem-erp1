"""sales_documents.quotation_number

Revision ID: 0010
Revises: 0009

The sales-order import added this column directly in the database to carry
the old ERP's "Quotation No#". This revision records it, so a fresh database
built from migrations has the same shape. On the existing database the
column is already there and nothing changes (IF NOT EXISTS).
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("alter table sales_documents add column if not exists quotation_number varchar(100)")


def downgrade() -> None:
    # Deliberately left in place: the column holds imported data that existed
    # before this revision, and dropping it would destroy that data.
    pass
