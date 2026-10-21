"""
The accounting posting engine: the only code that writes journal entries.

    Business transaction -> PostingRequest(event, amounts)
        -> posting rules resolve an account per line
        -> validation -> DRAFT journal + lines -> POSTED
        -> general ledger

Sales, purchasing, inventory, banking and the rest never touch accounts or
journal tables themselves. They build a `PostingRequest` and call `post()`
inside their own transaction, so a document and its accounting entry commit
or roll back together.

The service checks come first because they give the clearest message. The
database triggers check the same things again at the moment of posting, so
nothing that reaches POSTED can be unbalanced, dated in a closed period or
aimed at a header account, whichever code wrote it.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.audit.service import AuditContext, record
from app.companies.models import Branch, FinancialYear
from app.finance import numbering, periods
from app.finance.errors import FinanceError, db_guard
from app.finance.events import CREDIT, DEBIT, EVENTS, EventSpec
from app.finance.models import (
    DRAFT, OPENING, POSTED, REVERSAL, REVERSED, SYSTEM, Account, CostCenter, JournalEntry,
    JournalEntryLine, PostingRule,
)
from app.inventory.models import InventoryItem
from app.partners.models import BusinessPartner

CENT = Decimal("0.01")
ZERO = Decimal("0")

#: Control accounts a manual journal may still post to, because posting the
#: journal writes the matching subledger item (journals.post → AR item).
MANUAL_CONTROLS = {"RECEIVABLE"}


def money(value) -> Decimal:
    """Exact two-decimal amount. Never a float."""
    if value is None or value == "":
        return ZERO
    if isinstance(value, float):
        value = repr(value)
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class PostingLine:
    account_id: uuid.UUID
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    description: str | None = None
    customer_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    inventory_item_id: uuid.UUID | None = None
    quantity: Decimal | None = None
    cost_center_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    currency: str | None = None
    exchange_rate: Decimal = Decimal("1")
    #: Set by the engine for rule-built lines, so a preview can say which rule.
    line_key: str | None = None
    #: Cents added to the base amount to absorb foreign-currency rounding, so
    #: a journal whose lines each round separately still balances exactly.
    base_adjust: Decimal = ZERO

    @property
    def base_debit(self) -> Decimal:
        return money(self.debit * self.exchange_rate) + (self.base_adjust if self.debit else ZERO)

    @property
    def base_credit(self) -> Decimal:
        return money(self.credit * self.exchange_rate) + (self.base_adjust if self.credit else ZERO)


@dataclass
class PostingRequest:
    event_code: str
    company_id: uuid.UUID
    journal_date: date
    description: str | None = None
    branch_id: uuid.UUID | None = None
    document_type: str | None = None
    document_id: uuid.UUID | None = None
    source_module: str | None = None
    source_reference: str | None = None
    reference: str | None = None
    #: One amount per line key of the event. Negative posts on the other side.
    amounts: dict[str, Decimal] = field(default_factory=dict)
    customer_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    #: Replace the rule's account for a line, e.g. the bank a receipt went to.
    account_overrides: dict[str, uuid.UUID] = field(default_factory=dict)
    line_descriptions: dict[str, str] = field(default_factory=dict)
    cost_center_id: uuid.UUID | None = None
    #: Ready-made lines, for explicit-line events (manual, opening, bank).
    lines: list[PostingLine] = field(default_factory=list)
    journal_type: str = SYSTEM
    currency: str = "PKR"
    #: Rate from the document currency to the company currency.
    exchange_rate: Decimal = Decimal("1")
    #: Split one key's amount over several lines, e.g. revenue per product or
    #: output tax per tax code. Each split is a dict with "amount" and any of
    #: account_id (overrides the rule), customer_id, inventory_item_id,
    #: quantity, description, cost_center_id, branch_id. The splits of a key
    #: must add up to its amount.
    splits: dict[str, list[dict]] = field(default_factory=dict)
    #: Which numbering series the journal takes its number from.
    number_series: str = "JV"


# ------------------------------------------------------------ building lines

def _event(code: str) -> EventSpec:
    spec = EVENTS.get(code)
    if spec is None:
        raise FinanceError(f"Unknown accounting event {code}.")
    return spec


def build_lines(db: Session, req: PostingRequest) -> list[PostingLine]:
    """Turn a request into journal lines using the company's posting rules."""
    spec = _event(req.event_code)
    if spec.explicit_lines:
        if req.amounts:
            raise FinanceError(f"{spec.label} takes explicit lines, not amounts.")
        return list(req.lines)

    unknown = set(req.amounts) - {line.key for line in spec.lines}
    if unknown:
        raise FinanceError(f"{spec.label} has no line called {', '.join(sorted(unknown))}.")

    rules = {r.line_key: r for r in db.scalars(select(PostingRule).where(
        PostingRule.company_id == req.company_id, PostingRule.event_code == spec.code))}

    lines: list[PostingLine] = []
    for line in spec.lines:
        amount = money(req.amounts.get(line.key))
        if amount == ZERO:
            if line.required and line.key not in req.amounts:
                raise FinanceError(f"{spec.label}: no amount given for '{line.label}'.")
            continue
        account_id = req.account_overrides.get(line.key)
        if account_id is None:
            rule = rules.get(line.key)
            if rule is None or not rule.is_active or rule.account_id is None:
                raise FinanceError(
                    f"No account is set for '{line.label}' on {spec.label}. "
                    "Choose one under Finance Settings → Posting Rules.")
            account_id = rule.account_id

        parts = req.splits.get(line.key) or [{"amount": amount}]
        split_total = sum((money(p["amount"]) for p in parts), ZERO)
        if split_total != amount:
            raise FinanceError(f"{spec.label}: the parts of '{line.label}' add up to {split_total:,.2f}, "
                               f"not {amount:,.2f}.")
        for part in parts:
            value = money(part["amount"])
            if value == ZERO:
                continue
            side = line.side if value > 0 else (CREDIT if line.side == DEBIT else DEBIT)
            value = abs(value)
            lines.append(PostingLine(
                account_id=part.get("account_id") or account_id,
                debit=value if side == DEBIT else ZERO,
                credit=value if side == CREDIT else ZERO,
                description=part.get("description") or req.line_descriptions.get(line.key) or line.label,
                customer_id=part.get("customer_id") or (req.customer_id if line.party == "customer" else None),
                supplier_id=part.get("supplier_id") or (req.supplier_id if line.party == "supplier" else None),
                inventory_item_id=part.get("inventory_item_id"),
                quantity=part.get("quantity"),
                cost_center_id=part.get("cost_center_id") or req.cost_center_id,
                branch_id=part.get("branch_id") or req.branch_id,
                currency=req.currency,
                exchange_rate=Decimal(req.exchange_rate or 1),
                line_key=line.key,
            ))
    absorb_rounding(lines)
    return lines


def absorb_rounding(lines: list[PostingLine]) -> None:
    """Each line's base amount is rounded on its own, so a foreign-currency
    entry that balances in its own currency can be a cent or two out in the
    company currency. Put that difference on the largest line of the lighter
    side. Anything bigger than a rounding difference is left for validation
    to refuse."""
    if not lines:
        return
    diff = sum((l.base_debit for l in lines), ZERO) - sum((l.base_credit for l in lines), ZERO)
    if diff == 0 or abs(diff) > CENT * len(lines):
        return
    if sum((l.debit for l in lines), ZERO) != sum((l.credit for l in lines), ZERO):
        return  # unbalanced in its own currency: a real error, not rounding
    side = [l for l in lines if (l.credit if diff > 0 else l.debit) > 0]
    target = max(side, key=lambda l: l.credit if diff > 0 else l.debit)
    target.base_adjust += abs(diff)


# ------------------------------------------------------------ validation

def validate_lines(db: Session, company_id: uuid.UUID, lines: list[PostingLine], *,
                   manual: bool) -> None:
    """Everything the database would refuse, said first and said clearly,
    plus the subledger rules the database does not know about."""
    if len(lines) < 2:
        raise FinanceError("A journal needs at least two lines.")

    account_ids = {line.account_id for line in lines}
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.id.in_(account_ids)))}
    partner_ids = {pid for line in lines for pid in (line.customer_id, line.supplier_id) if pid}
    partners = {p.id: p for p in db.scalars(
        select(BusinessPartner).where(BusinessPartner.id.in_(partner_ids)))} if partner_ids else {}
    item_ids = {line.inventory_item_id for line in lines if line.inventory_item_id}
    items = {i.id: i for i in db.scalars(
        select(InventoryItem).where(InventoryItem.id.in_(item_ids)))} if item_ids else {}
    center_ids = {line.cost_center_id for line in lines if line.cost_center_id}
    centers = {c.id: c for c in db.scalars(
        select(CostCenter).where(CostCenter.id.in_(center_ids)))} if center_ids else {}
    branch_ids = {line.branch_id for line in lines if line.branch_id}
    branches = {b.id: b for b in db.scalars(
        select(Branch).where(Branch.id.in_(branch_ids)))} if branch_ids else {}

    total_dr = total_cr = ZERO
    for n, line in enumerate(lines, start=1):
        where = f"Line {n}"
        debit, credit = money(line.debit), money(line.credit)
        if debit < 0 or credit < 0:
            raise FinanceError(f"{where}: amounts cannot be negative.")
        if debit > 0 and credit > 0:
            raise FinanceError(f"{where}: enter a debit or a credit, not both.")
        if debit == 0 and credit == 0:
            raise FinanceError(f"{where}: enter a debit or a credit amount.")
        if line.exchange_rate is None or Decimal(line.exchange_rate) <= 0:
            raise FinanceError(f"{where}: the exchange rate must be greater than zero.")

        account = accounts.get(line.account_id)
        if account is None or account.company_id != company_id:
            raise FinanceError(f"{where}: the account does not exist in this company.")
        label = f"{account.code} {account.name}"
        if not account.is_active:
            raise FinanceError(f"{where}: {label} is inactive.")
        if not account.is_postable:
            raise FinanceError(f"{where}: {label} is a header account and cannot be posted to.")
        if manual and not account.allow_manual_posting and account.control_type not in MANUAL_CONTROLS:
            raise FinanceError(f"{where}: {label} is a control account and only accepts postings "
                               "from its own module.")

        if line.customer_id and line.supplier_id:
            raise FinanceError(f"{where}: name a customer or a supplier, not both.")
        if line.customer_id:
            p = partners.get(line.customer_id)
            if p is None or p.company_id != company_id or not p.is_customer:
                raise FinanceError(f"{where}: that customer does not exist.")
        if line.supplier_id:
            p = partners.get(line.supplier_id)
            if p is None or p.company_id != company_id or not p.is_supplier:
                raise FinanceError(f"{where}: that supplier does not exist.")
        if account.control_type == "RECEIVABLE" and not line.customer_id:
            raise FinanceError(f"{where}: {label} is a receivable account; name the customer.")
        if account.control_type == "PAYABLE" and not line.supplier_id:
            raise FinanceError(f"{where}: {label} is a payable account; name the supplier.")
        if account.control_type == "CUSTOMER_ADVANCE" and not line.customer_id:
            raise FinanceError(f"{where}: {label} holds customer advances; name the customer.")
        if line.inventory_item_id:
            item = items.get(line.inventory_item_id)
            if item is None or item.company_id != company_id:
                raise FinanceError(f"{where}: that inventory item does not exist.")
        if line.cost_center_id:
            c = centers.get(line.cost_center_id)
            if c is None or c.company_id != company_id or not c.is_active:
                raise FinanceError(f"{where}: that cost centre does not exist or is inactive.")
        if line.branch_id:
            b = branches.get(line.branch_id)
            if b is None or b.company_id != company_id:
                raise FinanceError(f"{where}: that branch does not belong to the company.")

        total_dr += line.base_debit
        total_cr += line.base_credit

    if total_dr != total_cr:
        raise FinanceError(f"The journal is not balanced: debits {total_dr:,.2f}, "
                           f"credits {total_cr:,.2f}, difference {abs(total_dr - total_cr):,.2f}.")


# ------------------------------------------------------------ journals

def _year_and_period(db: Session, company_id: uuid.UUID, on: date):
    fy = periods.year_for_date(db, company_id, on)
    period = periods.period_for_date(db, company_id, on)
    return fy, period


def write_lines(journal: JournalEntry, lines: list[PostingLine]) -> None:
    """Replace a DRAFT journal's lines and totals."""
    if journal.lines:
        # Delete the old lines and flush before adding the new ones. The unit
        # of work inserts before it deletes, so replacing line 1 with a new
        # line 1 in one flush breaks the (journal, line_number) unique key.
        journal.lines.clear()
        session = object_session(journal)
        if session is not None:
            with db_guard(session):
                session.flush()
    for n, line in enumerate(lines, start=1):
        journal.lines.append(JournalEntryLine(
            company_id=journal.company_id, line_number=n, account_id=line.account_id,
            description=line.description,
            debit=money(line.debit), credit=money(line.credit),
            currency=line.currency or journal.currency,
            exchange_rate=Decimal(line.exchange_rate or 1),
            base_debit=line.base_debit, base_credit=line.base_credit,
            customer_id=line.customer_id, supplier_id=line.supplier_id,
            inventory_item_id=line.inventory_item_id, quantity=line.quantity,
            cost_center_id=line.cost_center_id,
            # A line with no branch of its own belongs to the journal's branch,
            # so branch reports can filter on lines alone.
            branch_id=line.branch_id or journal.branch_id,
        ))
    journal.total_debit = sum((line.base_debit for line in lines), ZERO)
    journal.total_credit = sum((line.base_credit for line in lines), ZERO)


def new_journal(db: Session, *, company_id: uuid.UUID, journal_date: date, journal_type: str,
                branch_id: uuid.UUID | None, description: str | None, reference: str | None,
                user_id: uuid.UUID | None, number_series: str = "JV", **extra) -> JournalEntry:
    """A numbered DRAFT journal in the period covering its date."""
    fy, period = _year_and_period(db, company_id, journal_date)
    journal = JournalEntry(
        id=uuid.uuid4(), company_id=company_id, branch_id=branch_id,
        financial_year_id=fy.id, accounting_period_id=period.id,
        journal_number=numbering.allocate(db, company_id, number_series, fy, branch_id),
        journal_date=journal_date, journal_type=journal_type, status=DRAFT,
        description=description, reference=reference, created_by=user_id, **extra,
    )
    db.add(journal)
    return journal


def mark_posted(db: Session, journal: JournalEntry, ctx: AuditContext | None,
                reason: str | None = None) -> JournalEntry:
    """Move a journal to POSTED. The database trigger re-checks balance,
    period and accounts at this moment."""
    period = periods.period_for_date(db, journal.company_id, journal.journal_date)
    periods.require_open(period)
    previous = journal.status
    journal.status = POSTED
    journal.posted_by = ctx.user_id if ctx else None
    journal.posted_at = datetime.now(timezone.utc)
    with db_guard(db):
        db.flush()
    record(db, ctx, action="post", module="finance", entity="journal_entries",
           entity_id=journal.id, company_id=journal.company_id,
           old_values={"status": previous},
           new_values={"status": POSTED, "journal_number": journal.journal_number,
                       "total_debit": journal.total_debit, "total_credit": journal.total_credit,
                       "event_code": journal.event_code},
           reason=reason)
    return journal


def post(db: Session, req: PostingRequest, ctx: AuditContext | None) -> JournalEntry:
    """Build, validate and post one accounting event. The caller commits."""
    spec = _event(req.event_code)
    lines = build_lines(db, req)
    validate_lines(db, req.company_id, lines, manual=False)

    if req.document_id is not None:
        duplicate = db.scalar(select(JournalEntry).where(
            JournalEntry.company_id == req.company_id,
            JournalEntry.document_type == req.document_type,
            JournalEntry.document_id == req.document_id,
            JournalEntry.event_code == spec.code,
            JournalEntry.status == POSTED,
            JournalEntry.journal_type != REVERSAL))
        if duplicate:
            raise FinanceError(f"{req.source_reference or 'This document'} is already posted "
                               f"as {duplicate.journal_number}.")

    journal = new_journal(
        db, company_id=req.company_id, journal_date=req.journal_date,
        journal_type=req.journal_type, branch_id=req.branch_id,
        description=req.description, reference=req.reference,
        user_id=ctx.user_id if ctx else None, number_series=req.number_series,
        event_code=spec.code, document_type=req.document_type, document_id=req.document_id,
        source_module=req.source_module or spec.source_module,
        source_reference=req.source_reference, currency=req.currency,
    )
    write_lines(journal, lines)
    with db_guard(db):
        db.flush()
    record(db, ctx, action="create", module="finance", entity="journal_entries",
           entity_id=journal.id, company_id=journal.company_id,
           new_values={"journal_number": journal.journal_number, "event_code": spec.code,
                       "document_type": req.document_type, "document_id": req.document_id,
                       "lines": len(lines)})
    return mark_posted(db, journal, ctx)


def preview(db: Session, req: PostingRequest) -> dict:
    """The entry a request would produce, without writing anything."""
    lines = build_lines(db, req)
    accounts = {a.id: a for a in db.scalars(
        select(Account).where(Account.id.in_({line.account_id for line in lines})))}
    total_dr = sum((line.base_debit for line in lines), ZERO)
    total_cr = sum((line.base_credit for line in lines), ZERO)
    problem = None
    try:
        validate_lines(db, req.company_id, lines, manual=False)
    except FinanceError as error:
        problem = error.message
    return {
        "event_code": req.event_code,
        "lines": [{
            "line_key": line.line_key,
            "account_id": str(line.account_id),
            "account_code": accounts[line.account_id].code if line.account_id in accounts else None,
            "account_name": accounts[line.account_id].name if line.account_id in accounts else None,
            "description": line.description,
            "debit": line.base_debit, "credit": line.base_credit,
        } for line in lines],
        "total_debit": total_dr, "total_credit": total_cr,
        "balanced": total_dr == total_cr, "problem": problem,
    }


#: Journals owned by a document with its own subledger. Reversing one from
#: the journal screen would leave the document and the subledger claiming a
#: balance the ledger no longer has, so they are reversed through the document.
DOCUMENT_OWNED = {"SALES_INVOICE", "SALES_CREDIT_NOTE", "SALES_DEBIT_NOTE",
                  "CUSTOMER_RECEIPT", "AR_ALLOCATION", "SERVICE_INVOICE"}


def reverse(db: Session, journal: JournalEntry, reversal_date: date, reason: str,
            ctx: AuditContext, *, allow_document: bool = False) -> JournalEntry:
    """Cancel a posted journal with its mirror image. The original stays in
    the ledger, marked REVERSED and linked both ways to the reversal."""
    if journal.document_type in DOCUMENT_OWNED and not allow_document:
        raise FinanceError(f"{journal.journal_number} belongs to {journal.source_reference or 'a document'}; "
                           "cancel or reverse that document instead, so the receivables stay in step.")
    if journal.status != POSTED:
        raise FinanceError(f"Only a posted journal can be reversed; {journal.journal_number} "
                           f"is {journal.status}.")
    if journal.journal_type == REVERSAL:
        raise FinanceError("A reversal cannot itself be reversed. Post a new journal instead.")
    if journal.journal_type == OPENING:
        raise FinanceError("Opening balances are corrected with an adjustment journal dated at "
                           "the cut-over, not by reversing the opening journal.")
    if not reason or len(reason.strip()) < 5:
        raise FinanceError("Give a reason for the reversal; it is kept with both journals.")
    if reversal_date < journal.journal_date:
        raise FinanceError("A reversal cannot be dated before the journal it reverses.")

    mirrored = [PostingLine(
        account_id=line.account_id, debit=line.credit, credit=line.debit,
        description=f"Reversal: {line.description or ''}".strip(),
        customer_id=line.customer_id, supplier_id=line.supplier_id,
        inventory_item_id=line.inventory_item_id, quantity=line.quantity,
        cost_center_id=line.cost_center_id, branch_id=line.branch_id,
        currency=line.currency, exchange_rate=line.exchange_rate,
        # Keep the original base amounts exactly, rounding adjustment included.
        base_adjust=(line.base_debit + line.base_credit)
        - money((line.debit + line.credit) * line.exchange_rate),
    ) for line in journal.lines]

    reversal = new_journal(
        db, company_id=journal.company_id, journal_date=reversal_date, journal_type=REVERSAL,
        branch_id=journal.branch_id,
        description=f"Reversal of {journal.journal_number}: {reason.strip()}",
        reference=journal.journal_number, user_id=ctx.user_id,
        event_code=journal.event_code, document_type=journal.document_type,
        document_id=journal.document_id, source_module=journal.source_module,
        source_reference=journal.source_reference, currency=journal.currency,
        reversed_entry_id=journal.id,
    )
    write_lines(reversal, mirrored)
    with db_guard(db):
        db.flush()
    mark_posted(db, reversal, ctx, reason=reason.strip())

    journal.status = REVERSED
    journal.reversed_by_entry_id = reversal.id
    journal.updated_by = ctx.user_id
    with db_guard(db):
        db.flush()
    record(db, ctx, action="reverse", module="finance", entity="journal_entries",
           entity_id=journal.id, company_id=journal.company_id,
           old_values={"status": POSTED},
           new_values={"status": REVERSED, "reversed_by": reversal.journal_number},
           reason=reason.strip())
    return reversal


def fiscal_year_of(db: Session, journal: JournalEntry) -> FinancialYear:
    return db.get(FinancialYear, journal.financial_year_id)
