"""
Finance setup for a company: numbering series, the standard chart, posting
rules and accounting periods for its existing financial years.

Idempotent and non-destructive. A company that already has a chart keeps
it, a rule that already names an account keeps it, and a year that already
has periods keeps them. Run by the seed script and from the Chart of
Accounts screen. No balance, journal or opening figure is created.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import AuditContext
from app.companies.models import FinancialYear
from app.finance import chart, numbering, periods
from app.finance.models import AccountingPeriod


def install_defaults(db: Session, company_id: uuid.UUID, ctx: AuditContext | None) -> dict:
    series = numbering.install_default_series(db, company_id, ctx.user_id if ctx else None)
    accounts = chart.install_standard_chart(db, company_id, ctx)
    db.flush()
    from app.receivables.setup import install as install_receivables
    receivables = install_receivables(db, company_id, ctx)
    db.flush()
    rules = chart.install_posting_rules(db, company_id, ctx)
    generated = 0
    years = db.scalars(select(FinancialYear).where(FinancialYear.company_id == company_id)).all()
    for fy in years:
        had_periods = db.scalar(select(AccountingPeriod.id).where(
            AccountingPeriod.financial_year_id == fy.id).limit(1)) is not None
        created = periods.generate_periods(db, fy, ctx)
        if not had_periods:
            generated += len(created)
    db.flush()
    return {"series_added": series, "accounts_added": accounts, "rules_updated": rules,
            "periods_generated": generated, "receivables": receivables}
