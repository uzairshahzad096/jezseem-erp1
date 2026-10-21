"""receivable items for manual journal lines

Revision ID: 0025
Revises: 0024

A manual journal may now debit or credit a customer's receivable account
(1130). Each such line becomes an AR item of type JOURNAL when the journal
posts, so the AR aging and reconciliation stay in step with the ledger. The
one-source rule is kept: exactly one of sales document, receipt, opening
line, service invoice or journal line.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

OLD_SOURCE = ("(sales_document_id is not null)::int + (receipt_id is not null)::int "
              "+ (opening_line_id is not null)::int + (service_invoice_id is not null)::int = 1")
NEW_SOURCE = ("(sales_document_id is not null)::int + (receipt_id is not null)::int "
              "+ (opening_line_id is not null)::int + (service_invoice_id is not null)::int "
              "+ (journal_line_id is not null)::int = 1")
OLD_TYPES = "item_type in ('INVOICE','DEBIT_NOTE','CREDIT_NOTE','RECEIPT','OPENING')"
NEW_TYPES = "item_type in ('INVOICE','DEBIT_NOTE','CREDIT_NOTE','RECEIPT','OPENING','JOURNAL')"


def upgrade() -> None:
    op.add_column("ar_items", sa.Column("journal_line_id", UUID(as_uuid=True),
                                        sa.ForeignKey("journal_entry_lines.id"), nullable=True))
    op.execute("create unique index uq_ar_item_journal_line on ar_items (journal_line_id) "
               "where journal_line_id is not null")
    op.drop_constraint("ck_ar_item_one_source", "ar_items", type_="check")
    op.create_check_constraint("ck_ar_item_one_source", "ar_items", NEW_SOURCE)
    op.drop_constraint("ck_ar_item_type", "ar_items", type_="check")
    op.create_check_constraint("ck_ar_item_type", "ar_items", NEW_TYPES)


def downgrade() -> None:
    op.drop_constraint("ck_ar_item_type", "ar_items", type_="check")
    op.create_check_constraint("ck_ar_item_type", "ar_items", OLD_TYPES)
    op.drop_constraint("ck_ar_item_one_source", "ar_items", type_="check")
    op.create_check_constraint("ck_ar_item_one_source", "ar_items", OLD_SOURCE)
    op.execute("drop index uq_ar_item_journal_line")
    op.drop_column("ar_items", "journal_line_id")
