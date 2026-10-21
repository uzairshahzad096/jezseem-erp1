"""
Chart of accounts: the standard structure, and the rules for changing it.

The standard chart is a starting structure for a Pakistani trading company,
numbered 1000–8999 as the Phase 1 spec proposes. It carries no balances and
is not a reconstruction of the old ERP's accounts, whose codes are unknown.
The accountant renames, adds and retires accounts freely. Nothing in the
system reads meaning from a code; control types and account types do that.

Two accounts are marked REQUIRES BUSINESS CONFIRMATION in their description
(freight on sales, and the purchase clearing route) because their treatment
depends on answers the business has not given yet.
"""

import uuid

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.audit.service import AuditContext, changed, record, snapshot
from app.finance.errors import FinanceError
from app.finance.events import EVENTS, rule_keys
from app.finance.models import (
    POSTED, REVERSED, Account, AccountGroup, AccountType, JournalEntry, JournalEntryLine,
    OpeningBalanceLine, PostingRule,
)

#: (code, name, account type, sort)
STANDARD_GROUPS = [
    ("CA", "Current Assets", "ASSET", 10),
    ("NCA", "Non-Current Assets", "ASSET", 20),
    ("CL", "Current Liabilities", "LIABILITY", 30),
    ("NCL", "Non-Current Liabilities", "LIABILITY", 40),
    ("EQ", "Equity", "EQUITY", 50),
    ("REV", "Revenue", "REVENUE", 60),
    ("COS", "Cost of Sales", "COST_OF_SALES", 70),
    ("OPEX", "Operating Expenses", "EXPENSE", 80),
    ("OI", "Other Income", "OTHER_INCOME", 90),
    ("OE", "Other Expenses", "OTHER_EXPENSE", 100),
]

# (code, name, type, parent, group, postable, control_type, control account,
#  normal balance override, description)
H, P = False, True
STANDARD_CHART: list[tuple] = [
    ("1000", "Assets", "ASSET", None, None, H, None, False, None, None),
    ("1100", "Current Assets", "ASSET", "1000", "CA", H, None, False, None, None),
    ("1110", "Cash in Hand", "ASSET", "1100", "CA", P, "CASH", False, None, None),
    ("1120", "Bank Accounts", "ASSET", "1100", "CA", H, None, False, None, None),
    ("1121", "Bank - Current Account", "ASSET", "1120", "CA", P, "BANK", False, None,
     "Rename to the actual bank and account number; add one account per bank account."),
    ("1130", "Accounts Receivable - Trade", "ASSET", "1100", "CA", P, "RECEIVABLE", True, None,
     "Control account: posted only with a customer, through receivables or opening balances."),
    ("1140", "Inventory", "ASSET", "1100", "CA", P, "INVENTORY", True, None,
     "Control account: posted by inventory documents and opening balances."),
    ("1150", "Advances to Suppliers", "ASSET", "1100", "CA", P, None, False, None, None),
    ("1160", "Advances to Employees", "ASSET", "1100", "CA", P, None, False, None, None),
    ("1170", "Prepayments", "ASSET", "1100", "CA", P, None, False, None, None),
    ("1180", "Input Sales Tax", "ASSET", "1100", "CA", P, "TAX", False, None, None),
    ("1185", "Advance Income Tax / WHT Receivable", "ASSET", "1100", "CA", P, "TAX", False, None, None),
    ("1190", "Other Receivables", "ASSET", "1100", "CA", P, None, False, None, None),
    ("1200", "Non-Current Assets", "ASSET", "1000", "NCA", H, None, False, None, None),
    ("1210", "Furniture and Fixtures", "ASSET", "1200", "NCA", P, None, False, None, None),
    ("1220", "Office Equipment", "ASSET", "1200", "NCA", P, None, False, None, None),
    ("1230", "Vehicles", "ASSET", "1200", "NCA", P, None, False, None, None),
    ("1240", "Computers", "ASSET", "1200", "NCA", P, None, False, None, None),
    ("1250", "Long-Term Deposits", "ASSET", "1200", "NCA", P, None, False, None, None),
    ("1290", "Accumulated Depreciation", "ASSET", "1200", "NCA", P, None, False, "CREDIT",
     "Contra-asset: carries a credit balance."),
    ("2000", "Liabilities", "LIABILITY", None, None, H, None, False, None, None),
    ("2100", "Current Liabilities", "LIABILITY", "2000", "CL", H, None, False, None, None),
    ("2110", "Accounts Payable - Trade", "LIABILITY", "2100", "CL", P, "PAYABLE", True, None,
     "Control account: posted only with a supplier, through payables or opening balances."),
    ("2115", "Goods Received Not Invoiced", "LIABILITY", "2100", "CL", P, "GRNI", True, None,
     "Clearing account between goods receipt and supplier invoice."),
    ("2120", "Accrued Expenses", "LIABILITY", "2100", "CL", P, None, False, None, None),
    ("2130", "Output Sales Tax Payable", "LIABILITY", "2100", "CL", P, "TAX", False, None, None),
    ("2140", "Withholding Tax Payable", "LIABILITY", "2100", "CL", P, "TAX", False, None, None),
    ("2150", "Income Tax Payable", "LIABILITY", "2100", "CL", P, "TAX", False, None, None),
    ("2160", "Advances from Customers", "LIABILITY", "2100", "CL", P, "CUSTOMER_ADVANCE", True, None,
     "Control account: unallocated customer receipts, posted only with a customer."),
    ("2170", "Short-Term Borrowings", "LIABILITY", "2100", "CL", P, None, False, None, None),
    ("2190", "Other Current Liabilities", "LIABILITY", "2100", "CL", P, None, False, None, None),
    ("2200", "Non-Current Liabilities", "LIABILITY", "2000", "NCL", H, None, False, None, None),
    ("2210", "Long-Term Loans", "LIABILITY", "2200", "NCL", P, None, False, None, None),
    ("3000", "Equity", "EQUITY", None, None, H, None, False, None, None),
    ("3100", "Owner's / Share Capital", "EQUITY", "3000", "EQ", P, None, False, None, None),
    ("3200", "Retained Earnings", "EQUITY", "3000", "EQ", P, None, False, None, None),
    ("3300", "Reserves", "EQUITY", "3000", "EQ", P, None, False, None, None),
    ("3400", "Drawings", "EQUITY", "3000", "EQ", P, None, False, "DEBIT",
     "Contra-equity: carries a debit balance."),
    ("4000", "Revenue", "REVENUE", None, None, H, None, False, None, None),
    ("4100", "Sales - Goods", "REVENUE", "4000", "REV", P, None, False, None, None),
    ("4200", "Sales - Services", "REVENUE", "4000", "REV", P, None, False, None, None),
    ("4300", "Freight Recovered", "REVENUE", "4000", "REV", P, None, False, None,
     "REQUIRES BUSINESS CONFIRMATION: whether freight charged to customers is revenue "
     "or a recovery against freight expense."),
    ("4900", "Sales Returns and Discounts", "REVENUE", "4000", "REV", P, None, False, "DEBIT",
     "Contra-revenue: carries a debit balance."),
    ("5000", "Cost of Sales", "COST_OF_SALES", None, None, H, None, False, None, None),
    ("5100", "Cost of Goods Sold", "COST_OF_SALES", "5000", "COS", P, None, False, None, None),
    ("5200", "Freight Inward", "COST_OF_SALES", "5000", "COS", P, None, False, None, None),
    ("5300", "Import Duties and Clearing (not capitalised)", "COST_OF_SALES", "5000", "COS", P,
     None, False, None, None),
    ("5400", "Inventory Adjustments", "COST_OF_SALES", "5000", "COS", P, None, False, None, None),
    ("6000", "Operating Expenses", "EXPENSE", None, None, H, None, False, None, None),
    ("6100", "Salaries and Wages", "EXPENSE", "6000", "OPEX", P, None, False, None, None),
    ("6110", "Rent", "EXPENSE", "6000", "OPEX", P, None, False, None, None),
    ("6120", "Utilities", "EXPENSE", "6000", "OPEX", P, None, False, None, None),
    ("6130", "Transportation and Vehicle Running", "EXPENSE", "6000", "OPEX", P, None, False, None, None),
    ("6140", "Office Expenses and Stationery", "EXPENSE", "6000", "OPEX", P, None, False, None, None),
    ("6150", "Communication", "EXPENSE", "6000", "OPEX", P, None, False, None, None),
    ("6160", "Repairs and Maintenance", "EXPENSE", "6000", "OPEX", P, None, False, None, None),
    ("6170", "Selling and Marketing", "EXPENSE", "6000", "OPEX", P, None, False, None, None),
    ("6180", "Legal and Professional", "EXPENSE", "6000", "OPEX", P, None, False, None, None),
    ("6190", "Depreciation", "EXPENSE", "6000", "OPEX", P, None, False, None, None),
    ("6900", "Miscellaneous Expenses", "EXPENSE", "6000", "OPEX", P, None, False, None, None),
    ("7000", "Other Income", "OTHER_INCOME", None, None, H, None, False, None, None),
    ("7100", "Other Income", "OTHER_INCOME", "7000", "OI", P, None, False, None, None),
    ("7200", "Exchange Gain", "OTHER_INCOME", "7000", "OI", P, None, False, None, None),
    ("8000", "Other Expenses", "OTHER_EXPENSE", None, None, H, None, False, None, None),
    ("8100", "Bank Charges and Financial Costs", "OTHER_EXPENSE", "8000", "OE", P, None, False, None, None),
    ("8200", "Exchange Loss", "OTHER_EXPENSE", "8000", "OE", P, None, False, None, None),
    ("8900", "Taxation", "OTHER_EXPENSE", "8000", "OE", P, None, False, None, None),
]

#: Default account for each (event, line). Only applied while the rule has
#: no account, so a company's own choices are never overwritten.
DEFAULT_RULES: dict[tuple[str, str], str] = {
    ("SALES_INVOICE_POSTED", "receivable"): "1130",
    ("SALES_INVOICE_POSTED", "revenue"): "4100",
    ("SALES_INVOICE_POSTED", "output_tax"): "2130",
    ("SALES_INVOICE_POSTED", "freight"): "4300",
    ("SALES_INVOICE_POSTED", "cogs"): "5100",
    ("SALES_INVOICE_POSTED", "inventory"): "1140",
    ("CUSTOMER_RECEIPT_POSTED", "bank_cash"): "1121",
    ("CUSTOMER_RECEIPT_POSTED", "wht"): "1185",
    ("CUSTOMER_RECEIPT_POSTED", "receivable"): "1130",
    # REQUIRES BUSINESS CONFIRMATION: once goods receipts post
    # STOCK_RECEIPT_POSTED (Dr Inventory / Cr GRNI), the purchase line should
    # clear GRNI (2115) instead of debiting inventory a second time.
    ("PURCHASE_INVOICE_POSTED", "purchase"): "1140",
    ("PURCHASE_INVOICE_POSTED", "input_tax"): "1180",
    ("PURCHASE_INVOICE_POSTED", "payable"): "2110",
    ("SUPPLIER_PAYMENT_POSTED", "payable"): "2110",
    ("SUPPLIER_PAYMENT_POSTED", "bank_cash"): "1121",
    ("SUPPLIER_PAYMENT_POSTED", "wht"): "2140",
    ("STOCK_RECEIPT_POSTED", "inventory"): "1140",
    ("STOCK_RECEIPT_POSTED", "grni"): "2115",
    ("STOCK_ISSUE_POSTED", "cogs"): "5100",
    ("STOCK_ISSUE_POSTED", "inventory"): "1140",
    ("EXPENSE_POSTED", "expense"): "6900",
    ("EXPENSE_POSTED", "input_tax"): "1180",
    ("EXPENSE_POSTED", "bank_cash"): "1110",
    ("DEPRECIATION_POSTED", "depreciation_expense"): "6190",
    ("DEPRECIATION_POSTED", "accumulated_depreciation"): "1290",
    # Phase 2 — sales and receivables
    ("SALES_INVOICE_POSTED", "discount"): "4900",
    ("CUSTOMER_RECEIPT_POSTED", "advance"): "2160",
    ("CUSTOMER_ADVANCE_ALLOCATED", "advance"): "2160",
    ("CUSTOMER_ADVANCE_ALLOCATED", "receivable"): "1130",
    ("CUSTOMER_RECEIPT_REVERSED", "advance"): "2160",
    ("CUSTOMER_RECEIPT_REVERSED", "bank_cash"): "1121",
    ("SALES_CREDIT_NOTE_POSTED", "returns"): "4900",
    ("SALES_CREDIT_NOTE_POSTED", "output_tax"): "2130",
    ("SALES_CREDIT_NOTE_POSTED", "freight"): "4300",
    ("SALES_CREDIT_NOTE_POSTED", "receivable"): "1130",
    ("SALES_DEBIT_NOTE_POSTED", "receivable"): "1130",
    ("SALES_DEBIT_NOTE_POSTED", "revenue"): "4100",
    ("SALES_DEBIT_NOTE_POSTED", "output_tax"): "2130",
}


def _types(db: Session) -> dict[str, AccountType]:
    return {t.code: t for t in db.scalars(select(AccountType))}


def install_standard_chart(db: Session, company_id: uuid.UUID, ctx: AuditContext | None) -> int:
    """Install the standard structure for a company that has no accounts yet.
    Returns the number of accounts created (0 if the company already has a chart)."""
    if db.scalar(select(exists().where(Account.company_id == company_id))):
        return 0
    types = _types(db)
    user_id = ctx.user_id if ctx else None

    groups: dict[str, AccountGroup] = {}
    for code, name, type_code, order in STANDARD_GROUPS:
        group = db.scalar(select(AccountGroup).where(
            AccountGroup.company_id == company_id, AccountGroup.code == code))
        if group is None:
            group = AccountGroup(company_id=company_id, code=code, name=name,
                                 account_type_id=types[type_code].id, sort_order=order,
                                 created_by=user_id)
            db.add(group)
        groups[code] = group
    db.flush()

    by_code: dict[str, Account] = {}
    for (code, name, type_code, parent, group, postable, control_type, is_control,
         balance, description) in STANDARD_CHART:
        account_type = types[type_code]
        account = Account(
            id=uuid.uuid4(), company_id=company_id, code=code, name=name,
            account_type_id=account_type.id,
            account_group_id=groups[group].id if group else None,
            parent_id=by_code[parent].id if parent else None,
            normal_balance=balance or account_type.normal_balance,
            is_postable=postable, is_control_account=is_control, control_type=control_type,
            allow_manual_posting=not is_control, is_active=True, description=description,
            created_by=user_id,
        )
        db.add(account)
        by_code[code] = account
    db.flush()
    record(db, ctx, action="create", module="finance", entity="accounts", company_id=company_id,
           new_values={"accounts": len(by_code), "source": "standard chart"},
           reason="Installed the standard chart of accounts")
    return len(by_code)


def install_posting_rules(db: Session, company_id: uuid.UUID, ctx: AuditContext | None) -> int:
    """A rule row for every (event, line). Rows without an account are
    filled from DEFAULT_RULES where that account code exists. A rule that
    already names an account is left alone."""
    accounts = {a.code: a for a in db.scalars(select(Account).where(Account.company_id == company_id))}
    rules = {(r.event_code, r.line_key): r for r in db.scalars(
        select(PostingRule).where(PostingRule.company_id == company_id))}
    touched = 0
    for event_code, line in rule_keys():
        rule = rules.get((event_code, line.key))
        if rule is None:
            rule = PostingRule(company_id=company_id, event_code=event_code, line_key=line.key,
                               description=line.label, created_by=ctx.user_id if ctx else None)
            db.add(rule)
            touched += 1
        if rule.account_id is None:
            default = accounts.get(DEFAULT_RULES.get((event_code, line.key), ""))
            if default is not None:
                rule.account_id = default.id
                touched += 1
    return touched


# ------------------------------------------------------------ maintenance

def _has_postings(db: Session, account_id: uuid.UUID) -> bool:
    return bool(db.scalar(select(exists().where(
        JournalEntryLine.account_id == account_id,
        JournalEntryLine.journal_entry_id == JournalEntry.id,
        JournalEntry.status.in_([POSTED, REVERSED])))))


def _posted_balance(db: Session, account_id: uuid.UUID):
    return db.scalar(
        select(func.coalesce(func.sum(JournalEntryLine.base_debit - JournalEntryLine.base_credit), 0))
        .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
        .where(JournalEntryLine.account_id == account_id,
               JournalEntry.status.in_([POSTED, REVERSED])))


def get_account(db: Session, company_id: uuid.UUID, account_id: uuid.UUID) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.company_id != company_id:
        raise FinanceError("That account does not exist.", 404)
    return account


def _apply(db: Session, company_id: uuid.UUID, account: Account, data: dict) -> None:
    """Validate and copy the editable fields onto an account."""
    account_type = db.get(AccountType, data["account_type_id"])
    if account_type is None:
        raise FinanceError("Choose an account type.")

    parent = None
    if data.get("parent_id"):
        parent = get_account(db, company_id, data["parent_id"])
        if parent.id == account.id:
            raise FinanceError("An account cannot be its own parent.")
        if parent.is_postable:
            raise FinanceError(f"{parent.code} {parent.name} is a posting account; "
                               "only header accounts can have children.")
        if parent.account_type_id != account_type.id:
            raise FinanceError("An account must have the same type as its parent.")
        # Walk up to make sure the new parent is not one of this account's children.
        cursor = parent
        while cursor is not None and cursor.parent_id is not None:
            if cursor.parent_id == account.id:
                raise FinanceError("That parent is below this account in the tree.")
            cursor = db.get(Account, cursor.parent_id)

    if data.get("account_group_id"):
        group = db.get(AccountGroup, data["account_group_id"])
        if group is None or group.company_id != company_id:
            raise FinanceError("That account group does not exist.")
        if group.account_type_id != account_type.id:
            raise FinanceError("The account group belongs to a different account type.")

    control_type = data.get("control_type") or None
    is_control = bool(data.get("is_control_account"))
    if is_control and not control_type:
        raise FinanceError("A control account needs a control type (receivable, payable, …).")

    code = data["code"].strip()
    if not code:
        raise FinanceError("An account code is required.")
    clash = db.scalar(select(Account).where(Account.company_id == company_id,
                                            Account.code == code, Account.id != account.id))
    if clash:
        raise FinanceError(f"Code {code} is already used by {clash.name}.")

    account.code = code
    account.name = data["name"].strip()
    account.account_type_id = account_type.id
    account.account_group_id = data.get("account_group_id")
    account.parent_id = parent.id if parent else None
    account.normal_balance = data.get("normal_balance") or account_type.normal_balance
    account.is_postable = bool(data.get("is_postable", True))
    account.is_control_account = is_control
    account.control_type = control_type
    account.allow_manual_posting = bool(data.get("allow_manual_posting", not is_control))
    account.currency = data.get("currency") or None
    account.description = data.get("description") or None


def create_account(db: Session, company_id: uuid.UUID, data: dict, ctx: AuditContext) -> Account:
    account = Account(id=uuid.uuid4(), company_id=company_id, created_by=ctx.user_id, is_active=True)
    _apply(db, company_id, account, data)
    account.is_active = bool(data.get("is_active", True))
    db.add(account)
    db.flush()
    record(db, ctx, action="create", module="finance", entity="accounts", entity_id=account.id,
           company_id=company_id, new_values=snapshot(account))
    return account


def update_account(db: Session, company_id: uuid.UUID, account_id: uuid.UUID, data: dict,
                   ctx: AuditContext) -> Account:
    account = get_account(db, company_id, account_id)
    before = snapshot(account)
    posted = _has_postings(db, account.id)

    if posted:
        if data["account_type_id"] != account.account_type_id:
            raise FinanceError("The account has postings, so its type cannot change. "
                               "Create a new account and move the balance with a journal.")
        if not data.get("is_postable", True):
            raise FinanceError("The account has postings, so it cannot become a header account.")
    if not data.get("is_postable", True) and db.scalar(select(exists().where(
            OpeningBalanceLine.account_id == account.id))):
        raise FinanceError("Opening balances use this account, so it cannot become a header.")
    if data.get("is_postable", True) and db.scalar(select(exists().where(
            Account.parent_id == account.id))):
        raise FinanceError("The account has child accounts, so it must stay a header.")

    new_active = bool(data.get("is_active", True))
    if account.is_active and not new_active and posted and _posted_balance(db, account.id) != 0:
        raise FinanceError("The account still has a balance. Move it to another account "
                           "before deactivating this one.")

    _apply(db, company_id, account, data)
    account.is_active = new_active
    account.updated_by = ctx.user_id
    old, new = changed(before, snapshot(account))
    if new:
        record(db, ctx, action="update", module="finance", entity="accounts", entity_id=account.id,
               company_id=company_id, old_values=old, new_values=new)
    return account


def delete_account(db: Session, company_id: uuid.UUID, account_id: uuid.UUID, ctx: AuditContext) -> None:
    account = get_account(db, company_id, account_id)
    if db.scalar(select(exists().where(JournalEntryLine.account_id == account.id))):
        raise FinanceError("The account is used by journals. Deactivate it instead.")
    if db.scalar(select(exists().where(Account.parent_id == account.id))):
        raise FinanceError("The account has child accounts.")
    if db.scalar(select(exists().where(OpeningBalanceLine.account_id == account.id))):
        raise FinanceError("Opening balances use this account. Deactivate it instead.")
    if db.scalar(select(exists().where(PostingRule.account_id == account.id))):
        raise FinanceError("A posting rule uses this account. Change the rule first.")
    record(db, ctx, action="delete", module="finance", entity="accounts", entity_id=account.id,
           company_id=company_id, old_values=snapshot(account))
    db.delete(account)


def event_labels() -> dict[str, str]:
    return {code: spec.label for code, spec in EVENTS.items()}
