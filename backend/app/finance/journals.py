"""
Manual journals: DRAFT → SUBMITTED → APPROVED → POSTED.

A rejected journal goes back to DRAFT with the reason recorded. A journal
that is no longer wanted is CANCELLED, never deleted, so its number stays
accounted for. A posted journal is corrected by reversal (posting.reverse)
or by a further adjustment journal.

Lines are only editable in DRAFT, which the database also enforces.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit.service import record
from app.finance import periods, posting
from app.finance.context import FinanceContext
from app.finance.errors import FinanceError, db_guard
from app.finance.models import (
    ADJUSTMENT, APPROVED, CANCELLED, DRAFT, MANUAL, POSTED, SUBMITTED, Account, JournalEntry,
)
from app.finance.posting import (
    MANUAL_CONTROLS, ZERO, PostingLine, mark_posted, money, new_journal, validate_lines, write_lines,
)

MANUAL_TYPES = (MANUAL, ADJUSTMENT)


def get_journal(db: Session, ctx: FinanceContext, journal_id: uuid.UUID) -> JournalEntry:
    journal = db.scalar(select(JournalEntry).options(selectinload(JournalEntry.lines))
                        .where(JournalEntry.id == journal_id))
    if journal is None or journal.company_id != ctx.company_id:
        raise FinanceError("That journal does not exist.", 404)
    if ctx.branch_ids is not None and journal.branch_id not in ctx.branch_ids:
        raise FinanceError("That journal does not exist.", 404)
    return journal


def _lines(payload_lines: list[dict]) -> list[PostingLine]:
    return [PostingLine(
        account_id=line["account_id"],
        debit=money(line.get("debit")), credit=money(line.get("credit")),
        description=line.get("description"),
        customer_id=line.get("customer_id"), supplier_id=line.get("supplier_id"),
        inventory_item_id=line.get("inventory_item_id"),
        cost_center_id=line.get("cost_center_id"), branch_id=line.get("branch_id"),
    ) for line in payload_lines]


def _check_line_branches(ctx: FinanceContext, lines: list[PostingLine]) -> None:
    for line in lines:
        if line.branch_id:
            ctx.check_branch(line.branch_id)


def create(db: Session, ctx: FinanceContext, data: dict) -> JournalEntry:
    journal_type = data.get("journal_type") or MANUAL
    if journal_type not in MANUAL_TYPES:
        raise FinanceError("Only manual and adjustment journals are entered by hand.")
    branch_id = ctx.default_branch(data.get("branch_id"))
    lines = _lines(data["lines"])
    _check_line_branches(ctx, lines)
    validate_lines(db, ctx.company_id, lines, manual=True)

    journal = new_journal(
        db, company_id=ctx.company_id, journal_date=data["journal_date"],
        journal_type=journal_type, branch_id=branch_id,
        description=data.get("description"), reference=data.get("reference"),
        user_id=ctx.user_id, event_code="JOURNAL_ENTRY_POSTED", source_module="finance",
    )
    write_lines(journal, lines)
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="create", module="finance", entity="journal_entries",
           entity_id=journal.id, company_id=ctx.company_id,
           new_values={"journal_number": journal.journal_number, "journal_date": journal.journal_date,
                       "total_debit": journal.total_debit, "lines": len(lines)})
    return journal


def update(db: Session, ctx: FinanceContext, journal_id: uuid.UUID, data: dict) -> JournalEntry:
    journal = get_journal(db, ctx, journal_id)
    if journal.status != DRAFT:
        raise FinanceError(f"{journal.journal_number} is {journal.status}; only a draft can be edited.")
    if journal.journal_type not in MANUAL_TYPES:
        raise FinanceError("System journals are changed through their source document.")

    new_date: date = data["journal_date"]
    fy = periods.year_for_date(db, ctx.company_id, new_date)
    if fy.id != journal.financial_year_id:
        raise FinanceError("The new date is in another financial year, where this journal's "
                           "number does not belong. Cancel it and create the journal in that year.")
    period = periods.period_for_date(db, ctx.company_id, new_date)
    branch_id = ctx.default_branch(data.get("branch_id"))

    lines = _lines(data["lines"])
    _check_line_branches(ctx, lines)
    validate_lines(db, ctx.company_id, lines, manual=True)

    before = {"journal_date": journal.journal_date, "total_debit": journal.total_debit,
              "description": journal.description, "lines": len(journal.lines)}
    journal.journal_date = new_date
    journal.accounting_period_id = period.id
    journal.branch_id = branch_id
    journal.journal_type = data.get("journal_type") or journal.journal_type
    journal.description = data.get("description")
    journal.reference = data.get("reference")
    journal.updated_by = ctx.user_id
    write_lines(journal, lines)
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="update", module="finance", entity="journal_entries",
           entity_id=journal.id, company_id=ctx.company_id, old_values=before,
           new_values={"journal_date": journal.journal_date, "total_debit": journal.total_debit,
                       "description": journal.description, "lines": len(lines)})
    return journal


def _transition(db: Session, ctx: FinanceContext, journal: JournalEntry, to: str,
                action: str, reason: str | None = None) -> JournalEntry:
    previous = journal.status
    journal.status = to
    journal.updated_by = ctx.user_id
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action=action, module="finance", entity="journal_entries",
           entity_id=journal.id, company_id=ctx.company_id,
           old_values={"status": previous}, new_values={"status": to}, reason=reason)
    return journal


def submit(db: Session, ctx: FinanceContext, journal_id: uuid.UUID) -> JournalEntry:
    journal = get_journal(db, ctx, journal_id)
    if journal.status != DRAFT:
        raise FinanceError(f"{journal.journal_number} is {journal.status}; only a draft can be submitted.")
    validate_lines(db, ctx.company_id, _as_posting_lines(journal), manual=True)
    journal.submitted_by = ctx.user_id
    journal.submitted_at = datetime.now(timezone.utc)
    return _transition(db, ctx, journal, SUBMITTED, "submit")


def approve(db: Session, ctx: FinanceContext, journal_id: uuid.UUID) -> JournalEntry:
    journal = get_journal(db, ctx, journal_id)
    if journal.status != SUBMITTED:
        raise FinanceError(f"{journal.journal_number} is {journal.status}; only a submitted journal "
                           "can be approved.")
    journal.approved_by = ctx.user_id
    journal.approved_at = datetime.now(timezone.utc)
    return _transition(db, ctx, journal, APPROVED, "approve")


def reject(db: Session, ctx: FinanceContext, journal_id: uuid.UUID, reason: str) -> JournalEntry:
    journal = get_journal(db, ctx, journal_id)
    if journal.status not in (SUBMITTED, APPROVED):
        raise FinanceError(f"{journal.journal_number} is {journal.status}; there is nothing to reject.")
    if not reason or len(reason.strip()) < 3:
        raise FinanceError("Say why the journal is rejected, so the preparer can fix it.")
    journal.approved_by = None
    journal.approved_at = None
    return _transition(db, ctx, journal, DRAFT, "reject", reason.strip())


def post(db: Session, ctx: FinanceContext, journal_id: uuid.UUID) -> JournalEntry:
    journal = get_journal(db, ctx, journal_id)
    if journal.status != APPROVED:
        raise FinanceError(f"{journal.journal_number} is {journal.status}; a manual journal must be "
                           "approved before it is posted.")
    validate_lines(db, ctx.company_id, _as_posting_lines(journal), manual=True)
    mark_posted(db, journal, ctx.audit)
    _record_ar_items(db, ctx, journal)
    return journal


def _receivable_lines(db: Session, journal: JournalEntry):
    accounts = {a.id: a for a in db.scalars(select(Account).where(
        Account.id.in_({l.account_id for l in journal.lines})))}
    return [l for l in journal.lines
            if accounts[l.account_id].control_type in MANUAL_CONTROLS and l.customer_id]


def _record_ar_items(db: Session, ctx: FinanceContext, journal: JournalEntry) -> None:
    """Each line on the customer receivable becomes an AR item: a debit is
    owed by the customer (paid by a receipt), a credit is owed to them
    (allocated against an invoice), exactly as the ledger now shows."""
    from app.receivables import subledger
    from app.receivables.models import JOURNAL, KIND_AR

    for line in _receivable_lines(db, journal):
        subledger.record_item(
            db, company_id=journal.company_id, branch_id=line.branch_id or journal.branch_id,
            customer_id=line.customer_id, item_type=JOURNAL, kind=KIND_AR,
            number=journal.journal_number, document_date=journal.journal_date,
            amount=line.debit - line.credit,
            amount_base=(line.base_debit or ZERO) - (line.base_credit or ZERO),
            currency=line.currency or "PKR", exchange_rate=line.exchange_rate or 1,
            journal_entry_id=journal.id, journal_line_id=line.id, user_id=ctx.user_id)
    with db_guard(db):
        db.flush()


def reverse(db: Session, ctx: FinanceContext, journal_id: uuid.UUID, reversal_date: date,
            reason: str) -> JournalEntry:
    """Reverse a posted journal. Its customer items are cancelled with it,
    which needs them unmatched first, so no receipt or invoice is left
    pointing at money that is no longer there."""
    from app.receivables import subledger
    from app.receivables.models import ARItem

    journal = get_journal(db, ctx, journal_id)
    items = list(db.scalars(select(ARItem).where(ARItem.journal_entry_id == journal.id,
                                                 ARItem.journal_line_id.is_not(None),
                                                 ARItem.status == "OPEN")))
    for item in items:
        if subledger.active_allocations(db, item.id, "to") or subledger.active_allocations(db, item.id, "from"):
            raise FinanceError(f"{journal.journal_number} has been matched against a customer's "
                               "receipt or invoice. Undo that allocation first, then reverse the journal.")
    reversal = posting.reverse(db, journal, reversal_date, reason, ctx.audit)
    for item in items:
        subledger.cancel_item(db, item)
    return reversal


def cancel(db: Session, ctx: FinanceContext, journal_id: uuid.UUID, reason: str) -> JournalEntry:
    journal = get_journal(db, ctx, journal_id)
    if journal.status not in (DRAFT, SUBMITTED, APPROVED):
        raise FinanceError(f"{journal.journal_number} is {journal.status}. "
                           + ("Reverse it instead." if journal.status == POSTED else ""))
    if not reason or len(reason.strip()) < 3:
        raise FinanceError("Give a reason for cancelling the journal.")
    journal.cancelled_by = ctx.user_id
    journal.cancelled_at = datetime.now(timezone.utc)
    journal.cancel_reason = reason.strip()
    return _transition(db, ctx, journal, CANCELLED, "cancel", reason.strip())


def _as_posting_lines(journal: JournalEntry) -> list[PostingLine]:
    return [PostingLine(
        account_id=line.account_id, debit=line.debit, credit=line.credit,
        description=line.description, customer_id=line.customer_id,
        supplier_id=line.supplier_id, inventory_item_id=line.inventory_item_id,
        quantity=line.quantity, cost_center_id=line.cost_center_id, branch_id=line.branch_id,
        currency=line.currency, exchange_rate=line.exchange_rate,
    ) for line in journal.lines]
