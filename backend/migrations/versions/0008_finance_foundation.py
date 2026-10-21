"""finance foundation: chart of accounts, periods, journals, opening balances, audit

Revision ID: 0008
Revises: 0007

Finance Phase 1. Everything here is additive. Companies, branches, financial
years, users, partners and items are referenced by foreign key, never copied,
and no existing business row is touched. The single change to an existing
table is a nullable `branch_id` on `document_sequences`, so finance numbering
can run per branch. Rows already in that table keep their meaning.

The accounting rules that must never be broken are enforced by the database
as well as the service layer, so a script or a future module that skips the
service still cannot post an unbalanced journal or edit a posted one:

- a journal is inserted as DRAFT and becomes POSTED only when its lines
  balance, number at least two, sit in an OPEN period that covers the date,
  and hit active posting accounts of the same company;
- a POSTED journal may only become REVERSED; REVERSED and CANCELLED are final;
- lines change only while their journal is DRAFT;
- audit_logs is append-only.

No journal, balance or valuation is created from existing data.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
MONEY = sa.Numeric(18, 2)

#: (code, name, normal balance, statement, order). The eight top-level
#: families the Phase 1 spec numbers 1000–8999.
ACCOUNT_TYPES = [
    ("ASSET", "Assets", "DEBIT", "BS", 1),
    ("LIABILITY", "Liabilities", "CREDIT", "BS", 2),
    ("EQUITY", "Equity", "CREDIT", "BS", 3),
    ("REVENUE", "Revenue", "CREDIT", "PL", 4),
    ("COST_OF_SALES", "Cost of Sales", "DEBIT", "PL", 5),
    ("EXPENSE", "Operating Expenses", "DEBIT", "PL", 6),
    ("OTHER_INCOME", "Other Income", "CREDIT", "PL", 7),
    ("OTHER_EXPENSE", "Other Expenses", "DEBIT", "PL", 8),
]

FINANCE_PERMISSIONS = [
    ("view", "finance.view", "View finance screens"),
    ("create", "finance.create", "Create draft journals"),
    ("edit", "finance.edit", "Edit draft journals"),
    ("post", "finance.post", "Post journals and opening balances"),
    ("approve", "finance.approve", "Approve journals and opening balances"),
    ("reverse", "finance.reverse", "Reverse posted journals"),
    ("close_period", "finance.close_period", "Close, reopen and lock accounting periods"),
    ("opening_balance", "finance.opening_balance", "Prepare and import opening balances"),
    ("chart_of_accounts", "finance.chart_of_accounts", "Maintain the chart of accounts and finance setup"),
    ("reports", "finance.reports", "View general ledger, trial balance and finance reports"),
    ("audit", "finance.audit", "View the audit log"),
]


def audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("updated_by", UUID, sa.ForeignKey("users.id")),
    ]


def upgrade() -> None:
    # ------------------------------------------------------------ reference
    op.create_table(
        "account_types",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("code", sa.String(30), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("normal_balance", sa.String(6), nullable=False),
        sa.Column("statement", sa.String(2), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.CheckConstraint("normal_balance in ('DEBIT','CREDIT')", name="ck_account_type_balance"),
        sa.CheckConstraint("statement in ('BS','PL')", name="ck_account_type_statement"),
    )
    bind = op.get_bind()
    for code, name, balance, statement, order in ACCOUNT_TYPES:
        bind.execute(sa.text("""
            insert into account_types (id, code, name, normal_balance, statement, sort_order)
            values (gen_random_uuid(), :code, :name, :balance, :statement, :order)
        """), {"code": code, "name": name, "balance": balance,
               "statement": statement, "order": order})

    op.create_table(
        "account_groups",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("account_type_id", UUID, sa.ForeignKey("account_types.id"), nullable=False),
        sa.Column("parent_id", UUID, sa.ForeignKey("account_groups.id")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *audit_columns(),
        sa.UniqueConstraint("company_id", "code", name="uq_account_group_code"),
    )

    op.create_table(
        "accounts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("account_type_id", UUID, sa.ForeignKey("account_types.id"), nullable=False),
        sa.Column("account_group_id", UUID, sa.ForeignKey("account_groups.id")),
        sa.Column("parent_id", UUID, sa.ForeignKey("accounts.id"), index=True),
        sa.Column("normal_balance", sa.String(6), nullable=False),
        sa.Column("is_postable", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_control_account", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("control_type", sa.String(20)),
        sa.Column("allow_manual_posting", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("currency", sa.String(10)),
        sa.Column("description", sa.Text),
        *audit_columns(),
        sa.UniqueConstraint("company_id", "code", name="uq_account_code"),
        sa.CheckConstraint("normal_balance in ('DEBIT','CREDIT')", name="ck_account_balance"),
        sa.CheckConstraint(
            "control_type is null or control_type in "
            "('RECEIVABLE','PAYABLE','INVENTORY','BANK','CASH','TAX','GRNI')",
            name="ck_account_control_type"),
        sa.CheckConstraint("parent_id is null or parent_id <> id", name="ck_account_not_own_parent"),
    )

    op.create_table(
        "cost_centers",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("parent_id", UUID, sa.ForeignKey("cost_centers.id")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *audit_columns(),
        sa.UniqueConstraint("company_id", "code", name="uq_cost_center_code"),
    )

    op.create_table(
        "accounting_periods",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("financial_year_id", UUID, sa.ForeignKey("financial_years.id"),
                  nullable=False, index=True),
        sa.Column("period_number", sa.Integer, nullable=False),
        sa.Column("name", sa.String(30), nullable=False),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="OPEN"),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("closed_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", UUID, sa.ForeignKey("users.id")),
        *audit_columns(),
        sa.UniqueConstraint("financial_year_id", "period_number", name="uq_period_number"),
        sa.CheckConstraint("status in ('OPEN','CLOSED','LOCKED')", name="ck_period_status"),
        sa.CheckConstraint("period_end >= period_start", name="ck_period_dates"),
    )
    op.create_index("ix_period_company_dates", "accounting_periods",
                    ["company_id", "period_start", "period_end"])

    # ------------------------------------------------------------ numbering
    op.create_table(
        "document_series",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("doc_type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("prefix", sa.String(20), nullable=False),
        sa.Column("padding", sa.Integer, nullable=False, server_default="6"),
        sa.Column("format", sa.String(60), nullable=False, server_default="{prefix}-{seq}"),
        sa.Column("reset_each_fiscal_year", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("per_branch", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *audit_columns(),
        sa.UniqueConstraint("company_id", "doc_type", name="uq_document_series_type"),
        sa.CheckConstraint("padding between 1 and 12", name="ck_series_padding"),
    )

    op.add_column("document_sequences",
                  sa.Column("branch_id", UUID, sa.ForeignKey("branches.id"), nullable=True))
    op.drop_constraint("uq_sequence_scope", "document_sequences", type_="unique")
    op.execute("""
        create unique index uq_sequence_scope_branch on document_sequences
            (company_id, fiscal_year, doc_type,
             coalesce(branch_id, '00000000-0000-0000-0000-000000000000'::uuid))
    """)

    # ------------------------------------------------------------ journals
    op.create_table(
        "journal_entries",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("branch_id", UUID, sa.ForeignKey("branches.id"), index=True),
        sa.Column("financial_year_id", UUID, sa.ForeignKey("financial_years.id"), nullable=False),
        sa.Column("accounting_period_id", UUID, sa.ForeignKey("accounting_periods.id"),
                  nullable=False, index=True),
        sa.Column("journal_number", sa.String(40), nullable=False),
        sa.Column("journal_date", sa.Date, nullable=False),
        sa.Column("journal_type", sa.String(20), nullable=False, server_default="MANUAL"),
        sa.Column("event_code", sa.String(50)),
        sa.Column("document_type", sa.String(50)),
        sa.Column("document_id", UUID),
        sa.Column("description", sa.Text),
        sa.Column("reference", sa.String(100)),
        sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
        sa.Column("source_module", sa.String(30)),
        sa.Column("source_reference", sa.String(100)),
        sa.Column("currency", sa.String(10), nullable=False, server_default="PKR"),
        sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("total_debit", MONEY, nullable=False, server_default="0"),
        sa.Column("total_credit", MONEY, nullable=False, server_default="0"),
        sa.Column("submitted_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("posted_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.Text),
        sa.Column("reversed_entry_id", UUID, sa.ForeignKey("journal_entries.id")),
        sa.Column("reversed_by_entry_id", UUID, sa.ForeignKey("journal_entries.id")),
        *audit_columns(),
        sa.UniqueConstraint("company_id", "financial_year_id", "journal_number",
                            name="uq_journal_number"),
        sa.CheckConstraint(
            "status in ('DRAFT','SUBMITTED','APPROVED','POSTED','REVERSED','CANCELLED')",
            name="ck_journal_status"),
        sa.CheckConstraint(
            "journal_type in ('MANUAL','ADJUSTMENT','OPENING','REVERSAL','SYSTEM')",
            name="ck_journal_type"),
        sa.CheckConstraint("exchange_rate > 0", name="ck_journal_rate"),
    )
    op.create_index("ix_journal_company_date", "journal_entries", ["company_id", "journal_date"])
    op.create_index("ix_journal_status", "journal_entries", ["company_id", "status"])
    op.create_index("ix_journal_document", "journal_entries", ["document_type", "document_id"])
    # A source document can have only one live posting per event. After a
    # reversal the original is REVERSED, so the document may post again.
    op.execute("""
        create unique index uq_journal_document_event on journal_entries
            (company_id, document_type, document_id, coalesce(event_code, ''))
        where status = 'POSTED' and document_id is not null and journal_type <> 'REVERSAL'
    """)

    op.create_table(
        "journal_entry_lines",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("journal_entry_id", UUID,
                  sa.ForeignKey("journal_entries.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("line_number", sa.Integer, nullable=False),
        sa.Column("account_id", UUID, sa.ForeignKey("accounts.id"), nullable=False, index=True),
        sa.Column("description", sa.Text),
        sa.Column("debit", MONEY, nullable=False, server_default="0"),
        sa.Column("credit", MONEY, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(10), nullable=False, server_default="PKR"),
        sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("base_debit", MONEY, nullable=False, server_default="0"),
        sa.Column("base_credit", MONEY, nullable=False, server_default="0"),
        sa.Column("customer_id", UUID, sa.ForeignKey("business_partners.id"), index=True),
        sa.Column("supplier_id", UUID, sa.ForeignKey("business_partners.id"), index=True),
        sa.Column("inventory_item_id", UUID, sa.ForeignKey("inventory_items.id"), index=True),
        sa.Column("quantity", sa.Numeric(18, 4)),
        sa.Column("cost_center_id", UUID, sa.ForeignKey("cost_centers.id")),
        sa.Column("branch_id", UUID, sa.ForeignKey("branches.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("debit >= 0 and credit >= 0", name="ck_line_non_negative"),
        sa.CheckConstraint("base_debit >= 0 and base_credit >= 0", name="ck_line_base_non_negative"),
        sa.CheckConstraint("(debit > 0 and credit = 0) or (credit > 0 and debit = 0)",
                           name="ck_line_one_side"),
        sa.CheckConstraint("(base_debit > 0 and base_credit = 0) or (base_credit > 0 and base_debit = 0)",
                           name="ck_line_base_one_side"),
        sa.CheckConstraint("exchange_rate > 0", name="ck_line_rate"),
        sa.CheckConstraint("customer_id is null or supplier_id is null", name="ck_line_one_party"),
        sa.UniqueConstraint("journal_entry_id", "line_number", name="uq_journal_line_number"),
    )
    op.create_index("ix_journal_line_company_account", "journal_entry_lines",
                    ["company_id", "account_id"])

    op.create_table(
        "posting_rules",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("event_code", sa.String(50), nullable=False),
        sa.Column("line_key", sa.String(40), nullable=False),
        sa.Column("account_id", UUID, sa.ForeignKey("accounts.id")),
        sa.Column("description", sa.String(255)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        *audit_columns(),
        sa.UniqueConstraint("company_id", "event_code", "line_key", name="uq_posting_rule"),
    )

    # ------------------------------------------------------------ opening balances
    op.create_table(
        "opening_balance_batches",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("branch_id", UUID, sa.ForeignKey("branches.id")),
        sa.Column("financial_year_id", UUID, sa.ForeignKey("financial_years.id"), nullable=False),
        sa.Column("batch_number", sa.String(40), nullable=False),
        sa.Column("cutover_date", sa.Date, nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
        sa.Column("source_document", sa.String(255)),
        sa.Column("notes", sa.Text),
        sa.Column("prepared_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("posted_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("journal_entry_id", UUID, sa.ForeignKey("journal_entries.id")),
        sa.Column("completed_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("total_debit", MONEY, nullable=False, server_default="0"),
        sa.Column("total_credit", MONEY, nullable=False, server_default="0"),
        *audit_columns(),
        sa.UniqueConstraint("company_id", "batch_number", name="uq_opening_batch_number"),
        sa.CheckConstraint(
            "status in ('DRAFT','VALIDATED','APPROVED','POSTED','COMPLETED','CANCELLED')",
            name="ck_opening_batch_status"),
    )
    # One live opening position per company, year and branch.
    op.execute("""
        create unique index uq_opening_batch_live on opening_balance_batches
            (company_id, financial_year_id,
             coalesce(branch_id, '00000000-0000-0000-0000-000000000000'::uuid))
        where status in ('POSTED','COMPLETED')
    """)

    op.create_table(
        "opening_balance_lines",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("batch_id", UUID, sa.ForeignKey("opening_balance_batches.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("schedule", sa.String(12), nullable=False),
        sa.Column("row_number", sa.Integer, nullable=False),
        sa.Column("account_code", sa.String(30)),
        sa.Column("account_name", sa.String(200)),
        sa.Column("account_id", UUID, sa.ForeignKey("accounts.id")),
        sa.Column("debit", MONEY, nullable=False, server_default="0"),
        sa.Column("credit", MONEY, nullable=False, server_default="0"),
        sa.Column("party_code", sa.String(50)),
        sa.Column("party_name", sa.String(255)),
        sa.Column("customer_id", UUID, sa.ForeignKey("business_partners.id")),
        sa.Column("supplier_id", UUID, sa.ForeignKey("business_partners.id")),
        sa.Column("item_code", sa.String(40)),
        sa.Column("inventory_item_id", UUID, sa.ForeignKey("inventory_items.id")),
        sa.Column("location_name", sa.String(150)),
        sa.Column("location_id", UUID, sa.ForeignKey("item_locations.id")),
        sa.Column("quantity", sa.Numeric(18, 4)),
        sa.Column("unit_cost", sa.Numeric(18, 4)),
        sa.Column("amount", MONEY),
        sa.Column("reference", sa.String(100)),
        sa.Column("document_date", sa.Date),
        sa.Column("due_date", sa.Date),
        sa.Column("bank_name", sa.String(150)),
        sa.Column("bank_account_number", sa.String(60)),
        sa.Column("statement_balance", MONEY),
        sa.Column("uncleared_deposits", MONEY),
        sa.Column("uncleared_payments", MONEY),
        sa.Column("branch_code", sa.String(50)),
        sa.Column("branch_id", UUID, sa.ForeignKey("branches.id")),
        sa.Column("raw", pg.JSONB),
        sa.Column("errors", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("schedule in ('GL','AR','AP','INVENTORY','BANK')",
                           name="ck_opening_line_schedule"),
        sa.CheckConstraint("debit >= 0 and credit >= 0", name="ck_opening_line_non_negative"),
    )

    op.create_table(
        "opening_balance_imports",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("batch_id", UUID, sa.ForeignKey("opening_balance_batches.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("schedule", sa.String(12), nullable=False),
        sa.Column("file_name", sa.String(255)),
        sa.Column("file_hash", sa.String(64), nullable=False, index=True),
        sa.Column("row_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("imported_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "opening_balance_reconciliations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("batch_id", UUID, sa.ForeignKey("opening_balance_batches.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("legacy_balance", MONEY),
        sa.Column("erp_balance", MONEY, nullable=False, server_default="0"),
        sa.Column("difference", MONEY),
        sa.Column("explanation", sa.Text),
        sa.Column("updated_by", UUID, sa.ForeignKey("users.id")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("batch_id", "category", name="uq_opening_reconciliation_category"),
    )

    # ------------------------------------------------------------ audit
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("company_id", UUID, sa.ForeignKey("companies.id"), index=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id"), index=True),
        sa.Column("username", sa.String(100)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False, index=True),
        sa.Column("action", sa.String(30), nullable=False, index=True),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("entity", sa.String(60)),
        sa.Column("entity_id", sa.String(64)),
        sa.Column("old_values", pg.JSONB),
        sa.Column("new_values", pg.JSONB),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("user_agent", sa.String(255)),
        sa.Column("reason", sa.Text),
    )
    op.create_index("ix_audit_entity", "audit_logs", ["entity", "entity_id"])

    _create_triggers()
    _seed_permissions(bind)


def _create_triggers() -> None:
    # Messages are written for the person at the screen: the API returns them
    # as they are.
    op.execute(r"""
    create or replace function fin_journal_guard() returns trigger
    language plpgsql as $$
    declare
        v_lines integer;
        v_dr numeric;
        v_cr numeric;
        v_bad integer;
        v_period accounting_periods%rowtype;
        v_free_after_post text[] := array['status','reversed_by_entry_id','updated_at','updated_by'];
        v_touch text[] := array['updated_at','updated_by'];
    begin
        if tg_op = 'DELETE' then
            if old.status <> 'DRAFT' then
                raise exception 'Journal % is % and cannot be deleted. Cancel or reverse it instead.',
                    old.journal_number, old.status;
            end if;
            return old;
        end if;

        if tg_op = 'INSERT' then
            if new.status <> 'DRAFT' then
                raise exception 'A journal must be created as DRAFT and posted once its lines are in place.';
            end if;
            return new;
        end if;

        if old.status in ('REVERSED', 'CANCELLED') then
            if (to_jsonb(new) - v_touch) is distinct from (to_jsonb(old) - v_touch) then
                raise exception 'Journal % is % and can no longer change.', old.journal_number, old.status;
            end if;
            return new;
        end if;

        if old.status = 'POSTED' then
            if new.status not in ('POSTED', 'REVERSED')
               or (to_jsonb(new) - v_free_after_post) is distinct from (to_jsonb(old) - v_free_after_post) then
                raise exception 'Journal % is posted and cannot be edited. Post a reversal or an adjustment instead.',
                    old.journal_number;
            end if;
            if new.status = 'REVERSED' and new.reversed_by_entry_id is null then
                raise exception 'Journal % can only be marked reversed by a reversal journal.', old.journal_number;
            end if;
            return new;
        end if;

        if new.status = 'REVERSED' then
            raise exception 'Only a posted journal can be reversed.';
        end if;

        if new.status = 'POSTED' then
            select count(*), coalesce(sum(base_debit), 0), coalesce(sum(base_credit), 0)
              into v_lines, v_dr, v_cr
              from journal_entry_lines where journal_entry_id = new.id;
            if v_lines < 2 then
                raise exception 'Journal % needs at least two lines to post.', new.journal_number;
            end if;
            if v_dr <> v_cr then
                raise exception 'Journal % is not balanced: debit % and credit %.', new.journal_number, v_dr, v_cr;
            end if;
            if v_dr = 0 then
                raise exception 'Journal % has no amount to post.', new.journal_number;
            end if;
            if new.total_debit <> v_dr or new.total_credit <> v_cr then
                raise exception 'Journal % totals do not match its lines.', new.journal_number;
            end if;

            select * into v_period from accounting_periods where id = new.accounting_period_id;
            if not found or v_period.company_id <> new.company_id
               or v_period.financial_year_id <> new.financial_year_id then
                raise exception 'Journal % points at a period of another company or year.', new.journal_number;
            end if;
            if v_period.status <> 'OPEN' then
                raise exception 'Period % is % and does not accept postings.', v_period.name, v_period.status;
            end if;
            if new.journal_date < v_period.period_start or new.journal_date > v_period.period_end then
                raise exception 'Journal date % is outside period %.', new.journal_date, v_period.name;
            end if;

            select count(*) into v_bad
              from journal_entry_lines l join accounts a on a.id = l.account_id
             where l.journal_entry_id = new.id
               and (a.company_id <> new.company_id or l.company_id <> new.company_id
                    or not a.is_active or not a.is_postable);
            if v_bad > 0 then
                raise exception 'Journal % uses an inactive, header or other-company account.', new.journal_number;
            end if;

            if new.posted_at is null then
                new.posted_at := now();
            end if;
        end if;
        return new;
    end $$;
    """)
    op.execute("""
        create trigger trg_fin_journal_guard
        before insert or update or delete on journal_entries
        for each row execute function fin_journal_guard();
    """)

    op.execute(r"""
    create or replace function fin_journal_line_guard() returns trigger
    language plpgsql as $$
    declare
        v_status text;
    begin
        if tg_op in ('UPDATE', 'DELETE') then
            -- FOR SHARE waits for a posting in progress, so a line cannot slip
            -- into a journal between its balance check and its commit.
            select status into v_status from journal_entries
             where id = old.journal_entry_id for share;
            if found and v_status <> 'DRAFT' then
                raise exception 'Lines of a % journal cannot be changed.', v_status;
            end if;
        end if;
        if tg_op in ('INSERT', 'UPDATE') then
            select status into v_status from journal_entries
             where id = new.journal_entry_id for share;
            if v_status is distinct from 'DRAFT' then
                raise exception 'Lines can only be added to a DRAFT journal (this one is %).', v_status;
            end if;
            return new;
        end if;
        return old;
    end $$;
    """)
    op.execute("""
        create trigger trg_fin_journal_line_guard
        before insert or update or delete on journal_entry_lines
        for each row execute function fin_journal_line_guard();
    """)

    op.execute(r"""
    create or replace function fin_period_guard() returns trigger
    language plpgsql as $$
    begin
        if old.status = 'LOCKED' and (to_jsonb(new) - array['updated_at','updated_by'])
                                     is distinct from (to_jsonb(old) - array['updated_at','updated_by']) then
            raise exception 'Period % is locked and cannot be changed.', old.name;
        end if;
        return new;
    end $$;
    """)
    op.execute("""
        create trigger trg_fin_period_guard before update on accounting_periods
        for each row execute function fin_period_guard();
    """)

    op.execute(r"""
    create or replace function fin_opening_batch_guard() returns trigger
    language plpgsql as $$
    declare
        v_free text[] := array['status','completed_by','completed_at','updated_at','updated_by'];
    begin
        if tg_op = 'DELETE' then
            if old.status <> 'DRAFT' then
                raise exception 'Opening batch % is % and cannot be deleted.', old.batch_number, old.status;
            end if;
            return old;
        end if;
        if old.status in ('COMPLETED', 'CANCELLED')
           and (to_jsonb(new) - array['updated_at','updated_by'])
               is distinct from (to_jsonb(old) - array['updated_at','updated_by']) then
            raise exception 'Opening batch % is % and can no longer change.', old.batch_number, old.status;
        end if;
        if old.status = 'POSTED'
           and (new.status not in ('POSTED', 'COMPLETED')
                or (to_jsonb(new) - v_free) is distinct from (to_jsonb(old) - v_free)) then
            raise exception 'Opening batch % is posted and cannot be edited.', old.batch_number;
        end if;
        return new;
    end $$;
    """)
    op.execute("""
        create trigger trg_fin_opening_batch_guard
        before update or delete on opening_balance_batches
        for each row execute function fin_opening_batch_guard();
    """)

    op.execute(r"""
    create or replace function fin_opening_line_guard() returns trigger
    language plpgsql as $$
    declare
        v_status text;
        v_batch uuid;
    begin
        v_batch := case when tg_op = 'DELETE' then old.batch_id else new.batch_id end;
        select status into v_status from opening_balance_batches where id = v_batch for share;
        if found and v_status not in ('DRAFT', 'VALIDATED') then
            raise exception 'Opening lines are frozen once the batch is %.', v_status;
        end if;
        if tg_op = 'DELETE' then return old; end if;
        return new;
    end $$;
    """)
    op.execute("""
        create trigger trg_fin_opening_line_guard
        before insert or update or delete on opening_balance_lines
        for each row execute function fin_opening_line_guard();
    """)

    op.execute(r"""
    create or replace function audit_log_append_only() returns trigger
    language plpgsql as $$
    begin
        raise exception 'The audit log is append-only.';
    end $$;
    """)
    op.execute("""
        create trigger trg_audit_log_append_only
        before update or delete on audit_logs
        for each row execute function audit_log_append_only();
    """)
    op.execute("""
        create trigger trg_audit_log_no_truncate
        before truncate on audit_logs
        for each statement execute function audit_log_append_only();
    """)


def _seed_permissions(bind) -> None:
    """Add the finance codes to the existing catalogue and give them to the
    Administrator role, so the screens work straight after `alembic upgrade`.
    The seed script adds the same codes idempotently."""
    for action, code, description in FINANCE_PERMISSIONS:
        bind.execute(sa.text("""
            insert into permissions (id, module, action, code, description)
            values (gen_random_uuid(), 'finance', :action, :code, :description)
            on conflict (code) do nothing
        """), {"action": action, "code": code, "description": description})
    bind.execute(sa.text("""
        insert into role_permissions (role_id, permission_id)
        select r.id, p.id from roles r cross join permissions p
        where r.name = 'Administrator' and p.code = any(:codes)
        on conflict do nothing
    """), {"codes": [code for _, code, _ in FINANCE_PERMISSIONS]})


def downgrade() -> None:
    codes = [code for _, code, _ in FINANCE_PERMISSIONS]
    bind = op.get_bind()
    bind.execute(sa.text("""
        delete from role_permissions where permission_id in
            (select id from permissions where code = any(:codes))
    """), {"codes": codes})
    bind.execute(sa.text("delete from permissions where code = any(:codes)"), {"codes": codes})

    for trigger, table in [
        ("trg_audit_log_no_truncate", "audit_logs"),
        ("trg_audit_log_append_only", "audit_logs"),
        ("trg_fin_opening_line_guard", "opening_balance_lines"),
        ("trg_fin_opening_batch_guard", "opening_balance_batches"),
        ("trg_fin_period_guard", "accounting_periods"),
        ("trg_fin_journal_line_guard", "journal_entry_lines"),
        ("trg_fin_journal_guard", "journal_entries"),
    ]:
        op.execute(f"drop trigger if exists {trigger} on {table}")
    for function in ["audit_log_append_only", "fin_opening_line_guard", "fin_opening_batch_guard",
                     "fin_period_guard", "fin_journal_line_guard", "fin_journal_guard"]:
        op.execute(f"drop function if exists {function}()")

    op.drop_table("audit_logs")
    op.drop_table("opening_balance_reconciliations")
    op.drop_table("opening_balance_imports")
    op.drop_table("opening_balance_lines")
    op.drop_table("opening_balance_batches")
    op.drop_table("posting_rules")
    op.drop_table("journal_entry_lines")
    op.drop_table("journal_entries")

    op.execute("drop index if exists uq_sequence_scope_branch")
    op.execute("delete from document_sequences where branch_id is not null")
    op.drop_column("document_sequences", "branch_id")
    op.create_unique_constraint("uq_sequence_scope", "document_sequences",
                                ["company_id", "fiscal_year", "doc_type"])

    op.drop_table("document_series")
    op.drop_table("accounting_periods")
    op.drop_table("cost_centers")
    op.drop_table("accounts")
    op.drop_table("account_groups")
    op.drop_table("account_types")
