"""Journals, the database guarantees behind them, the general ledger and the
trial balance. Spec tests 1–11, plus the audit trail."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.finance import journals, ledger, periods, posting
from app.finance.errors import FinanceError
from app.finance.models import POSTED, REVERSED, JournalEntry, JournalEntryLine

D = Decimal
JUL = date(2026, 7, 15)
AUG = date(2026, 8, 10)


def lines(world, *rows):
    """rows: (account code, debit, credit[, extra dict])"""
    out = []
    for row in rows:
        code, debit, credit = row[:3]
        extra = row[3] if len(row) > 3 else {}
        out.append({"account_id": world.account(code).id, "debit": D(str(debit)),
                    "credit": D(str(credit)), "description": f"{code} line", **extra})
    return out


def manual(world, on=JUL, rows=None, **kw):
    """Create, submit, approve and post a manual journal."""
    ctx = world.ctx()
    rows = rows or lines(world, ("6110", 1000, 0), ("1110", 0, 1000))
    journal = journals.create(world.db, ctx, {"journal_date": on, "lines": rows,
                                              "description": kw.get("description", "Rent")})
    journals.submit(world.db, ctx, journal.id)
    journals.approve(world.db, ctx, journal.id)
    return journals.post(world.db, ctx, journal.id)


# 1
def test_balanced_journal_posts(world):
    journal = manual(world)
    assert journal.status == POSTED
    assert journal.total_debit == journal.total_credit == D("1000.00")
    assert journal.journal_number == "JV-000001"
    assert journal.posted_at is not None and journal.posted_by == world.admin.id


# 2
def test_unbalanced_journal_rejected_by_service(world):
    with pytest.raises(FinanceError, match="not balanced"):
        journals.create(world.db, world.ctx(), {
            "journal_date": JUL, "lines": lines(world, ("6110", 1000, 0), ("1110", 0, 900))})


def test_unbalanced_journal_rejected_by_database(world, db):
    """Even code that skips the service cannot post an unbalanced journal."""
    journal = posting.new_journal(db, company_id=world.company.id, journal_date=JUL,
                                  journal_type="MANUAL", branch_id=None, description="raw",
                                  reference=None, user_id=world.admin.id)
    db.flush()
    db.add_all([
        JournalEntryLine(journal_entry_id=journal.id, company_id=world.company.id, line_number=1,
                         account_id=world.account("6110").id, debit=D(500), base_debit=D(500)),
        JournalEntryLine(journal_entry_id=journal.id, company_id=world.company.id, line_number=2,
                         account_id=world.account("1110").id, credit=D(400), base_credit=D(400)),
    ])
    journal.total_debit, journal.total_credit = D(500), D(400)
    db.flush()
    journal.status = POSTED
    with pytest.raises(DBAPIError, match="not balanced"):
        db.flush()


def test_single_line_journal_rejected(world):
    with pytest.raises(FinanceError, match="at least two lines"):
        posting.validate_lines(world.db, world.company.id, [posting.PostingLine(
            account_id=world.account("1110").id, debit=D(1))], manual=True)


# 3 & 4
@pytest.mark.parametrize("debit,credit", [(-100, 0), (0, -100)])
def test_negative_amounts_rejected_by_service(world, debit, credit):
    with pytest.raises(FinanceError, match="negative"):
        journals.create(world.db, world.ctx(), {"journal_date": JUL, "lines": lines(
            world, ("6110", debit, credit), ("1110", 100, 0))})


@pytest.mark.parametrize("column", ["debit", "credit"])
def test_negative_amounts_rejected_by_database(world, db, column):
    journal = posting.new_journal(db, company_id=world.company.id, journal_date=JUL,
                                  journal_type="MANUAL", branch_id=None, description=None,
                                  reference=None, user_id=None)
    db.flush()
    db.add(JournalEntryLine(journal_entry_id=journal.id, company_id=world.company.id, line_number=1,
                            account_id=world.account("6110").id, **{column: D(-5)}))
    with pytest.raises(DBAPIError, match="ck_line"):
        db.flush()


def test_debit_and_credit_on_one_line_rejected(world, db):
    with pytest.raises(FinanceError, match="not both"):
        journals.create(world.db, world.ctx(), {"journal_date": JUL, "lines": lines(
            world, ("6110", 100, 100), ("1110", 0, 0))})
    journal = posting.new_journal(db, company_id=world.company.id, journal_date=JUL,
                                  journal_type="MANUAL", branch_id=None, description=None,
                                  reference=None, user_id=None)
    db.flush()
    db.add(JournalEntryLine(journal_entry_id=journal.id, company_id=world.company.id, line_number=1,
                            account_id=world.account("6110").id, debit=D(5), credit=D(5),
                            base_debit=D(5), base_credit=D(5)))
    with pytest.raises(DBAPIError, match="ck_line"):
        db.flush()


# 5
def test_closed_period_rejects_posting(world, db):
    ctx = world.ctx()
    journal = journals.create(db, ctx, {"journal_date": JUL, "lines": lines(
        world, ("6110", 50, 0), ("1110", 0, 50))})
    journals.submit(db, ctx, journal.id)
    journals.approve(db, ctx, journal.id)
    period = world.period(JUL)
    # A period with an unposted journal cannot be closed…
    with pytest.raises(FinanceError, match="not posted or cancelled"):
        periods.close_period(db, world.company.id, period.id, "month end", world.audit)
    # …so force it closed underneath the journal and try to post.
    db.execute(text("update accounting_periods set status = 'CLOSED' where id = :id"), {"id": period.id})
    db.expire_all()
    with pytest.raises(FinanceError, match="CLOSED"):
        journals.post(db, ctx, journal.id)


def test_closed_period_rejected_by_database(world, db):
    ctx = world.ctx()
    journal = journals.create(db, ctx, {"journal_date": JUL, "lines": lines(
        world, ("6110", 50, 0), ("1110", 0, 50))})
    db.execute(text("update accounting_periods set status = 'CLOSED' where id = :id"),
               {"id": journal.accounting_period_id})
    with pytest.raises(DBAPIError, match="does not accept postings"):
        db.execute(text("update journal_entries set status = 'POSTED' where id = :id"), {"id": journal.id})


def test_period_close_reopen_and_lock(world, db):
    period = world.period(AUG)
    periods.close_period(db, world.company.id, period.id, "month end", world.audit)
    with pytest.raises(FinanceError, match="reason"):
        periods.reopen_period(db, world.company.id, period.id, "", world.audit)
    periods.reopen_period(db, world.company.id, period.id, "late supplier bill", world.audit)
    periods.close_period(db, world.company.id, period.id, "again", world.audit)
    periods.lock_period(db, world.company.id, period.id, "audited", world.audit)
    with pytest.raises(FinanceError, match="locked"):
        periods.reopen_period(db, world.company.id, period.id, "please", world.audit)
    db.flush()
    with pytest.raises(DBAPIError, match="locked"):
        db.execute(text("update accounting_periods set status = 'OPEN' where id = :id"), {"id": period.id})


# 6
def test_duplicate_journal_number_rejected(world, db):
    first = manual(world)
    second = journals.create(db, world.ctx(), {"journal_date": JUL, "lines": lines(
        world, ("6110", 10, 0), ("1110", 0, 10))})
    db.flush()
    second.journal_number = first.journal_number
    with pytest.raises(DBAPIError, match="uq_journal_number"):
        db.flush()


def test_numbering_is_sequential_and_restarts_each_year(world, db):
    from app.companies.models import FinancialYear
    from app.finance import numbering
    assert manual(world).journal_number == "JV-000001"
    assert manual(world).journal_number == "JV-000002"
    next_year = periods.create_financial_year(db, world.company.id, "2027-28", date(2027, 7, 1),
                                              date(2028, 6, 30), False, world.audit)
    assert numbering.allocate(db, world.company.id, "JV", next_year) == "JV-000001"
    assert isinstance(next_year, FinancialYear)


# 7
def test_posted_journal_cannot_be_edited(world, db):
    journal = manual(world)
    with pytest.raises(FinanceError, match="only a draft can be edited"):
        journals.update(db, world.ctx(), journal.id, {"journal_date": JUL, "lines": lines(
            world, ("6110", 1, 0), ("1110", 0, 1))})
    with pytest.raises(DBAPIError, match="posted and cannot be edited"):
        db.execute(text("update journal_entries set description = 'changed' where id = :id"),
                   {"id": journal.id})


def test_posted_journal_lines_cannot_be_modified(world, db):
    journal = manual(world)
    with pytest.raises(DBAPIError, match="cannot be changed"):
        db.execute(text("update journal_entry_lines set debit = 1, base_debit = 1 "
                        "where journal_entry_id = :id and line_number = 1"), {"id": journal.id})


def test_line_cannot_be_added_to_posted_journal(world, db):
    journal = manual(world)
    with pytest.raises(DBAPIError, match="only be added to a DRAFT"):
        db.execute(text("""insert into journal_entry_lines
            (id, journal_entry_id, company_id, line_number, account_id, debit, base_debit)
            values (:id, :j, :c, 9, :a, 5, 5)"""),
            {"id": uuid.uuid4(), "j": journal.id, "c": world.company.id, "a": world.account("6110").id})


# 8
def test_posted_journal_cannot_be_deleted(world, db):
    journal = manual(world)
    with pytest.raises(DBAPIError, match="cannot be deleted"):
        db.execute(text("delete from journal_entries where id = :id"), {"id": journal.id})


def test_journal_cannot_be_inserted_as_posted(world, db):
    period = world.period(JUL)
    with pytest.raises(DBAPIError, match="must be created as DRAFT"):
        db.execute(text("""insert into journal_entries
            (id, company_id, financial_year_id, accounting_period_id, journal_number, journal_date, status)
            values (:id, :c, :fy, :p, 'X-1', :d, 'POSTED')"""),
            {"id": uuid.uuid4(), "c": world.company.id, "fy": world.fy.id, "p": period.id, "d": JUL})


def test_cancelled_journal_is_final(world, db):
    ctx = world.ctx()
    journal = journals.create(db, ctx, {"journal_date": JUL, "lines": lines(
        world, ("6110", 10, 0), ("1110", 0, 10))})
    journals.cancel(db, ctx, journal.id, "entered twice")
    with pytest.raises(DBAPIError, match="can no longer change"):
        db.execute(text("update journal_entries set status = 'DRAFT' where id = :id"), {"id": journal.id})


# 9
def test_reversal(world, db):
    original = manual(world)
    reversal = posting.reverse(db, original, AUG, "posted to the wrong account", world.audit)
    db.refresh(original)
    assert original.status == REVERSED
    assert original.reversed_by_entry_id == reversal.id
    assert reversal.reversed_entry_id == original.id
    assert reversal.status == POSTED and reversal.journal_type == "REVERSAL"
    by_account = {l.account_id: (l.debit, l.credit) for l in reversal.lines}
    assert by_account[world.account("6110").id] == (D(0), D(1000))
    assert by_account[world.account("1110").id] == (D(1000), D(0))

    tb = ledger.trial_balance(db, world.ctx(), financial_year_id=world.fy.id)
    assert all(row["balance"] == 0 for row in tb["rows"])
    assert tb["is_balanced"]

    with pytest.raises(FinanceError, match="Only a posted journal"):
        posting.reverse(db, original, AUG, "again please", world.audit)
    with pytest.raises(FinanceError, match="cannot itself be reversed"):
        posting.reverse(db, reversal, AUG, "undo the undo", world.audit)


def test_reversal_needs_reason_and_valid_date(world, db):
    original = manual(world, on=AUG)
    with pytest.raises(FinanceError, match="reason"):
        posting.reverse(db, original, AUG, "", world.audit)
    with pytest.raises(FinanceError, match="before the journal"):
        posting.reverse(db, original, JUL, "wrong account", world.audit)


# 10
def test_trial_balance(world, db):
    manual(world, rows=lines(world, ("1110", 50000, 0), ("3100", 0, 50000)), description="Capital")
    manual(world, rows=lines(world, ("6110", 12000, 0), ("1110", 0, 12000)), description="Rent")
    manual(world, on=AUG, rows=lines(world, ("6120", 3000, 0), ("1110", 0, 3000)), description="Power")
    # A draft never reaches the trial balance.
    journals.create(db, world.ctx(), {"journal_date": AUG, "lines": lines(
        world, ("6120", 999, 0), ("1110", 0, 999))})

    tb = ledger.trial_balance(db, world.ctx(), financial_year_id=world.fy.id)
    rows = {r["account_code"]: r for r in tb["rows"]}
    assert rows["1110"]["debit"] == D("35000.00")
    assert rows["3100"]["credit"] == D("50000.00")
    assert rows["6110"]["debit"] == D("12000.00")
    assert rows["6120"]["debit"] == D("3000.00")
    assert tb["totals"]["closing_debit"] == tb["totals"]["closing_credit"] == D("50000.00")
    assert tb["is_balanced"] and tb["difference"] == 0

    # August alone: July becomes the opening column.
    aug = ledger.trial_balance(db, world.ctx(), period_id=world.period(AUG).id)
    cash = {r["account_code"]: r for r in aug["rows"]}["1110"]
    assert cash["opening_debit"] == D("38000.00")
    assert cash["period_credit"] == D("3000.00")
    assert cash["closing_debit"] == D("35000.00")
    assert aug["is_balanced"]


# 11
def test_general_ledger_running_balance(world, db):
    manual(world, on=date(2026, 7, 1), rows=lines(world, ("1110", 10000, 0), ("3100", 0, 10000)))
    manual(world, on=date(2026, 7, 20), rows=lines(world, ("6110", 2500, 0), ("1110", 0, 2500)))
    manual(world, on=date(2026, 8, 5), rows=lines(world, ("6120", 1500, 0), ("1110", 0, 1500)))

    gl = ledger.general_ledger(db, world.ctx(), world.account("1110").id,
                               date_from=date(2026, 7, 10), date_to=date(2026, 8, 31))
    assert gl["opening_balance"] == D("10000.00")
    assert [r["running_balance"] for r in gl["rows"]] == [D("7500.00"), D("6000.00")]
    assert gl["total_credit"] == D("4000.00")
    assert gl["closing_balance"] == D("6000.00")
    row = gl["rows"][0]
    assert row["journal_number"] and row["journal_id"] and row["description"]


def test_manual_journal_cannot_hit_control_account(world):
    with pytest.raises(FinanceError, match="control account"):
        journals.create(world.db, world.ctx(), {"journal_date": JUL, "lines": lines(
            world, ("1140", 100, 0), ("4100", 0, 100))})


def test_customer_journal_line_goes_to_the_customers_account(world, db):
    """The customer receivable may be journalled by hand (owner, 20-Oct-2026):
    each line becomes an AR item, so aging and the ledger agree."""
    from app.receivables import subledger
    from app.receivables.models import ARItem

    with pytest.raises(FinanceError, match="name the customer"):
        journals.create(db, world.ctx(), {"journal_date": JUL, "lines": lines(
            world, ("1130", 100, 0), ("4100", 0, 100))})
    journal = manual(world, rows=lines(
        world, ("1130", 2500, 0, {"customer_id": world.customer.id}), ("4100", 0, 2500)))
    item = db.scalar(select(ARItem).where(ARItem.journal_entry_id == journal.id))
    assert item.item_type == "JOURNAL" and item.amount == D("2500.00")
    assert item.customer_id == world.customer.id and item.document_number == journal.journal_number
    assert subledger.balances(db, world.company.id)[world.customer.id]["receivable"] == D("2500.00")

    credit = manual(world, rows=lines(
        world, ("6110", 400, 0), ("1130", 0, 400, {"customer_id": world.customer.id})))
    assert subledger.balances(db, world.company.id)[world.customer.id]["receivable"] == D("2100.00")

    # Matched items must be unmatched before the journal is reversed.
    note = db.scalar(select(ARItem).where(ARItem.journal_entry_id == credit.id))
    allocation = subledger.allocate(db, world.audit, world.company.id, note.id, item.id, D(400), JUL)
    with pytest.raises(FinanceError, match="Undo that allocation"):
        journals.reverse(db, world.ctx(), credit.id, AUG, "wrong customer")
    subledger.unallocate(db, world.audit, world.company.id, allocation.id, "wrong customer")
    journals.reverse(db, world.ctx(), credit.id, AUG, "wrong customer")
    assert note.status == "CANCELLED"
    assert subledger.balances(db, world.company.id)[world.customer.id]["receivable"] == D("2500.00")


def test_header_and_inactive_accounts_rejected(world, db):
    with pytest.raises(FinanceError, match="header account"):
        journals.create(db, world.ctx(), {"journal_date": JUL, "lines": lines(
            world, ("1100", 100, 0), ("4100", 0, 100))})
    world.account("6150").is_active = False
    db.flush()
    with pytest.raises(FinanceError, match="inactive"):
        journals.create(db, world.ctx(), {"journal_date": JUL, "lines": lines(
            world, ("6150", 100, 0), ("1110", 0, 100))})


def test_draft_journal_can_be_edited(world, db):
    """Replacing a draft's lines reuses line numbers 1..n; found in Phase 1 validation."""
    ctx = world.ctx()
    journal = journals.create(db, ctx, {"journal_date": JUL, "lines": lines(
        world, ("6110", 100, 0), ("1110", 0, 100))})
    db.flush()
    journals.update(db, ctx, journal.id, {"journal_date": AUG, "description": "edited", "lines": lines(
        world, ("6120", 250, 0), ("6110", 50, 0), ("1110", 0, 300))})
    db.flush()
    db.refresh(journal)
    assert [(l.line_number, l.debit, l.credit) for l in journal.lines] == [
        (1, D("250.00"), D("0.00")), (2, D("50.00"), D("0.00")), (3, D("0.00"), D("300.00"))]
    assert journal.total_debit == D("300.00") and journal.journal_date == AUG
    assert journal.accounting_period_id == world.period(AUG).id


def test_draft_edit_through_api(client, world):
    body = {"journal_date": "2026-07-15", "lines": [
        {"account_id": str(world.account("6110").id), "debit": "10", "credit": "0"},
        {"account_id": str(world.account("1110").id), "debit": "0", "credit": "10"}]}
    jid = client.post("/api/v1/finance/journals", json=body).json()["id"]
    body["lines"][0]["debit"] = body["lines"][1]["credit"] = "20"
    edited = client.put(f"/api/v1/finance/journals/{jid}", json=body)
    assert edited.status_code == 200, edited.text
    assert edited.json()["total_debit"] == 20


def test_workflow_requires_approval_before_posting(world, db):
    ctx = world.ctx()
    journal = journals.create(db, ctx, {"journal_date": JUL, "lines": lines(
        world, ("6110", 10, 0), ("1110", 0, 10))})
    with pytest.raises(FinanceError, match="must be approved"):
        journals.post(db, ctx, journal.id)
    journals.submit(db, ctx, journal.id)
    journals.reject(db, ctx, journal.id, "wrong period")
    assert journal.status == "DRAFT"


def test_audit_trail_records_and_is_append_only(world, db):
    journal = manual(world)
    db.flush()  # the audit entry joins the caller's transaction; make it visible to raw SQL
    actions = [r[0] for r in db.execute(text(
        "select action from audit_logs where entity = 'journal_entries' and entity_id = :id "
        "order by occurred_at"), {"id": str(journal.id)})]
    assert {"create", "submit", "approve", "post"} <= set(actions)
    # Each refused statement in its own savepoint: after one refusal PostgreSQL
    # aborts the transaction, and the next check would never reach the trigger.
    with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
        db.execute(text("update audit_logs set action = 'x' where entity_id = :id"), {"id": str(journal.id)})
    with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
        db.execute(text("delete from audit_logs where entity_id = :id"), {"id": str(journal.id)})


def test_every_posted_journal_is_balanced(world, db):
    """The invariant behind every test above, checked across the ledger."""
    manual(world)
    manual(world, on=AUG, rows=lines(world, ("1110", 700, 0), ("7100", 0, 700)))
    unbalanced = db.execute(text("""
        select j.journal_number from journal_entries j join journal_entry_lines l on l.journal_entry_id = j.id
        where j.company_id = :c and j.status in ('POSTED','REVERSED')
        group by j.id, j.journal_number having sum(l.base_debit) <> sum(l.base_credit)"""),
        {"c": world.company.id}).all()
    assert unbalanced == []
    assert db.scalar(text("select count(*) from journal_entries where company_id = :c and status = 'POSTED'"),
                     {"c": world.company.id}) == 2
    assert JournalEntry  # imported for readers following the model
