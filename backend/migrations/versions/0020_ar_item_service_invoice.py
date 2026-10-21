"""receivable items for service invoices

Revision ID: 0020
Revises: 0019

A posted service invoice (Calibration / Services) is a receivable like a sales
invoice, so an AR item may now come from one. The one-source rule is kept:
exactly one of sales document, receipt, opening line or service invoice.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

OLD = ("(sales_document_id is not null)::int + (receipt_id is not null)::int "
       "+ (opening_line_id is not null)::int = 1")
NEW = ("(sales_document_id is not null)::int + (receipt_id is not null)::int "
       "+ (opening_line_id is not null)::int + (service_invoice_id is not null)::int = 1")


def upgrade() -> None:
    op.add_column("ar_items", sa.Column("service_invoice_id", UUID(as_uuid=True),
                                        sa.ForeignKey("svc_invoices.id"), nullable=True))
    op.execute("create unique index uq_ar_item_service_invoice on ar_items (service_invoice_id) "
               "where service_invoice_id is not null")
    op.drop_constraint("ck_ar_item_one_source", "ar_items", type_="check")
    op.create_check_constraint("ck_ar_item_one_source", "ar_items", NEW)


def downgrade() -> None:
    op.drop_constraint("ck_ar_item_one_source", "ar_items", type_="check")
    op.create_check_constraint("ck_ar_item_one_source", "ar_items", OLD)
    op.execute("drop index uq_ar_item_service_invoice")
    op.drop_column("ar_items", "service_invoice_id")
