"""
Finance API — /api/v1/finance/...

Every endpoint takes a FinanceContext, which carries the permission check,
the working company, the caller's branches and the audit details. Services do
the work and raise FinanceError; this file only translates between HTTP and
them, commits, and shapes the responses.

Permissions (all rows in the existing `permissions` table):
    finance.view               read screens
    finance.chart_of_accounts  chart, groups, cost centres, numbering, posting rules, setup
    finance.create / .edit     draft journals
    finance.approve            approve / reject journals, approve & complete opening batches
    finance.post               post journals and opening batches
    finance.reverse            reverse posted journals
    finance.close_period       financial years and periods: create, close, reopen, lock
    finance.opening_balance    create batches, import, validate, reconcile
    finance.reports            general ledger, trial balance, exports
    finance.audit              audit log
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.audit.models import AuditLog
from app.audit.service import changed, record, snapshot
from app.companies.models import Branch, Company, FinancialYear
from app.core.database import get_db
from app.exports.writers import FORMATS
from app.finance import chart, journals, ledger, numbering, opening, periods, posting, setup
from app.finance.context import FinanceContext, finance_context
from app.finance.errors import FinanceError, db_guard
from app.finance.events import EVENTS
from app.finance.models import (
    CONTROL_TYPES, JOURNAL_STATUSES, JOURNAL_TYPES, RECONCILIATION_CATEGORIES, SCHEDULES, Account,
    AccountGroup, AccountingPeriod, AccountType, CostCenter, DocumentSeries, JournalEntry,
    JournalEntryLine, OpeningBalanceBatch, OpeningBalanceImport, PostingRule,
)
from app.finance.schemas import (
    AccountGroupIn, AccountIn, CostCenterIn, FinancialYearIn, JournalIn, OpeningBatchIn,
    PostingPreviewIn, PostingRuleIn, ReasonIn, ReconciliationIn, ReverseIn, SeriesIn,
)
from app.inventory.models import InventoryItem
from app.partners.models import BusinessPartner
from app.users.models import User

router = APIRouter(prefix="/finance", tags=["finance"])

VIEW = "finance.view"
SETUP = "finance.chart_of_accounts"


def commit(db: Session) -> None:
    with db_guard(db):
        db.commit()


def _num(value) -> float:
    return float(value) if value is not None else 0.0


def _names(db: Session, model, ids) -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    column = {"User": "full_name", "BusinessPartner": "name", "Branch": "name"}[model.__name__]
    return {row.id: getattr(row, column) for row in db.scalars(select(model).where(model.id.in_(ids)))}


# ============================================================ context & meta

@router.get("/context")
def finance_context_info(db: Session = Depends(get_db),
                         ctx: FinanceContext = Depends(finance_context(VIEW))):
    """What the screens need to start: company, branches, years, current period."""
    company = db.get(Company, ctx.company_id)
    branches = db.scalars(select(Branch).where(Branch.company_id == ctx.company_id)
                          .order_by(Branch.code)).all()
    years = db.scalars(select(FinancialYear).where(FinancialYear.company_id == ctx.company_id)
                       .order_by(FinancialYear.start_date.desc())).all()
    today = date.today()
    period = db.scalar(select(AccountingPeriod).where(
        AccountingPeriod.company_id == ctx.company_id,
        AccountingPeriod.period_start <= today, AccountingPeriod.period_end >= today))
    return {
        "company": {"id": str(company.id), "name": company.name, "code": company.code,
                    "currency": company.default_currency},
        "branches": [{"id": str(b.id), "code": b.code, "name": b.name} for b in branches
                     if ctx.branch_ids is None or b.id in ctx.branch_ids],
        "branch_id": str(ctx.branch_id) if ctx.branch_id else None,
        "financial_years": [{"id": str(fy.id), "name": fy.name, "start_date": fy.start_date,
                             "end_date": fy.end_date, "is_current": fy.is_current} for fy in years],
        "current_period": ({"id": str(period.id), "name": period.name, "status": period.status}
                           if period else None),
        "has_chart": db.scalar(select(func.count()).select_from(Account)
                               .where(Account.company_id == ctx.company_id)) > 0,
    }


@router.get("/meta")
def meta(ctx: FinanceContext = Depends(finance_context(VIEW))):
    return {
        "control_types": CONTROL_TYPES,
        "journal_statuses": JOURNAL_STATUSES,
        "journal_types": JOURNAL_TYPES,
        "schedules": SCHEDULES,
        "reconciliation_categories": RECONCILIATION_CATEGORIES,
        "events": [{"code": e.code, "label": e.label, "description": e.description,
                    "explicit_lines": e.explicit_lines} for e in EVENTS.values()],
    }


@router.post("/setup/install-defaults")
def install_defaults(db: Session = Depends(get_db),
                     ctx: FinanceContext = Depends(finance_context(SETUP))):
    """Standard chart (only if the company has none), numbering series,
    posting rules and periods. Never creates a balance."""
    result = setup.install_defaults(db, ctx.company_id, ctx.audit)
    commit(db)
    return result


# ============================================================ chart of accounts

def _account(a: Account, types: dict, groups: dict, balance: Decimal | None = None) -> dict:
    t = types.get(a.account_type_id)
    return {
        "id": str(a.id), "code": a.code, "name": a.name,
        "account_type_id": str(a.account_type_id),
        "account_type": t.code if t else None, "account_type_name": t.name if t else None,
        "account_group_id": str(a.account_group_id) if a.account_group_id else None,
        "account_group": groups.get(a.account_group_id),
        "parent_id": str(a.parent_id) if a.parent_id else None,
        "normal_balance": a.normal_balance, "is_postable": a.is_postable,
        "is_control_account": a.is_control_account, "control_type": a.control_type,
        "allow_manual_posting": a.allow_manual_posting, "is_active": a.is_active,
        "currency": a.currency, "description": a.description,
        "balance": _num(balance) if balance is not None else None,
        "created_at": a.created_at, "updated_at": a.updated_at,
    }


@router.get("/account-types")
def account_types(db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(VIEW))):
    return [{"id": str(t.id), "code": t.code, "name": t.name, "normal_balance": t.normal_balance,
             "statement": t.statement} for t in db.scalars(select(AccountType).order_by(AccountType.sort_order))]


@router.get("/account-groups")
def list_groups(db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(VIEW))):
    return [{"id": str(g.id), "code": g.code, "name": g.name,
             "account_type_id": str(g.account_type_id),
             "parent_id": str(g.parent_id) if g.parent_id else None,
             "sort_order": g.sort_order, "is_active": g.is_active}
            for g in db.scalars(select(AccountGroup).where(AccountGroup.company_id == ctx.company_id)
                                .order_by(AccountGroup.sort_order, AccountGroup.code))]


@router.post("/account-groups", status_code=201)
def create_group(payload: AccountGroupIn, db: Session = Depends(get_db),
                 ctx: FinanceContext = Depends(finance_context(SETUP))):
    group = AccountGroup(company_id=ctx.company_id, created_by=ctx.user_id, **payload.model_dump())
    db.add(group)
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="create", module="finance", entity="account_groups",
           entity_id=group.id, company_id=ctx.company_id, new_values=snapshot(group))
    commit(db)
    return {"id": str(group.id)}


@router.put("/account-groups/{group_id}")
def update_group(group_id: uuid.UUID, payload: AccountGroupIn, db: Session = Depends(get_db),
                 ctx: FinanceContext = Depends(finance_context(SETUP))):
    group = db.get(AccountGroup, group_id)
    if group is None or group.company_id != ctx.company_id:
        raise FinanceError("That account group does not exist.", 404)
    before = snapshot(group)
    for key, value in payload.model_dump().items():
        setattr(group, key, value)
    group.updated_by = ctx.user_id
    old, new = changed(before, snapshot(group))
    record(db, ctx.audit, action="update", module="finance", entity="account_groups",
           entity_id=group.id, company_id=ctx.company_id, old_values=old, new_values=new)
    commit(db)
    return {"id": str(group.id)}


def _balances(db: Session, company_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    rows = db.execute(
        select(JournalEntryLine.account_id,
               func.sum(JournalEntryLine.base_debit - JournalEntryLine.base_credit))
        .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
        .where(JournalEntry.company_id == company_id,
               JournalEntry.status.in_(ledger.LEDGER_STATUSES))
        .group_by(JournalEntryLine.account_id)).all()
    return {account_id: Decimal(total or 0) for account_id, total in rows}


@router.get("/accounts")
def list_accounts(
    search: str | None = None,
    postable_only: bool = False,
    active_only: bool = False,
    manual_only: bool = False,
    journal_lines: bool = False,
    with_balances: bool = False,
    db: Session = Depends(get_db),
    ctx: FinanceContext = Depends(finance_context(VIEW)),
):
    """The whole chart, in code order: small enough to send at once, and the
    tree is built in the browser from parent_id."""
    stmt = select(Account).where(Account.company_id == ctx.company_id).order_by(Account.code)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Account.code.ilike(like), Account.name.ilike(like)))
    if postable_only:
        stmt = stmt.where(Account.is_postable.is_(True))
    if active_only:
        stmt = stmt.where(Account.is_active.is_(True))
    if manual_only:
        stmt = stmt.where(Account.allow_manual_posting.is_(True))
    elif journal_lines:
        # The manual journal form: open accounts plus the customer receivable,
        # whose lines become AR items when the journal posts.
        stmt = stmt.where(or_(Account.allow_manual_posting.is_(True),
                              Account.control_type.in_(posting.MANUAL_CONTROLS)))
    types = {t.id: t for t in db.scalars(select(AccountType))}
    groups = {g.id: g.name for g in db.scalars(select(AccountGroup).where(
        AccountGroup.company_id == ctx.company_id))}
    balances = _balances(db, ctx.company_id) if with_balances else {}
    rows = [_account(a, types, groups, balances.get(a.id, Decimal(0)) if with_balances else None)
            for a in db.scalars(stmt)]
    if with_balances:
        # How many customers / suppliers stand behind each control account, so
        # the chart can offer to list them (see /accounts/{id}/parties).
        counts = {kind: db.scalar(select(func.count()).select_from(BusinessPartner).where(
            BusinessPartner.company_id == ctx.company_id, flag.is_(True))) or 0
            for kind, flag in (("customer", BusinessPartner.is_customer), ("supplier", BusinessPartner.is_supplier))}
        for row in rows:
            kind = SUBLEDGER_OF.get(row["control_type"]) if row["is_postable"] else None
            row["subledger"] = {"kind": kind, "count": counts[kind]} if kind else None
    return rows


#: Which parties make up a control account's balance.
# A receipt not yet matched to an invoice is held as a customer advance, so that
# account has customers behind it as well.
SUBLEDGER_OF = {"RECEIVABLE": "customer", "CUSTOMER_ADVANCE": "customer", "PAYABLE": "supplier"}


@router.get("/accounts/{account_id}/parties")
def account_parties(account_id: uuid.UUID, db: Session = Depends(get_db),
                    ctx: FinanceContext = Depends(finance_context(VIEW))):
    """The customers behind a receivable account, or the suppliers behind a
    payable one, each with the balance its postings on this account add up to.

    Customers are not separate ledger accounts. Every invoice and receipt
    posts to the one control account with the customer on the line; a
    customer's balance is the sum of those lines. Listing them here is how
    each customer appears in the chart, under Current Assets, without the
    ledger holding a thousand accounts that could drift from the customer file.
    """
    account = chart.get_account(db, ctx.company_id, account_id)
    kind = SUBLEDGER_OF.get(account.control_type)
    if kind is None:
        return {"kind": None, "items": [], "total": 0.0, "unassigned": 0.0}
    party_column = JournalEntryLine.customer_id if kind == "customer" else JournalEntryLine.supplier_id
    posted = dict(db.execute(
        select(party_column, func.sum(JournalEntryLine.base_debit - JournalEntryLine.base_credit))
        .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
        .where(JournalEntry.company_id == ctx.company_id, JournalEntry.status.in_(ledger.LEDGER_STATUSES),
               JournalEntryLine.account_id == account.id)
        .group_by(party_column)).all())
    flag = BusinessPartner.is_customer if kind == "customer" else BusinessPartner.is_supplier
    partners = db.scalars(select(BusinessPartner).where(
        BusinessPartner.company_id == ctx.company_id, flag.is_(True)).order_by(BusinessPartner.name)).all()
    listed = {p.id for p in partners}
    # A posting to this account for a party that is not (or no longer) flagged
    # as this kind still belongs in the list, or the figures would not add up.
    extra_ids = [pid for pid in posted if pid is not None and pid not in listed]
    if extra_ids:
        partners += db.scalars(select(BusinessPartner).where(BusinessPartner.id.in_(extra_ids))).all()
    items = [{"id": str(p.id), "code": p.code, "name": p.name, "city": p.city, "is_active": p.is_active,
              "balance": _num(posted.get(p.id, Decimal(0)))} for p in partners]
    return {"kind": kind, "items": items,
            "total": _num(sum((Decimal(v or 0) for k, v in posted.items() if k is not None), Decimal(0))),
            # Posted to the control account with no party on the line.
            "unassigned": _num(Decimal(posted.get(None) or 0))}


@router.get("/accounts/{account_id}")
def get_account(account_id: uuid.UUID, db: Session = Depends(get_db),
                ctx: FinanceContext = Depends(finance_context(VIEW))):
    account = chart.get_account(db, ctx.company_id, account_id)
    types = {t.id: t for t in db.scalars(select(AccountType))}
    groups = {g.id: g.name for g in db.scalars(select(AccountGroup).where(
        AccountGroup.company_id == ctx.company_id))}
    return _account(account, types, groups, _balances(db, ctx.company_id).get(account.id, Decimal(0)))


@router.post("/accounts", status_code=201)
def create_account(payload: AccountIn, db: Session = Depends(get_db),
                   ctx: FinanceContext = Depends(finance_context(SETUP))):
    account = chart.create_account(db, ctx.company_id, payload.data(), ctx.audit)
    commit(db)
    return {"id": str(account.id)}


@router.put("/accounts/{account_id}")
def update_account(account_id: uuid.UUID, payload: AccountIn, db: Session = Depends(get_db),
                   ctx: FinanceContext = Depends(finance_context(SETUP))):
    chart.update_account(db, ctx.company_id, account_id, payload.data(), ctx.audit)
    commit(db)
    return {"id": str(account_id)}


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: uuid.UUID, db: Session = Depends(get_db),
                   ctx: FinanceContext = Depends(finance_context(SETUP))):
    chart.delete_account(db, ctx.company_id, account_id, ctx.audit)
    commit(db)
    return Response(status_code=204)


# ============================================================ cost centres

@router.get("/cost-centers")
def list_cost_centers(db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(VIEW))):
    return [{"id": str(c.id), "code": c.code, "name": c.name,
             "parent_id": str(c.parent_id) if c.parent_id else None, "is_active": c.is_active}
            for c in db.scalars(select(CostCenter).where(CostCenter.company_id == ctx.company_id)
                                .order_by(CostCenter.code))]


@router.post("/cost-centers", status_code=201)
def create_cost_center(payload: CostCenterIn, db: Session = Depends(get_db),
                       ctx: FinanceContext = Depends(finance_context(SETUP))):
    center = CostCenter(company_id=ctx.company_id, created_by=ctx.user_id, **payload.model_dump())
    db.add(center)
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="create", module="finance", entity="cost_centers",
           entity_id=center.id, company_id=ctx.company_id, new_values=snapshot(center))
    commit(db)
    return {"id": str(center.id)}


@router.put("/cost-centers/{center_id}")
def update_cost_center(center_id: uuid.UUID, payload: CostCenterIn, db: Session = Depends(get_db),
                       ctx: FinanceContext = Depends(finance_context(SETUP))):
    center = db.get(CostCenter, center_id)
    if center is None or center.company_id != ctx.company_id:
        raise FinanceError("That cost centre does not exist.", 404)
    before = snapshot(center)
    for key, value in payload.model_dump().items():
        setattr(center, key, value)
    center.updated_by = ctx.user_id
    old, new = changed(before, snapshot(center))
    record(db, ctx.audit, action="update", module="finance", entity="cost_centers",
           entity_id=center.id, company_id=ctx.company_id, old_values=old, new_values=new)
    commit(db)
    return {"id": str(center.id)}


# ============================================================ years & periods

def _period(p: AccountingPeriod, users: dict) -> dict:
    return {"id": str(p.id), "financial_year_id": str(p.financial_year_id),
            "period_number": p.period_number, "name": p.name,
            "period_start": p.period_start, "period_end": p.period_end, "status": p.status,
            "closed_at": p.closed_at, "closed_by": users.get(p.closed_by),
            "locked_at": p.locked_at, "locked_by": users.get(p.locked_by)}


@router.get("/financial-years")
def list_years(db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(VIEW))):
    years = db.scalars(select(FinancialYear).where(FinancialYear.company_id == ctx.company_id)
                       .order_by(FinancialYear.start_date.desc())).all()
    all_periods = db.scalars(select(AccountingPeriod).where(
        AccountingPeriod.company_id == ctx.company_id).order_by(AccountingPeriod.period_number)).all()
    users = _names(db, User, {x for p in all_periods for x in (p.closed_by, p.locked_by)})
    counts = dict(db.execute(
        select(JournalEntry.accounting_period_id, func.count())
        .where(JournalEntry.company_id == ctx.company_id,
               JournalEntry.status.in_(ledger.LEDGER_STATUSES))
        .group_by(JournalEntry.accounting_period_id)).all())
    return [{
        "id": str(fy.id), "name": fy.name, "start_date": fy.start_date, "end_date": fy.end_date,
        "is_current": fy.is_current, "is_closed": fy.is_closed,
        "periods": [{**_period(p, users), "posted_journals": counts.get(p.id, 0)}
                    for p in all_periods if p.financial_year_id == fy.id],
    } for fy in years]


@router.post("/financial-years", status_code=201)
def create_year(payload: FinancialYearIn, db: Session = Depends(get_db),
                ctx: FinanceContext = Depends(finance_context("finance.close_period"))):
    fy = periods.create_financial_year(db, ctx.company_id, payload.name.strip(), payload.start_date,
                                       payload.end_date, payload.make_current, ctx.audit)
    commit(db)
    return {"id": str(fy.id)}


def _year(db: Session, ctx: FinanceContext, fy_id: uuid.UUID) -> FinancialYear:
    fy = db.get(FinancialYear, fy_id)
    if fy is None or fy.company_id != ctx.company_id:
        raise FinanceError("That financial year does not exist.", 404)
    return fy


@router.post("/financial-years/{fy_id}/generate-periods")
def generate_periods(fy_id: uuid.UUID, db: Session = Depends(get_db),
                     ctx: FinanceContext = Depends(finance_context("finance.close_period"))):
    created = periods.generate_periods(db, _year(db, ctx, fy_id), ctx.audit)
    commit(db)
    return {"periods": len(created)}


@router.post("/financial-years/{fy_id}/set-current")
def set_current_year(fy_id: uuid.UUID, db: Session = Depends(get_db),
                     ctx: FinanceContext = Depends(finance_context("finance.close_period"))):
    periods.set_current(db, _year(db, ctx, fy_id), ctx.audit)
    commit(db)
    return {"id": str(fy_id)}


@router.post("/periods/{period_id}/close")
def close_period(period_id: uuid.UUID, payload: ReasonIn, db: Session = Depends(get_db),
                 ctx: FinanceContext = Depends(finance_context("finance.close_period"))):
    period = periods.close_period(db, ctx.company_id, period_id, payload.reason, ctx.audit)
    commit(db)
    return _period(period, {})


@router.post("/periods/{period_id}/reopen")
def reopen_period(period_id: uuid.UUID, payload: ReasonIn, db: Session = Depends(get_db),
                  ctx: FinanceContext = Depends(finance_context("finance.close_period"))):
    period = periods.reopen_period(db, ctx.company_id, period_id, payload.reason, ctx.audit)
    commit(db)
    return _period(period, {})


@router.post("/periods/{period_id}/lock")
def lock_period(period_id: uuid.UUID, payload: ReasonIn, db: Session = Depends(get_db),
                ctx: FinanceContext = Depends(finance_context("finance.close_period"))):
    period = periods.lock_period(db, ctx.company_id, period_id, payload.reason, ctx.audit)
    commit(db)
    return _period(period, {})


# ============================================================ numbering

@router.get("/document-series")
def list_series(db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(VIEW))):
    fy = periods.current_year(db, ctx.company_id)
    return [{
        "id": str(s.id), "doc_type": s.doc_type, "name": s.name, "prefix": s.prefix,
        "padding": s.padding, "format": s.format,
        "reset_each_fiscal_year": s.reset_each_fiscal_year, "per_branch": s.per_branch,
        "is_active": s.is_active, "next_number": numbering.peek(db, s, fy),
    } for s in db.scalars(select(DocumentSeries).where(
        DocumentSeries.company_id == ctx.company_id).order_by(DocumentSeries.doc_type))]


@router.put("/document-series/{series_id}")
def update_series(series_id: uuid.UUID, payload: SeriesIn, db: Session = Depends(get_db),
                  ctx: FinanceContext = Depends(finance_context(SETUP))):
    series = db.get(DocumentSeries, series_id)
    if series is None or series.company_id != ctx.company_id:
        raise FinanceError("That numbering series does not exist.", 404)
    before = snapshot(series)
    for key, value in payload.model_dump().items():
        setattr(series, key, value)
    numbering.validate_series(series)
    series.updated_by = ctx.user_id
    old, new = changed(before, snapshot(series))
    record(db, ctx.audit, action="update", module="finance", entity="document_series",
           entity_id=series.id, company_id=ctx.company_id, old_values=old, new_values=new)
    commit(db)
    return {"id": str(series.id)}


# ============================================================ posting rules

@router.get("/posting-rules")
def list_posting_rules(db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(VIEW))):
    rules = {(r.event_code, r.line_key): r for r in db.scalars(
        select(PostingRule).where(PostingRule.company_id == ctx.company_id))}
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.company_id == ctx.company_id))}
    out = []
    for event in EVENTS.values():
        out.append({
            "event_code": event.code, "label": event.label, "description": event.description,
            "explicit_lines": event.explicit_lines,
            "lines": [{
                "rule_id": str(rules[(event.code, line.key)].id) if (event.code, line.key) in rules else None,
                "line_key": line.key, "label": line.label, "side": line.side,
                "required": line.required, "party": line.party,
                "account_id": str(rule.account_id) if (rule := rules.get((event.code, line.key)))
                and rule.account_id else None,
                "account": (f"{accounts[rule.account_id].code} {accounts[rule.account_id].name}"
                            if rule and rule.account_id in accounts else None),
                "is_active": rule.is_active if rule else False,
            } for line in event.lines],
        })
    return out


@router.put("/posting-rules/{rule_id}")
def update_posting_rule(rule_id: uuid.UUID, payload: PostingRuleIn, db: Session = Depends(get_db),
                        ctx: FinanceContext = Depends(finance_context(SETUP))):
    rule = db.get(PostingRule, rule_id)
    if rule is None or rule.company_id != ctx.company_id:
        raise FinanceError("That posting rule does not exist.", 404)
    if payload.account_id:
        account = chart.get_account(db, ctx.company_id, payload.account_id)
        if not account.is_postable or not account.is_active:
            raise FinanceError(f"{account.code} {account.name} is a header or inactive account.")
    before = snapshot(rule, ["account_id", "is_active"])
    rule.account_id = payload.account_id
    rule.is_active = payload.is_active
    rule.updated_by = ctx.user_id
    record(db, ctx.audit, action="update", module="finance", entity="posting_rules",
           entity_id=rule.id, company_id=ctx.company_id, old_values=before,
           new_values={"account_id": payload.account_id, "is_active": payload.is_active,
                       "event_code": rule.event_code, "line_key": rule.line_key})
    commit(db)
    return {"id": str(rule.id)}


@router.post("/posting/preview")
def preview_posting(payload: PostingPreviewIn, db: Session = Depends(get_db),
                    ctx: FinanceContext = Depends(finance_context(VIEW))):
    """The entry an event would produce with the current rules. Writes nothing."""
    return posting.preview(db, posting.PostingRequest(
        event_code=payload.event_code, company_id=ctx.company_id,
        journal_date=payload.journal_date or date.today(), amounts=payload.amounts,
        customer_id=payload.customer_id, supplier_id=payload.supplier_id))


# ============================================================ journals

def _journal_summary(j: JournalEntry, users: dict, branches: dict) -> dict:
    return {
        "id": str(j.id), "journal_number": j.journal_number, "journal_date": j.journal_date,
        "journal_type": j.journal_type, "status": j.status, "description": j.description,
        "reference": j.reference, "event_code": j.event_code,
        "document_type": j.document_type,
        "document_id": str(j.document_id) if j.document_id else None,
        "source_module": j.source_module, "source_reference": j.source_reference,
        "branch_id": str(j.branch_id) if j.branch_id else None, "branch": branches.get(j.branch_id),
        "currency": j.currency, "total_debit": _num(j.total_debit), "total_credit": _num(j.total_credit),
        "created_by": users.get(j.created_by), "created_at": j.created_at,
        "posted_by": users.get(j.posted_by), "posted_at": j.posted_at,
    }


def _journal_detail(db: Session, j: JournalEntry) -> dict:
    users = _names(db, User, [j.created_by, j.submitted_by, j.approved_by, j.posted_by, j.cancelled_by])
    branches = _names(db, Branch, [j.branch_id] + [l.branch_id for l in j.lines])
    partners = _names(db, BusinessPartner, [x for l in j.lines for x in (l.customer_id, l.supplier_id)])
    accounts = {a.id: a for a in db.scalars(select(Account).where(
        Account.id.in_({l.account_id for l in j.lines})))} if j.lines else {}
    items = {i.id: i.item_code for i in db.scalars(select(InventoryItem).where(
        InventoryItem.id.in_({l.inventory_item_id for l in j.lines if l.inventory_item_id})))} \
        if any(l.inventory_item_id for l in j.lines) else {}
    centers = {c.id: c.name for c in db.scalars(select(CostCenter).where(
        CostCenter.company_id == j.company_id))}
    period = db.get(AccountingPeriod, j.accounting_period_id)
    fy = db.get(FinancialYear, j.financial_year_id)
    related = {}
    for key, target in (("reversed_entry", j.reversed_entry_id), ("reversed_by_entry", j.reversed_by_entry_id)):
        if target:
            other = db.get(JournalEntry, target)
            related[key] = {"id": str(other.id), "journal_number": other.journal_number}
    return {
        **_journal_summary(j, users, branches),
        "financial_year": fy.name if fy else None,
        "period": {"id": str(period.id), "name": period.name, "status": period.status} if period else None,
        "exchange_rate": _num(j.exchange_rate),
        "submitted_by": users.get(j.submitted_by), "submitted_at": j.submitted_at,
        "approved_by": users.get(j.approved_by), "approved_at": j.approved_at,
        "cancelled_by": users.get(j.cancelled_by), "cancelled_at": j.cancelled_at,
        "cancel_reason": j.cancel_reason,
        "reversed_entry": related.get("reversed_entry"),
        "reversed_by_entry": related.get("reversed_by_entry"),
        "lines": [{
            "id": str(l.id), "line_number": l.line_number,
            "account_id": str(l.account_id),
            "account_code": accounts[l.account_id].code if l.account_id in accounts else None,
            "account_name": accounts[l.account_id].name if l.account_id in accounts else None,
            "description": l.description,
            "debit": _num(l.debit), "credit": _num(l.credit),
            "base_debit": _num(l.base_debit), "base_credit": _num(l.base_credit),
            "currency": l.currency, "exchange_rate": _num(l.exchange_rate),
            "customer_id": str(l.customer_id) if l.customer_id else None,
            "supplier_id": str(l.supplier_id) if l.supplier_id else None,
            "party": partners.get(l.customer_id or l.supplier_id),
            "inventory_item_id": str(l.inventory_item_id) if l.inventory_item_id else None,
            "item_code": items.get(l.inventory_item_id),
            "quantity": _num(l.quantity) if l.quantity is not None else None,
            "cost_center_id": str(l.cost_center_id) if l.cost_center_id else None,
            "cost_center": centers.get(l.cost_center_id),
            "branch_id": str(l.branch_id) if l.branch_id else None,
            "branch": branches.get(l.branch_id),
        } for l in j.lines],
    }


@router.get("/journals")
def list_journals(
    search: str | None = None,
    status_filter: list[str] = Query(default=[], alias="status"),
    journal_type: str | None = None, document_type: str | None = None,
    financial_year_id: uuid.UUID | None = None,
    period_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=5000),
    db: Session = Depends(get_db),
    ctx: FinanceContext = Depends(finance_context(VIEW)),
):
    stmt = select(JournalEntry).where(JournalEntry.company_id == ctx.company_id)
    condition = ctx.branch_condition(JournalEntry.branch_id)
    if condition is not None:
        stmt = stmt.where(condition)
    if search:
        stmt = stmt.where(ledger.journal_search_condition(search))
    if status_filter:
        stmt = stmt.where(JournalEntry.status.in_(status_filter))
    if journal_type:
        stmt = stmt.where(JournalEntry.journal_type == journal_type)
    if document_type:
        # What the journal came from; a comma-separated list is accepted.
        stmt = stmt.where(JournalEntry.document_type.in_(document_type.split(",")))
    if financial_year_id:
        stmt = stmt.where(JournalEntry.financial_year_id == financial_year_id)
    if period_id:
        stmt = stmt.where(JournalEntry.accounting_period_id == period_id)
    if account_id:
        stmt = stmt.where(JournalEntry.lines.any(JournalEntryLine.account_id == account_id))
    if date_from:
        stmt = stmt.where(JournalEntry.journal_date >= date_from)
    if date_to:
        stmt = stmt.where(JournalEntry.journal_date <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(JournalEntry.journal_date.desc(), JournalEntry.journal_number.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    users = _names(db, User, [j.created_by for j in rows] + [j.posted_by for j in rows])
    branches = _names(db, Branch, [j.branch_id for j in rows])
    return {"items": [_journal_summary(j, users, branches) for j in rows],
            "total": total, "page": page, "page_size": page_size}


@router.get("/journals/{journal_id}")
def get_journal(journal_id: uuid.UUID, db: Session = Depends(get_db),
                ctx: FinanceContext = Depends(finance_context(VIEW))):
    return _journal_detail(db, journals.get_journal(db, ctx, journal_id))


def _payload(payload: JournalIn) -> dict:
    data = payload.model_dump()
    return data


@router.post("/journals", status_code=201)
def create_journal(payload: JournalIn, db: Session = Depends(get_db),
                   ctx: FinanceContext = Depends(finance_context("finance.create"))):
    journal = journals.create(db, ctx, _payload(payload))
    commit(db)
    return _journal_detail(db, journals.get_journal(db, ctx, journal.id))


@router.put("/journals/{journal_id}")
def update_journal(journal_id: uuid.UUID, payload: JournalIn, db: Session = Depends(get_db),
                   ctx: FinanceContext = Depends(finance_context("finance.edit"))):
    journals.update(db, ctx, journal_id, _payload(payload))
    commit(db)
    return _journal_detail(db, journals.get_journal(db, ctx, journal_id))


def _action(fn, permission: str, with_reason: bool = False):
    if with_reason:
        def handler(journal_id: uuid.UUID, payload: ReasonIn, db: Session = Depends(get_db),
                    ctx: FinanceContext = Depends(finance_context(permission))):
            fn(db, ctx, journal_id, payload.reason or "")
            commit(db)
            return _journal_detail(db, journals.get_journal(db, ctx, journal_id))
    else:
        def handler(journal_id: uuid.UUID, db: Session = Depends(get_db),
                    ctx: FinanceContext = Depends(finance_context(permission))):
            fn(db, ctx, journal_id)
            commit(db)
            return _journal_detail(db, journals.get_journal(db, ctx, journal_id))
    return handler


router.post("/journals/{journal_id}/submit")(_action(journals.submit, "finance.create"))
router.post("/journals/{journal_id}/approve")(_action(journals.approve, "finance.approve"))
router.post("/journals/{journal_id}/reject")(_action(journals.reject, "finance.approve", True))
router.post("/journals/{journal_id}/post")(_action(journals.post, "finance.post"))
router.post("/journals/{journal_id}/cancel")(_action(journals.cancel, "finance.edit", True))


@router.post("/journals/{journal_id}/reverse")
def reverse_journal(journal_id: uuid.UUID, payload: ReverseIn, db: Session = Depends(get_db),
                    ctx: FinanceContext = Depends(finance_context("finance.reverse"))):
    reversal = journals.reverse(db, ctx, journal_id, payload.reversal_date, payload.reason)
    commit(db)
    return _journal_detail(db, journals.get_journal(db, ctx, reversal.id))


# ============================================================ reports

REPORTS = "finance.reports"


def _jsonable_rows(rows: list[dict]) -> list[dict]:
    return [{k: (_num(v) if isinstance(v, Decimal) else v) for k, v in row.items()} for row in rows]


@router.get("/trial-balance")
def trial_balance(
    financial_year_id: uuid.UUID | None = None, period_id: uuid.UUID | None = None,
    date_from: date | None = None, date_to: date | None = None,
    branch_id: uuid.UUID | None = None, include_zero: bool = False, by_customer: bool = False,
    db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(REPORTS)),
):
    result = ledger.trial_balance(db, ctx, financial_year_id=financial_year_id, period_id=period_id,
                                  date_from=date_from, date_to=date_to, branch_id=branch_id,
                                  include_zero=include_zero, by_customer=by_customer)
    return {**result, "rows": _jsonable_rows(result["rows"]),
            "totals": {k: _num(v) for k, v in result["totals"].items()},
            "difference": _num(result["difference"])}


@router.get("/ledger/parties")
def ledger_parties(db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(REPORTS))):
    """Customers and suppliers to pick in the general ledger, each with the
    balance of their receivable, payable and advance accounts (debit-positive:
    a customer who has paid in advance shows a credit)."""
    key = func.coalesce(JournalEntryLine.customer_id, JournalEntryLine.supplier_id)
    balances = dict(db.execute(
        select(key, func.sum(JournalEntryLine.base_debit - JournalEntryLine.base_credit))
        .join(JournalEntry, JournalEntry.id == JournalEntryLine.journal_entry_id)
        .where(JournalEntry.company_id == ctx.company_id, JournalEntry.status.in_(ledger.LEDGER_STATUSES),
               JournalEntryLine.account_id.in_(ledger.party_accounts(ctx)), key.is_not(None))
        .group_by(key)).all())
    partners = db.scalars(select(BusinessPartner).where(
        BusinessPartner.company_id == ctx.company_id,
        or_(BusinessPartner.is_customer.is_(True), BusinessPartner.is_supplier.is_(True)))
        .order_by(BusinessPartner.name)).all()
    return [{"id": str(p.id), "code": p.code, "name": p.name,
             "kind": "customer" if p.is_customer else "supplier",
             "balance": _num(balances.get(p.id, Decimal(0)))} for p in partners]


@router.get("/ledger")
def general_ledger(
    account_id: uuid.UUID | None = None,
    financial_year_id: uuid.UUID | None = None, period_id: uuid.UUID | None = None,
    date_from: date | None = None, date_to: date | None = None,
    branch_id: uuid.UUID | None = None, cost_center_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None, supplier_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(200, ge=1, le=5000),
    db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(REPORTS)),
):
    result = ledger.general_ledger(
        db, ctx, account_id, financial_year_id=financial_year_id, period_id=period_id,
        date_from=date_from, date_to=date_to, branch_id=branch_id, cost_center_id=cost_center_id,
        customer_id=customer_id, supplier_id=supplier_id, page=page, page_size=page_size)
    return {**result, "rows": _jsonable_rows(result["rows"]),
            **{k: _num(result[k]) for k in ("opening_balance", "total_debit", "total_credit",
                                             "closing_balance")}}


def _range_label(start: date | None, end: date | None) -> str:
    if start and end:
        return f"{start:%d-%b-%Y} to {end:%d-%b-%Y}"
    if end:
        return f"up to {end:%d-%b-%Y}"
    if start:
        return f"from {start:%d-%b-%Y}"
    return "all dates"


def _export(rows: list[dict], columns: list[tuple[str, str]], title: str, stem: str, fmt: str,
            db: Session, ctx: FinanceContext, header: dict | None = None) -> Response:
    media_type, extension, writer = FORMATS[fmt]
    if fmt == "csv":
        payload = writer(columns, rows)
    elif fmt == "pdf" and header:
        payload = writer(columns, rows, title, header)
    else:
        payload = writer(columns, rows, title)
    record(db, ctx.audit, action="export", module="finance", entity=stem,
           company_id=ctx.company_id, new_values={"format": fmt, "rows": len(rows), "title": title})
    commit(db)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return Response(content=payload, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{stem}-{stamp}.{extension}"'})


@router.get("/trial-balance/export")
def export_trial_balance(
    request_format: str = Query("xlsx", alias="format", pattern="^(csv|xlsx|pdf)$"),
    financial_year_id: uuid.UUID | None = None, period_id: uuid.UUID | None = None,
    date_from: date | None = None, date_to: date | None = None,
    branch_id: uuid.UUID | None = None, by_customer: bool = False,
    db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(REPORTS)),
):
    result = ledger.trial_balance(db, ctx, financial_year_id=financial_year_id, period_id=period_id,
                                  date_from=date_from, date_to=date_to, branch_id=branch_id,
                                  by_customer=by_customer)
    company = db.get(Company, ctx.company_id)
    branch = db.get(Branch, branch_id) if branch_id else None
    rows = result["rows"] + [{"account_code": "", "account_name": "TOTAL", **result["totals"],
                              "debit": result["totals"]["closing_debit"],
                              "credit": result["totals"]["closing_credit"],
                              "balance": result["difference"]}]
    title = (f"Trial Balance — {company.name}{' — ' + branch.name if branch else ''} — "
             f"{_range_label(result['date_from'], result['date_to'])} ({company.default_currency})")
    columns = [("account_code", "Account Code"), ("account_name", "Account Name"),
               ("opening_debit", "Opening Debit"), ("opening_credit", "Opening Credit"),
               ("period_debit", "Period Debit"), ("period_credit", "Period Credit"),
               ("debit", "Closing Debit"), ("credit", "Closing Credit"), ("balance", "Balance")]
    return _export(rows, columns, title, "trial-balance", request_format, db, ctx)


@router.get("/ledger/export")
def export_ledger(
    account_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None, supplier_id: uuid.UUID | None = None,
    request_format: str = Query("xlsx", alias="format", pattern="^(csv|xlsx|pdf)$"),
    financial_year_id: uuid.UUID | None = None, period_id: uuid.UUID | None = None,
    date_from: date | None = None, date_to: date | None = None, branch_id: uuid.UUID | None = None,
    db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(REPORTS)),
):
    title, columns, rows, stem, header = ledger_file(
        db, ctx, account_id, customer_id=customer_id, supplier_id=supplier_id,
        financial_year_id=financial_year_id, period_id=period_id,
        date_from=date_from, date_to=date_to, branch_id=branch_id)
    return _export(rows, columns, title, stem, request_format, db, ctx, header)


def ledger_file(db: Session, ctx: FinanceContext, account_id=None, *, customer_id=None, supplier_id=None,
                financial_year_id=None, period_id=None, date_from=None, date_to=None, branch_id=None):
    """Title, columns and rows of a downloaded ledger. The customer statement's
    download uses it too, so every customer ledger file reads the same."""
    result = ledger.general_ledger(db, ctx, account_id, financial_year_id=financial_year_id,
                                   period_id=period_id, date_from=date_from, date_to=date_to,
                                   branch_id=branch_id, customer_id=customer_id, supplier_id=supplier_id,
                                   page=1, page_size=10**9)
    company = db.get(Company, ctx.company_id)
    account, party = result["account"], result["party"]
    subject = " — ".join(x for x in (f"{account['code']} {account['name']}" if account else None,
                                     f"{party['code']} {party['name']}" if party else None) if x)
    rows = ([{"narration": "Opening balance", "running_balance": result["opening_balance"]}]
            + result["rows"]
            + [{"narration": "Closing balance", "debit": result["total_debit"],
                "credit": result["total_credit"], "running_balance": result["closing_balance"]}])
    title = (f"General Ledger — {subject} — {company.name} — "
             f"{_range_label(result['date_from'], result['date_to'])} ({company.default_currency})")
    # The downloaded file is laid out as the owner asked (13-Oct-2026): voucher
    # number first, no account, party, branch or cost-centre columns. A ledger of
    # an account alone keeps the party, since its lines would otherwise be anonymous.
    columns = [("voucher_no", "Voucher No"), ("invoice_no", "Invoice No"), ("journal_date", "Date"),
               ("journal_number", "Journal"), ("narration", "Narration"),
               *([] if party else [("customer", "Customer"), ("supplier", "Supplier")]),
               ("cheque_ref", "Cheque No / Ref No"), ("cheque_date", "Cheque Date"),
               ("debit", "Debit"), ("credit", "Credit"), ("running_balance", "Balance")]
    # The printed heading: company, report, period, and the account (the
    # customer or supplier, where one is chosen) in a box underneath.
    dates = [r["journal_date"] for r in result["rows"] if r.get("journal_date")]
    start = result["date_from"] or (min(dates) if dates else None)
    end = result["date_to"] or date.today()
    subject_of = party or account
    header = {"company": company.name, "report": "General Ledger",
              "date_from": f"{start:%d-%b-%Y}".upper() if start else "",
              "date_to": f"{end:%d-%b-%Y}".upper(),
              "printed": datetime.now().strftime("%d-%b-%y %I:%M %p"),
              "code": subject_of["code"],
              "name": subject_of["name"] + (f" — {account['code']} {account['name']}" if party and account else "")}
    return title, columns, rows, f"ledger-{(account or party)['code']}", header


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(VIEW))):
    data = ledger.dashboard(db, ctx)
    return {k: (_num(v) if isinstance(v, Decimal) else v) for k, v in data.items()}


@router.get("/sales-summary")
def sales_summary(db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(VIEW))):
    def plain(row: dict) -> dict:
        return {k: (_num(v) if isinstance(v, Decimal) else v) for k, v in row.items()}
    data = ledger.sales_summary(db, ctx)
    return {"years": [{**plain(y), "months": [plain(m) for m in y["months"]]} for y in data["years"]],
            "totals": plain(data["totals"])}


# ============================================================ opening balances

OPENING = "finance.opening_balance"


def _batch(db: Session, b: OpeningBalanceBatch, with_lines: bool = False) -> dict:
    users = _names(db, User, [b.prepared_by, b.approved_by, b.posted_by, b.completed_by])
    fy = db.get(FinancialYear, b.financial_year_id)
    journal = db.get(JournalEntry, b.journal_entry_id) if b.journal_entry_id else None
    data = {
        "id": str(b.id), "batch_number": b.batch_number, "status": b.status,
        "financial_year_id": str(b.financial_year_id), "financial_year": fy.name if fy else None,
        "branch_id": str(b.branch_id) if b.branch_id else None,
        "cutover_date": b.cutover_date, "source_document": b.source_document, "notes": b.notes,
        "prepared_by": users.get(b.prepared_by), "created_at": b.created_at,
        "validated_at": b.validated_at,
        "approved_by": users.get(b.approved_by), "approved_at": b.approved_at,
        "posted_by": users.get(b.posted_by), "posted_at": b.posted_at,
        "completed_by": users.get(b.completed_by), "completed_at": b.completed_at,
        "journal": {"id": str(journal.id), "journal_number": journal.journal_number} if journal else None,
        "total_debit": _num(b.total_debit), "total_credit": _num(b.total_credit),
        **opening.batch_summary(b),
    }
    if with_lines:
        imports = db.scalars(select(OpeningBalanceImport).where(OpeningBalanceImport.batch_id == b.id)
                             .order_by(OpeningBalanceImport.imported_at.desc())).all()
        data["imports"] = [{"schedule": i.schedule, "file_name": i.file_name, "rows": i.row_count,
                            "imported_at": i.imported_at, "file_hash": i.file_hash[:12]} for i in imports]
        data["schedules"] = {s: [] for s in SCHEDULES}
        for line in b.lines:
            data["schedules"][line.schedule].append({
                "id": str(line.id), "row_number": line.row_number,
                "account_code": line.account_code, "account_name": line.account_name,
                "debit": _num(line.debit), "credit": _num(line.credit),
                "party_code": line.party_code, "party_name": line.party_name,
                "item_code": line.item_code, "location_name": line.location_name,
                "quantity": _num(line.quantity) if line.quantity is not None else None,
                "unit_cost": _num(line.unit_cost) if line.unit_cost is not None else None,
                "amount": _num(line.amount) if line.amount is not None else None,
                "reference": line.reference, "document_date": line.document_date,
                "due_date": line.due_date, "bank_name": line.bank_name,
                "bank_account_number": line.bank_account_number,
                "statement_balance": _num(line.statement_balance) if line.statement_balance is not None else None,
                "uncleared_deposits": _num(line.uncleared_deposits) if line.uncleared_deposits is not None else None,
                "uncleared_payments": _num(line.uncleared_payments) if line.uncleared_payments is not None else None,
                "branch_code": line.branch_code, "errors": line.errors or [],
                "resolved": bool(line.account_id) and not line.errors,
            })
    return data


@router.get("/opening-balances")
def list_batches(db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(VIEW))):
    stmt = (select(OpeningBalanceBatch).options(selectinload(OpeningBalanceBatch.lines))
            .where(OpeningBalanceBatch.company_id == ctx.company_id)
            .order_by(OpeningBalanceBatch.created_at.desc()))
    condition = ctx.branch_condition(OpeningBalanceBatch.branch_id)
    if condition is not None:
        stmt = stmt.where(condition)
    return [_batch(db, b) for b in db.scalars(stmt)]


@router.get("/opening-balances/template")
def opening_template(ctx: FinanceContext = Depends(finance_context(VIEW))):
    return Response(
        content=opening.template_workbook(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="opening-balance-template.xlsx"'})


@router.post("/opening-balances", status_code=201)
def create_batch(payload: OpeningBatchIn, db: Session = Depends(get_db),
                 ctx: FinanceContext = Depends(finance_context(OPENING))):
    batch = opening.create_batch(db, ctx, payload.model_dump())
    commit(db)
    return _batch(db, opening.get_batch(db, ctx, batch.id), with_lines=True)


@router.get("/opening-balances/{batch_id}")
def get_batch(batch_id: uuid.UUID, db: Session = Depends(get_db),
              ctx: FinanceContext = Depends(finance_context(VIEW))):
    return _batch(db, opening.get_batch(db, ctx, batch_id), with_lines=True)


@router.post("/opening-balances/{batch_id}/import")
async def import_batch_file(
    batch_id: uuid.UUID,
    file: UploadFile = File(...),
    schedule: str | None = Form(default=None),
    db: Session = Depends(get_db),
    ctx: FinanceContext = Depends(finance_context(OPENING)),
):
    content = await file.read()
    batch = opening.get_batch(db, ctx, batch_id)
    imported = opening.import_file(db, ctx, batch, schedule or None, file.filename or "", content)
    commit(db)
    return {"imported": imported, "batch": _batch(db, opening.get_batch(db, ctx, batch_id), with_lines=True)}


@router.post("/opening-balances/{batch_id}/validate")
def validate_batch(batch_id: uuid.UUID, db: Session = Depends(get_db),
                   ctx: FinanceContext = Depends(finance_context(OPENING))):
    result = opening.validate(db, ctx, batch_id)
    commit(db)
    return {**result, "batch": _batch(db, opening.get_batch(db, ctx, batch_id), with_lines=True)}


@router.get("/opening-balances/{batch_id}/preview")
def preview_batch(batch_id: uuid.UUID, db: Session = Depends(get_db),
                  ctx: FinanceContext = Depends(finance_context(VIEW))):
    result = opening.preview(db, ctx, batch_id)
    return {**result, "lines": _jsonable_rows(result["lines"]),
            "tie_out": _jsonable_rows(result["tie_out"]),
            "total_debit": _num(result["total_debit"]), "total_credit": _num(result["total_credit"]),
            "schedules": {k: {**v, "total": _num(v["total"])} for k, v in result["schedules"].items()}}


@router.post("/opening-balances/{batch_id}/approve")
def approve_batch(batch_id: uuid.UUID, db: Session = Depends(get_db),
                  ctx: FinanceContext = Depends(finance_context("finance.approve"))):
    opening.approve(db, ctx, batch_id)
    commit(db)
    return _batch(db, opening.get_batch(db, ctx, batch_id), with_lines=True)


@router.post("/opening-balances/{batch_id}/post")
def post_batch(batch_id: uuid.UUID, db: Session = Depends(get_db),
               ctx: FinanceContext = Depends(finance_context("finance.post"))):
    opening.post(db, ctx, batch_id)
    commit(db)
    return _batch(db, opening.get_batch(db, ctx, batch_id), with_lines=True)


@router.post("/opening-balances/{batch_id}/cancel")
def cancel_batch(batch_id: uuid.UUID, payload: ReasonIn, db: Session = Depends(get_db),
                 ctx: FinanceContext = Depends(finance_context(OPENING))):
    opening.cancel(db, ctx, batch_id, payload.reason or "")
    commit(db)
    return _batch(db, opening.get_batch(db, ctx, batch_id), with_lines=True)


def _reconciliation_out(result: dict) -> dict:
    return {**result, "rows": _jsonable_rows(result["rows"]),
            "subledgers": _jsonable_rows(result["subledgers"])}


@router.get("/opening-balances/{batch_id}/reconciliation")
def get_reconciliation(batch_id: uuid.UUID, db: Session = Depends(get_db),
                       ctx: FinanceContext = Depends(finance_context(VIEW))):
    return _reconciliation_out(opening.reconciliation(db, ctx, batch_id))


@router.put("/opening-balances/{batch_id}/reconciliation")
def save_reconciliation(batch_id: uuid.UUID, payload: ReconciliationIn, db: Session = Depends(get_db),
                        ctx: FinanceContext = Depends(finance_context(OPENING))):
    result = opening.save_reconciliation(db, ctx, batch_id, [e.model_dump() for e in payload.entries])
    commit(db)
    return _reconciliation_out(result)


@router.post("/opening-balances/{batch_id}/complete")
def complete_batch(batch_id: uuid.UUID, db: Session = Depends(get_db),
                   ctx: FinanceContext = Depends(finance_context("finance.approve"))):
    opening.complete(db, ctx, batch_id)
    commit(db)
    return _batch(db, opening.get_batch(db, ctx, batch_id), with_lines=True)


# ============================================================ audit log

@router.get("/audit-logs")
def audit_logs(
    entity: str | None = None, entity_id: str | None = None, action: str | None = None,
    module: str | None = None, username: str | None = None,
    date_from: date | None = None, date_to: date | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=5000),
    db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context("finance.audit")),
):
    stmt = select(AuditLog).where(or_(AuditLog.company_id == ctx.company_id, AuditLog.company_id.is_(None)))
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if module:
        stmt = stmt.where(AuditLog.module == module)
    if username:
        stmt = stmt.where(AuditLog.username.ilike(f"%{username}%"))
    if date_from:
        stmt = stmt.where(func.date(AuditLog.occurred_at) >= date_from)
    if date_to:
        stmt = stmt.where(func.date(AuditLog.occurred_at) <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.occurred_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{
        "id": str(r.id), "occurred_at": r.occurred_at, "username": r.username,
        "action": r.action, "module": r.module, "entity": r.entity, "entity_id": r.entity_id,
        "old_values": r.old_values, "new_values": r.new_values,
        "ip_address": r.ip_address, "reason": r.reason,
    } for r in rows], "total": total, "page": page, "page_size": page_size}
