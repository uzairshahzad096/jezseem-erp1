"""
Financial years and accounting periods.

Financial years are the existing `financial_years` table; this module adds
monthly accounting periods beneath them and nothing else. That table keeps
its dates as ISO strings, which are parsed here rather than migrated. It is
shared with every other module and changing its column types is not a
Phase 1 matter.

Nothing assumes July–June. A year runs from whatever start date it is
given, and periods are cut at calendar-month boundaries inside it.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.service import AuditContext, record, snapshot
from app.companies.models import FinancialYear
from app.finance.errors import FinanceError
from app.finance.models import (
    APPROVED, CLOSED, DRAFT, LOCKED, OPEN, SUBMITTED, AccountingPeriod, JournalEntry,
)

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fy_dates(fy: FinancialYear) -> tuple[date, date]:
    try:
        return date.fromisoformat(fy.start_date), date.fromisoformat(fy.end_date)
    except (TypeError, ValueError) as error:
        raise FinanceError(f"Financial year {fy.name} has unreadable dates.") from error


def _month_end(d: date) -> date:
    first_next = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return first_next - timedelta(days=1)


def generate_periods(db: Session, fy: FinancialYear, ctx: AuditContext | None) -> list[AccountingPeriod]:
    """Monthly periods for a year that has none. Idempotent: a year that
    already has periods is left as it is."""
    existing = db.scalars(select(AccountingPeriod).where(
        AccountingPeriod.financial_year_id == fy.id).order_by(AccountingPeriod.period_number)).all()
    if existing:
        return list(existing)

    start, end = fy_dates(fy)
    periods, cursor, number = [], start, 1
    while cursor <= end:
        stop = min(_month_end(cursor), end)
        periods.append(AccountingPeriod(
            company_id=fy.company_id, financial_year_id=fy.id, period_number=number,
            name=f"{MONTHS[cursor.month - 1]} {cursor.year}",
            period_start=cursor, period_end=stop, status=OPEN,
            created_by=ctx.user_id if ctx else None,
        ))
        cursor, number = stop + timedelta(days=1), number + 1
    db.add_all(periods)
    record(db, ctx, action="create", module="finance", entity="accounting_periods",
           entity_id=fy.id, company_id=fy.company_id,
           new_values={"financial_year": fy.name, "periods": len(periods)},
           reason="Generated monthly periods")
    return periods


def create_financial_year(db: Session, company_id: uuid.UUID, name: str, start: date, end: date,
                          make_current: bool, ctx: AuditContext) -> FinancialYear:
    """A new year in the existing table, with its periods."""
    if end <= start:
        raise FinanceError("The year must end after it starts.")
    if (end - start).days > 400:
        raise FinanceError("A financial year cannot be longer than about 13 months.")
    for other in db.scalars(select(FinancialYear).where(FinancialYear.company_id == company_id)):
        o_start, o_end = fy_dates(other)
        if start <= o_end and end >= o_start:
            raise FinanceError(f"The dates overlap financial year {other.name}.")
        if other.name == name:
            raise FinanceError(f"A financial year called {name} already exists.")

    fy = FinancialYear(company_id=company_id, name=name, start_date=start.isoformat(),
                       end_date=end.isoformat(), is_current=False, is_closed=False,
                       created_by=ctx.user_id)
    db.add(fy)
    db.flush()
    if make_current:
        set_current(db, fy, ctx)
    record(db, ctx, action="create", module="finance", entity="financial_years", entity_id=fy.id,
           company_id=company_id, new_values=snapshot(fy))
    generate_periods(db, fy, ctx)
    return fy


def set_current(db: Session, fy: FinancialYear, ctx: AuditContext) -> None:
    """Only one current year per company, as the existing model intends."""
    for other in db.scalars(select(FinancialYear).where(
            FinancialYear.company_id == fy.company_id, FinancialYear.is_current.is_(True))):
        other.is_current = False
    fy.is_current = True
    record(db, ctx, action="update", module="finance", entity="financial_years", entity_id=fy.id,
           company_id=fy.company_id, new_values={"is_current": True})


def current_year(db: Session, company_id: uuid.UUID) -> FinancialYear | None:
    return db.scalar(select(FinancialYear).where(
        FinancialYear.company_id == company_id, FinancialYear.is_current.is_(True)))


def year_for_date(db: Session, company_id: uuid.UUID, on: date) -> FinancialYear:
    iso = on.isoformat()
    fy = db.scalar(select(FinancialYear).where(
        FinancialYear.company_id == company_id,
        FinancialYear.start_date <= iso, FinancialYear.end_date >= iso))
    if fy is None:
        raise FinanceError(f"No financial year covers {on:%d-%b-%Y}. Create it under Accounting Periods.")
    return fy


def period_for_date(db: Session, company_id: uuid.UUID, on: date) -> AccountingPeriod:
    period = db.scalar(select(AccountingPeriod).where(
        AccountingPeriod.company_id == company_id,
        AccountingPeriod.period_start <= on, AccountingPeriod.period_end >= on))
    if period is None:
        fy = year_for_date(db, company_id, on)
        raise FinanceError(f"Financial year {fy.name} has no accounting periods yet. "
                           "Generate them under Accounting Periods.")
    return period


def require_open(period: AccountingPeriod) -> None:
    if period.status != OPEN:
        raise FinanceError(f"Period {period.name} is {period.status} and does not accept postings.")


def _get(db: Session, company_id: uuid.UUID, period_id: uuid.UUID) -> AccountingPeriod:
    period = db.get(AccountingPeriod, period_id)
    if period is None or period.company_id != company_id:
        raise FinanceError("That accounting period does not exist.", 404)
    return period


def close_period(db: Session, company_id: uuid.UUID, period_id: uuid.UUID,
                 reason: str | None, ctx: AuditContext) -> AccountingPeriod:
    period = _get(db, company_id, period_id)
    if period.status != OPEN:
        raise FinanceError(f"Period {period.name} is already {period.status}.")
    pending = db.scalar(select(func.count()).select_from(JournalEntry).where(
        JournalEntry.company_id == company_id,
        JournalEntry.accounting_period_id == period.id,
        JournalEntry.status.in_([DRAFT, SUBMITTED, APPROVED])))
    if pending:
        raise FinanceError(f"{pending} journal(s) in {period.name} are not posted or cancelled yet. "
                           "Post or cancel them before closing the period.")
    old = snapshot(period, ["status"])
    period.status = CLOSED
    period.closed_at = datetime.now(timezone.utc)
    period.closed_by = ctx.user_id
    period.updated_by = ctx.user_id
    record(db, ctx, action="close", module="finance", entity="accounting_periods",
           entity_id=period.id, company_id=company_id, old_values=old,
           new_values={"status": CLOSED}, reason=reason)
    return period


def reopen_period(db: Session, company_id: uuid.UUID, period_id: uuid.UUID,
                  reason: str | None, ctx: AuditContext) -> AccountingPeriod:
    period = _get(db, company_id, period_id)
    if period.status == LOCKED:
        raise FinanceError(f"Period {period.name} is locked and cannot be reopened.")
    if period.status != CLOSED:
        raise FinanceError(f"Period {period.name} is not closed.")
    if not reason or len(reason.strip()) < 5:
        raise FinanceError("Give a reason for reopening the period; it is kept in the audit log.")
    period.status = OPEN
    period.updated_by = ctx.user_id
    record(db, ctx, action="reopen", module="finance", entity="accounting_periods",
           entity_id=period.id, company_id=company_id, old_values={"status": CLOSED},
           new_values={"status": OPEN}, reason=reason.strip())
    return period


def lock_period(db: Session, company_id: uuid.UUID, period_id: uuid.UUID,
                reason: str | None, ctx: AuditContext) -> AccountingPeriod:
    period = _get(db, company_id, period_id)
    if period.status != CLOSED:
        raise FinanceError("Close the period before locking it.")
    period.status = LOCKED
    period.locked_at = datetime.now(timezone.utc)
    period.locked_by = ctx.user_id
    period.updated_by = ctx.user_id
    record(db, ctx, action="lock", module="finance", entity="accounting_periods",
           entity_id=period.id, company_id=company_id, old_values={"status": CLOSED},
           new_values={"status": LOCKED}, reason=reason)
    return period
