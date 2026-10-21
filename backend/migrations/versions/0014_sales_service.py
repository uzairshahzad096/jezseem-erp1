"""service sales documents

Revision ID: 0014
Revises: 0013

Adds `sales_documents.is_service`: the order (or quotation) is for a
service, so it is printed as a Service Invoice instead of a sales or sales
tax invoice. Existing documents get false.
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sales_documents",
                  sa.Column("is_service", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("sales_documents", "is_service")