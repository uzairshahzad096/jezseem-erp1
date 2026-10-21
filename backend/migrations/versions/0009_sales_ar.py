"""sales invoices, customer receipts, credit/debit notes and the AR subledger

Revision ID: 0009
Revises: 0008

Finance Phase 2. Invoices, credit notes and debit notes are further doc_types
on the existing `sales_documents` table (which already holds quotations and
sales orders), so there is no second invoice table. What is new:

- master data: payment terms, payment methods, tax codes, AR settings;
- `customer_receipts`;
- the AR subledger: `ar_items` (one immutable row per posted receivable
  document) and `ar_allocations` (receipt/credit ↔ invoice). Outstanding is
  always amount − active allocations, never a stored, editable balance.

Changes to existing tables are additive, nullable columns, with two
exceptions:
- `uq_sales_doc_number` is replaced by two partial unique indexes. Quotations
  and sales orders keep exactly today's rule; the new types are unique per
  financial year, so invoice numbers can restart each year.
- The account control-type check gains CUSTOMER_ADVANCE.

No existing quotation, sales order, customer or stock row is modified.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
MONEY = sa.Numeric(18, 2)
NEW_TYPES = "('sales_invoice','credit_note','debit_note')"

PERMISSIONS = [
    ("sales", "view", "sales.invoice.view", "View sales invoices"),
    ("sales", "create", "sales.invoice.create", "Create sales invoices"),
    ("sales", "edit", "sales.invoice.edit", "Edit draft sales invoices"),
    ("sales", "confirm", "sales.invoice.confirm", "Confirm sales invoices"),
    ("sales", "post", "sales.invoice.post", "Post sales invoices to the ledger"),
    ("sales", "cancel", "sales.invoice.cancel", "Cancel / reverse sales invoices"),
    ("sales", "credit_approve", "sales.invoice.credit_approve", "Approve invoices over the credit limit"),
    ("ar", "view", "ar.view", "View receivables, receipts and notes"),
    ("ar", "create", "ar.receipt.create", "Create and edit draft customer receipts"),
    ("ar", "post", "ar.receipt.post", "Post customer receipts"),
    ("ar", "allocate", "ar.receipt.allocate", "Allocate and unallocate receipts and credits"),
    ("ar", "reverse", "ar.receipt.reverse", "Reverse posted customer receipts"),
    ("ar", "create", "ar.credit_note.create", "Create credit and debit notes"),
    ("ar", "post", "ar.credit_note.post", "Post credit and debit notes"),
    ("ar", "reverse", "ar.credit_note.reverse", "Reverse posted credit and debit notes"),
    ("ar", "reports", "ar.reports", "Customer statements, aging, reconciliation and registers"),
    ("ar", "settings", "ar.settings", "Payment terms, payment methods, tax codes and AR settings"),
]


def audit_columns():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("updated_by", UUID, sa.ForeignKey("users.id")),
    ]


def upgrade() -> None:
    # ------------------------------------------------------------ chart
    op.drop_constraint("ck_account_control_type", "accounts", type_="check")
    op.create_check_constraint(
        "ck_account_control_type", "accounts",
        "control_type is null or control_type in "
        "('RECEIVABLE','PAYABLE','INVENTORY','BANK','CASH','TAX','GRNI','CUSTOMER_ADVANCE')")

    # ------------------------------------------------------------ master data
    op.create_table(
        "payment_terms",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_cash", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        *audit_columns(),
        sa.UniqueConstraint("company_id", "code", name="uq_payment_term_code"),
        sa.CheckConstraint("days >= 0", name="ck_payment_term_days"),
    )
    op.create_table(
        "payment_methods",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("requires_reference", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("default_account_id", UUID, sa.ForeignKey("accounts.id")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        *audit_columns(),
        sa.UniqueConstraint("company_id", "code", name="uq_payment_method_code"),
        sa.CheckConstraint("kind in ('CASH','BANK','CHEQUE','ONLINE','OTHER')", name="ck_payment_method_kind"),
    )
    op.create_table(
        "tax_codes",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("tax_type", sa.String(20), nullable=False),
        sa.Column("rate", sa.Numeric(9, 4), nullable=False, server_default="0"),
        sa.Column("output_account_id", UUID, sa.ForeignKey("accounts.id")),
        sa.Column("effective_from", sa.Date),
        sa.Column("effective_to", sa.Date),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("description", sa.Text),
        *audit_columns(),
        sa.UniqueConstraint("company_id", "code", name="uq_tax_code"),
        sa.CheckConstraint("tax_type in ('SALES_TAX','EXEMPT','ZERO_RATED','OTHER')", name="ck_tax_type"),
        sa.CheckConstraint("rate >= 0 and rate < 100", name="ck_tax_rate"),
        sa.CheckConstraint("tax_type in ('SALES_TAX','OTHER') or rate = 0", name="ck_tax_exempt_zero"),
    )
    op.create_table(
        "ar_settings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, unique=True),
        sa.Column("credit_limit_policy", sa.String(10), nullable=False, server_default="WARN"),
        sa.Column("sales_order_cutoff_date", sa.Date),
        sa.Column("allow_quotation_invoice", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("default_payment_term_id", UUID, sa.ForeignKey("payment_terms.id")),
        sa.Column("aging_buckets", sa.String(60), nullable=False, server_default="30,60,90,120"),
        *audit_columns(),
        sa.CheckConstraint("credit_limit_policy in ('NONE','WARN','BLOCK','APPROVAL')", name="ck_ar_credit_policy"),
    )

    # ------------------------------------------------------------ customers
    op.add_column("business_partners", sa.Column("credit_limit", MONEY))
    op.add_column("business_partners", sa.Column(
        "default_payment_term_id", UUID, sa.ForeignKey("payment_terms.id")))

    # ------------------------------------------------------------ sales documents
    cols = [
        sa.Column("financial_year_id", UUID, sa.ForeignKey("financial_years.id"), index=True),
        sa.Column("due_date", sa.Date),
        sa.Column("due_date_overridden", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("payment_term_id", UUID, sa.ForeignKey("payment_terms.id")),
        sa.Column("billing_address", sa.Text),
        sa.Column("shipping_address", sa.Text),
        sa.Column("quotation_id", UUID, sa.ForeignKey("sales_documents.id")),
        sa.Column("gate_pass_id", UUID, sa.ForeignKey("gate_passes.id")),
        sa.Column("tax_inclusive", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_cash_sale", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("cash_account_id", UUID, sa.ForeignKey("accounts.id")),
        sa.Column("reason_code", sa.String(30)),
        sa.Column("reason", sa.Text),
        sa.Column("journal_entry_id", UUID, sa.ForeignKey("journal_entries.id")),
        sa.Column("cancel_journal_id", UUID, sa.ForeignKey("journal_entries.id")),
        sa.Column("confirmed_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("posted_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.Text),
        sa.Column("credit_check_status", sa.String(20)),
        sa.Column("credit_approved_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("credit_approved_at", sa.DateTime(timezone=True)),
    ]
    for column in cols:
        op.add_column("sales_documents", column)

    op.add_column("sales_document_lines", sa.Column(
        "source_line_id", UUID, sa.ForeignKey("sales_document_lines.id"), index=True))
    op.add_column("sales_document_lines", sa.Column(
        "gate_pass_line_id", UUID, sa.ForeignKey("gate_pass_lines.id"), index=True))
    op.add_column("sales_document_lines", sa.Column("tax_code_id", UUID, sa.ForeignKey("tax_codes.id")))

    op.drop_constraint("uq_sales_doc_number", "sales_documents", type_="unique")
    op.execute(f"""create unique index uq_sales_doc_number_legacy on sales_documents
                   (company_id, doc_type, doc_number) where doc_type not in {NEW_TYPES}""")
    op.execute(f"""create unique index uq_sales_doc_number_fy on sales_documents
                   (company_id, doc_type, financial_year_id, doc_number) where doc_type in {NEW_TYPES}""")

    # ------------------------------------------------------------ receipts
    op.create_table(
        "customer_receipts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("branch_id", UUID, sa.ForeignKey("branches.id"), index=True),
        sa.Column("financial_year_id", UUID, sa.ForeignKey("financial_years.id"), nullable=False),
        sa.Column("receipt_number", sa.String(40), nullable=False),
        sa.Column("receipt_date", sa.Date, nullable=False, index=True),
        sa.Column("customer_id", UUID, sa.ForeignKey("business_partners.id"), nullable=False, index=True),
        sa.Column("payment_method_id", UUID, sa.ForeignKey("payment_methods.id"), nullable=False),
        sa.Column("deposit_account_id", UUID, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="PKR"),
        sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("amount_base", MONEY, nullable=False),
        sa.Column("reference", sa.String(100)),
        sa.Column("cheque_number", sa.String(50)),
        sa.Column("cheque_date", sa.Date),
        sa.Column("bank_name", sa.String(150)),
        sa.Column("notes", sa.Text),
        sa.Column("planned_allocations", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
        sa.Column("journal_entry_id", UUID, sa.ForeignKey("journal_entries.id")),
        sa.Column("reversal_journal_id", UUID, sa.ForeignKey("journal_entries.id")),
        sa.Column("posted_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("reversed_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("reversed_at", sa.DateTime(timezone=True)),
        sa.Column("reverse_reason", sa.Text),
        sa.Column("cancelled_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        *audit_columns(),
        sa.UniqueConstraint("company_id", "financial_year_id", "receipt_number", name="uq_receipt_number"),
        sa.CheckConstraint("amount > 0", name="ck_receipt_amount"),
        sa.CheckConstraint("exchange_rate > 0", name="ck_receipt_rate"),
        sa.CheckConstraint("status in ('DRAFT','POSTED','REVERSED','CANCELLED')", name="ck_receipt_status"),
    )

    # ------------------------------------------------------------ AR subledger
    op.create_table(
        "ar_items",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("branch_id", UUID, sa.ForeignKey("branches.id")),
        sa.Column("customer_id", UUID, sa.ForeignKey("business_partners.id"), nullable=False, index=True),
        sa.Column("item_type", sa.String(12), nullable=False),
        # AR: the balance sits on the receivable account. ADVANCE: on the
        # customer-advances account (receipts, opening advances).
        sa.Column("kind", sa.String(8), nullable=False, server_default="AR"),
        sa.Column("sales_document_id", UUID, sa.ForeignKey("sales_documents.id")),
        sa.Column("receipt_id", UUID, sa.ForeignKey("customer_receipts.id")),
        sa.Column("opening_line_id", UUID, sa.ForeignKey("opening_balance_lines.id")),
        sa.Column("document_number", sa.String(50), nullable=False),
        sa.Column("document_date", sa.Date, nullable=False),
        sa.Column("due_date", sa.Date),
        sa.Column("currency", sa.String(10), nullable=False, server_default="PKR"),
        sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("amount_base", MONEY, nullable=False),
        sa.Column("journal_entry_id", UUID, sa.ForeignKey("journal_entries.id")),
        sa.Column("status", sa.String(10), nullable=False, server_default="OPEN"),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id")),
        sa.CheckConstraint("amount <> 0", name="ck_ar_item_amount"),
        sa.CheckConstraint("item_type in ('INVOICE','DEBIT_NOTE','CREDIT_NOTE','RECEIPT','OPENING')",
                           name="ck_ar_item_type"),
        sa.CheckConstraint("kind in ('AR','ADVANCE')", name="ck_ar_item_kind"),
        sa.CheckConstraint("status in ('OPEN','CANCELLED')", name="ck_ar_item_status"),
        sa.CheckConstraint("(sales_document_id is not null)::int + (receipt_id is not null)::int "
                           "+ (opening_line_id is not null)::int = 1", name="ck_ar_item_one_source"),
    )
    op.create_index("ix_ar_items_open", "ar_items", ["company_id", "customer_id", "status"])
    op.execute("create unique index uq_ar_item_sales_doc on ar_items (sales_document_id) where sales_document_id is not null")
    op.execute("create unique index uq_ar_item_receipt on ar_items (receipt_id) where receipt_id is not null")
    op.execute("create unique index uq_ar_item_opening on ar_items (opening_line_id) where opening_line_id is not null")

    op.create_table(
        "ar_allocations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("from_item_id", UUID, sa.ForeignKey("ar_items.id"), nullable=False, index=True),
        sa.Column("to_item_id", UUID, sa.ForeignKey("ar_items.id"), nullable=False, index=True),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("amount_base", MONEY, nullable=False),
        sa.Column("allocation_date", sa.Date, nullable=False),
        sa.Column("journal_entry_id", UUID, sa.ForeignKey("journal_entries.id")),
        sa.Column("status", sa.String(10), nullable=False, server_default="ACTIVE"),
        sa.Column("reversed_at", sa.DateTime(timezone=True)),
        sa.Column("reversed_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("reversal_journal_id", UUID, sa.ForeignKey("journal_entries.id")),
        sa.Column("reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id")),
        sa.CheckConstraint("amount > 0", name="ck_ar_allocation_amount"),
        sa.CheckConstraint("from_item_id <> to_item_id", name="ck_ar_allocation_distinct"),
        sa.CheckConstraint("status in ('ACTIVE','REVERSED')", name="ck_ar_allocation_status"),
    )

    # Opening AR already posted under Phase 1 becomes subledger items.
    op.execute("""
        insert into ar_items (id, company_id, branch_id, customer_id, item_type, kind, opening_line_id,
                              document_number, document_date, due_date, currency, exchange_rate,
                              amount, amount_base, journal_entry_id, status, created_by)
        select gen_random_uuid(), b.company_id, coalesce(l.branch_id, b.branch_id), l.customer_id, 'OPENING', 'AR',
               l.id, coalesce(l.reference, b.batch_number), coalesce(l.document_date, b.cutover_date),
               coalesce(l.due_date, l.document_date, b.cutover_date), 'PKR', 1, l.amount, l.amount,
               b.journal_entry_id, 'OPEN', b.posted_by
        from opening_balance_lines l join opening_balance_batches b on b.id = l.batch_id
        where b.status in ('POSTED','COMPLETED') and l.schedule = 'AR'
          and l.customer_id is not null and coalesce(l.amount, 0) <> 0
    """)

    _triggers()
    _permissions()


def _triggers() -> None:
    op.execute(rf"""
    create or replace function sales_ar_document_guard() returns trigger language plpgsql as $$
    declare
        v_free text[] := array['status','cancelled_by','cancelled_at','cancel_reason','cancel_journal_id',
                               'updated_at','updated_by'];
        v_touch text[] := array['updated_at','updated_by'];
    begin
        if tg_op = 'DELETE' then
            if old.doc_type in {NEW_TYPES} and old.status <> 'DRAFT' then
                raise exception '% % is % and cannot be deleted.', replace(old.doc_type, '_', ' '),
                    old.doc_number, old.status;
            end if;
            return old;
        end if;
        if old.doc_type not in {NEW_TYPES} then
            return new;
        end if;
        if new.doc_type is distinct from old.doc_type then
            raise exception 'A document''s type cannot change.';
        end if;
        if old.status = 'CANCELLED'
           and (to_jsonb(new) - v_touch) is distinct from (to_jsonb(old) - v_touch) then
            raise exception '% % is cancelled and can no longer change.', replace(old.doc_type, '_', ' '), old.doc_number;
        end if;
        if old.status = 'POSTED'
           and (new.status not in ('POSTED','CANCELLED')
                or (to_jsonb(new) - v_free) is distinct from (to_jsonb(old) - v_free)) then
            raise exception '% % is posted and cannot be edited. Use a credit note or cancel it.',
                replace(old.doc_type, '_', ' '), old.doc_number;
        end if;
        return new;
    end $$;
    """)
    op.execute("""create trigger trg_sales_ar_document_guard before update or delete on sales_documents
                  for each row execute function sales_ar_document_guard();""")

    op.execute(rf"""
    create or replace function sales_ar_line_guard() returns trigger language plpgsql as $$
    declare
        v_type text;
        v_status text;
        v_doc uuid;
    begin
        v_doc := case when tg_op = 'DELETE' then old.document_id else new.document_id end;
        select doc_type, status into v_type, v_status from sales_documents where id = v_doc for share;
        if found and v_type in {NEW_TYPES} and v_status <> 'DRAFT' then
            raise exception 'Lines of a % % cannot be changed.', lower(v_status), replace(v_type, '_', ' ');
        end if;
        if tg_op = 'UPDATE' and old.document_id <> new.document_id then
            select doc_type, status into v_type, v_status from sales_documents where id = old.document_id for share;
            if found and v_type in {NEW_TYPES} and v_status <> 'DRAFT' then
                raise exception 'Lines of a % % cannot be changed.', lower(v_status), replace(v_type, '_', ' ');
            end if;
        end if;
        if tg_op = 'DELETE' then return old; end if;
        return new;
    end $$;
    """)
    op.execute("""create trigger trg_sales_ar_line_guard before insert or update or delete on sales_document_lines
                  for each row execute function sales_ar_line_guard();""")

    op.execute(r"""
    create or replace function customer_receipt_guard() returns trigger language plpgsql as $$
    declare
        v_free text[] := array['status','reversal_journal_id','reversed_by','reversed_at','reverse_reason',
                               'updated_at','updated_by'];
        v_touch text[] := array['updated_at','updated_by'];
    begin
        if tg_op = 'DELETE' then
            if old.status <> 'DRAFT' then
                raise exception 'Receipt % is % and cannot be deleted.', old.receipt_number, old.status;
            end if;
            return old;
        end if;
        if tg_op = 'INSERT' then
            if new.status <> 'DRAFT' then
                raise exception 'A receipt must be created as DRAFT.';
            end if;
            return new;
        end if;
        if old.status in ('REVERSED','CANCELLED')
           and (to_jsonb(new) - v_touch) is distinct from (to_jsonb(old) - v_touch) then
            raise exception 'Receipt % is % and can no longer change.', old.receipt_number, old.status;
        end if;
        if old.status = 'POSTED'
           and (new.status not in ('POSTED','REVERSED')
                or (to_jsonb(new) - v_free) is distinct from (to_jsonb(old) - v_free)) then
            raise exception 'Receipt % is posted and cannot be edited. Reverse it instead.', old.receipt_number;
        end if;
        return new;
    end $$;
    """)
    op.execute("""create trigger trg_customer_receipt_guard before insert or update or delete on customer_receipts
                  for each row execute function customer_receipt_guard();""")

    op.execute(r"""
    create or replace function ar_item_guard() returns trigger language plpgsql as $$
    begin
        if tg_op = 'DELETE' then
            raise exception 'Receivable items are never deleted; cancel the document instead.';
        end if;
        if old.status = 'CANCELLED'
           or new.status not in ('OPEN','CANCELLED')
           or (to_jsonb(new) - array['status','cancelled_at']) is distinct from (to_jsonb(old) - array['status','cancelled_at']) then
            raise exception 'A receivable item can only move from OPEN to CANCELLED.';
        end if;
        return new;
    end $$;
    """)
    op.execute("""create trigger trg_ar_item_guard before update or delete on ar_items
                  for each row execute function ar_item_guard();""")

    op.execute(r"""
    create or replace function ar_allocation_guard() returns trigger language plpgsql as $$
    declare
        v_free text[] := array['status','reversed_at','reversed_by','reversal_journal_id','reason'];
    begin
        if tg_op = 'DELETE' then
            raise exception 'Allocations are never deleted; unallocate instead.';
        end if;
        if old.status <> 'ACTIVE' or new.status <> 'REVERSED'
           or (to_jsonb(new) - v_free) is distinct from (to_jsonb(old) - v_free) then
            raise exception 'An allocation can only be reversed, once.';
        end if;
        return new;
    end $$;
    """)
    op.execute("""create trigger trg_ar_allocation_guard before update or delete on ar_allocations
                  for each row execute function ar_allocation_guard();""")


def _permissions() -> None:
    bind = op.get_bind()
    for module, action, code, description in PERMISSIONS:
        bind.execute(sa.text("""
            insert into permissions (id, module, action, code, description)
            values (gen_random_uuid(), :module, :action, :code, :description)
            on conflict (code) do nothing
        """), {"module": module, "action": action, "code": code, "description": description})
    bind.execute(sa.text("""
        insert into role_permissions (role_id, permission_id)
        select r.id, p.id from roles r cross join permissions p
        where r.name = 'Administrator' and p.code = any(:codes)
        on conflict do nothing
    """), {"codes": [p[2] for p in PERMISSIONS]})


def downgrade() -> None:
    bind = op.get_bind()
    codes = [p[2] for p in PERMISSIONS]
    bind.execute(sa.text("delete from role_permissions where permission_id in "
                         "(select id from permissions where code = any(:c))"), {"c": codes})
    bind.execute(sa.text("delete from permissions where code = any(:c)"), {"c": codes})

    for trigger, table in [("trg_ar_allocation_guard", "ar_allocations"), ("trg_ar_item_guard", "ar_items"),
                           ("trg_customer_receipt_guard", "customer_receipts"),
                           ("trg_sales_ar_line_guard", "sales_document_lines"),
                           ("trg_sales_ar_document_guard", "sales_documents")]:
        op.execute(f"drop trigger if exists {trigger} on {table}")
    for fn in ["ar_allocation_guard", "ar_item_guard", "customer_receipt_guard", "sales_ar_line_guard",
               "sales_ar_document_guard"]:
        op.execute(f"drop function if exists {fn}()")

    op.drop_table("ar_allocations")
    op.drop_table("ar_items")
    op.drop_table("customer_receipts")

    # Invoices, notes and their lines exist only from this revision.
    op.execute(f"delete from sales_document_lines where document_id in "
               f"(select id from sales_documents where doc_type in {NEW_TYPES})")
    op.execute(f"delete from sales_documents where doc_type in {NEW_TYPES}")
    op.execute("drop index if exists uq_sales_doc_number_fy")
    op.execute("drop index if exists uq_sales_doc_number_legacy")
    op.create_unique_constraint("uq_sales_doc_number", "sales_documents", ["company_id", "doc_type", "doc_number"])

    for column in ["tax_code_id", "gate_pass_line_id", "source_line_id"]:
        op.drop_column("sales_document_lines", column)
    for column in ["credit_approved_at", "credit_approved_by", "credit_check_status", "cancel_reason",
                   "cancelled_at", "cancelled_by", "posted_at", "posted_by", "confirmed_at", "confirmed_by",
                   "cancel_journal_id", "journal_entry_id", "reason", "reason_code", "cash_account_id",
                   "is_cash_sale", "tax_inclusive", "gate_pass_id", "quotation_id", "shipping_address",
                   "billing_address", "payment_term_id", "due_date_overridden", "due_date", "financial_year_id"]:
        op.drop_column("sales_documents", column)
    op.drop_column("business_partners", "default_payment_term_id")
    op.drop_column("business_partners", "credit_limit")

    op.drop_table("ar_settings")
    op.drop_table("tax_codes")
    op.drop_table("payment_methods")
    op.drop_table("payment_terms")

    op.execute("update accounts set control_type = null, is_control_account = false "
               "where control_type = 'CUSTOMER_ADVANCE'")
    op.drop_constraint("ck_account_control_type", "accounts", type_="check")
    op.create_check_constraint(
        "ck_account_control_type", "accounts",
        "control_type is null or control_type in ('RECEIVABLE','PAYABLE','INVENTORY','BANK','CASH','TAX','GRNI')")
