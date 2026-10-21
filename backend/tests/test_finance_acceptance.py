"""Acceptance tests A to I of the finance brief: invoices, receipts against an
invoice, on-account receipts, later allocation, credit balances, duplicate
prevention, reversal and reconciliation. Each runs the real services inside the
rolled-back test transaction."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.finance import ledger
from app.finance.errors import FinanceError
from app.finance.models import JournalEntry
from app.receivables import documents, receipts, reports, subledger
from tests.test_receivables import ON, by_account, method, outstanding, posted_invoice, receipt

D = Decimal


def status(db, doc):
    return documents.payment_state(db, doc)["payment_status"]


def trial(world):
    tb = ledger.trial_balance(world.db, world.ctx())
    assert tb["is_balanced"]
    return {r["account_code"]: r["balance"] for r in tb["rows"]}


def journal_count(world):
    return world.db.scalar(select(func.count()).select_from(JournalEntry).where(
        JournalEntry.company_id == world.company.id))


def profile(world):
    return reports.customer_profile(world.db, world.ctx(), world.customer.id)


def test_a_invoice(world, db):
    inv = posted_invoice(world)                                   # 100,000 + 18% tax
    lines = by_account(world, db.get(JournalEntry, inv.journal_entry_id))
    assert lines == {"1130": (D("118000.00"), D("0")), "4100": (D("0"), D("100000.00")),
                     "2130": (D("0"), D("18000.00"))}
    assert status(db, inv) == "OPEN" and outstanding(world, inv) == D("118000.00")
    assert profile(world)["net_balance"] == D("118000.00")
    trial(world)


def test_b_c_partial_then_full_payment(world, db):
    inv = posted_invoice(world)
    receipt(world, 60000, [(inv, 60000)])
    assert outstanding(world, inv) == D("58000.00") and status(db, inv) == "PARTIALLY_PAID"
    receipt(world, 58000, [(inv, 58000)], on=ON + timedelta(days=3))
    assert outstanding(world, inv) == 0 and status(db, inv) == "PAID"
    tb = trial(world)
    assert tb["1130"] == 0 and tb["1121"] == D("118000.00")


def test_d_e_on_account_receipt_and_later_allocation(world, db):
    """1,000,000 outstanding over three invoices; 600,000 received with no
    invoice chosen; allocated afterwards."""
    a = posted_invoice(world, amount=500000, taxed=False)
    b = posted_invoice(world, amount=300000, taxed=False)
    c = posted_invoice(world, amount=200000, taxed=False)
    r = receipt(world, 600000, on=ON + timedelta(days=2))         # no invoice selected

    # D: Dr Bank / Cr the customer's receivable, in one entry.
    assert by_account(world, db.get(JournalEntry, r.journal_entry_id)) == {
        "1121": (D("600000.00"), D("0")), "1130": (D("0"), D("600000.00"))}
    p = profile(world)
    assert p["gross_outstanding"] == D("1000000.00")
    assert p["unallocated_receipts"] == D("600000.00")
    assert p["net_balance"] == D("400000.00") and p["advances"] == 0
    assert [status(db, x) for x in (a, b, c)] == ["OPEN"] * 3
    assert [outstanding(world, x) for x in (a, b, c)] == [D("500000.00"), D("300000.00"), D("200000.00")]
    assert trial(world)["1130"] == D("400000.00")
    assert reports.reconciliation(db, world.ctx())["reconciled"]

    # E: allocate the same receipt; no second receipt, no new ledger entry.
    journals, bank = journal_count(world), trial(world)["1121"]
    item = lambda doc: subledger.item_for_document(db, doc.id).id
    receipts.allocate(db, world.ctx(), r.id, [{"item_id": item(a), "amount": D(500000)},
                                              {"item_id": item(b), "amount": D(100000)}], ON + timedelta(days=4))
    assert journal_count(world) == journals and trial(world)["1121"] == bank
    assert [status(db, x) for x in (a, b, c)] == ["PAID", "PARTIALLY_PAID", "OPEN"]
    assert outstanding(world, b) == D("200000.00")
    assert r.receipt_date == ON + timedelta(days=2) and r.amount == D("600000.00") and r.status == "POSTED"
    p = profile(world)
    assert p["gross_outstanding"] == D("400000.00") and p["unallocated_receipts"] == 0
    assert p["net_balance"] == D("400000.00")
    # An allocation can never take an invoice below zero.
    spare = receipt(world, 500000, on=ON + timedelta(days=5))
    with pytest.raises(FinanceError, match="only 200,000.00 outstanding"):
        receipts.allocate(db, world.ctx(), spare.id, [{"item_id": item(c), "amount": D(250000)}])


def test_f_receipt_larger_than_what_is_owed(world, db):
    inv = posted_invoice(world, amount=100000, taxed=False)
    receipt(world, 150000, [(inv, 100000)])
    assert status(db, inv) == "PAID"
    p = profile(world)
    assert p["gross_outstanding"] == 0 and p["unallocated_receipts"] == D("50000.00")
    assert p["net_balance"] == D("-50000.00")                     # the customer is in credit
    assert trial(world)["1130"] == D("-50000.00")
    assert reports.reconciliation(db, world.ctx())["reconciled"]


def test_g_nothing_posts_twice(world, db):
    inv = posted_invoice(world)
    with pytest.raises(FinanceError):
        documents.post(db, world.ctx(), inv.id)
    r = receipt(world, 118000, [(inv, 118000)])
    with pytest.raises(FinanceError, match="POSTED"):
        receipts.post(db, world.ctx(), r.id)
    assert trial(world)["1121"] == D("118000.00") and journal_count(world) == 2


def test_h_reversal(world, db):
    inv = posted_invoice(world, amount=100000, taxed=False)
    r = receipt(world, 100000, [(inv, 100000)])
    assert status(db, inv) == "PAID"
    receipts.reverse(db, world.ctx(), r.id, "Cheque bounced")
    assert r.status == "REVERSED" and status(db, inv) == "OPEN" and outstanding(world, inv) == D("100000.00")
    tb = trial(world)
    assert tb["1121"] == 0 and tb["1130"] == D("100000.00")
    assert profile(world)["net_balance"] == D("100000.00")
    with pytest.raises(FinanceError, match="REVERSED"):
        receipts.reverse(db, world.ctx(), r.id, "again")


def test_i_reconciliation(world, db):
    a = posted_invoice(world, amount=100000)
    posted_invoice(world, amount=40000, taxed=False, customer=world.customer2)
    receipt(world, 50000, [(a, 50000)])
    receipt(world, 20000)                                         # on account
    receipt(world, 60000, customer=world.customer2)               # more than owed
    rec = reports.reconciliation(db, world.ctx())
    assert rec["reconciled"] and rec["differences"] == []
    assert rec["receivable"]["subledger"] == rec["receivable"]["control_account"] == D("28000.00")
    tb = ledger.trial_balance(db, world.ctx())
    assert tb["is_balanced"] and tb["difference"] == 0


def test_tax_withheld_by_the_customer(world, db):
    """The customer settles 118,000 but keeps back 5,900 as withholding tax:
    the bank gets 112,100, the tax goes to its own account, the customer is
    credited with the whole 118,000."""
    inv = posted_invoice(world)
    ctx = world.ctx()
    r = receipts.create(db, ctx, {
        "customer_id": world.customer.id, "receipt_date": ON, "payment_method_id": method(world).id,
        "amount": D("118000"), "wht_amount": D("5900"), "reference": "TRX-9",
        "allocations": [{"item_id": subledger.item_for_document(db, inv.id).id, "amount": D("118000")}]})
    receipts.post(db, ctx, r.id)
    assert by_account(world, db.get(JournalEntry, r.journal_entry_id)) == {
        "1121": (D("112100.00"), D("0")), "1185": (D("5900.00"), D("0")), "1130": (D("0"), D("118000.00"))}
    assert status(db, inv) == "PAID"
    receipts.reverse(db, ctx, r.id, "entered twice")
    tb = trial(world)
    assert tb["1121"] == 0 and tb["1185"] == 0 and tb["1130"] == D("118000.00")
    with pytest.raises(FinanceError, match="less than the amount"):
        receipts.create(db, ctx, {"customer_id": world.customer.id, "receipt_date": ON,
                                  "payment_method_id": method(world).id, "amount": D("100"),
                                  "wht_amount": D("100"), "reference": "X"})


def test_sales_by_month_and_year(client, world, db):
    """Sales on the finance dashboard come from the ledger: by month and by
    financial year, net of credit notes, with a cancelled invoice left out."""
    posted_invoice(world, amount=100000, on=date(2026, 7, 15))            # + 18,000 tax
    posted_invoice(world, amount=50000, taxed=False, on=date(2026, 7, 20))
    posted_invoice(world, amount=30000, taxed=False, on=date(2026, 8, 3))
    wrong = posted_invoice(world, amount=7000, taxed=False, on=date(2026, 8, 4))
    documents.cancel(db, world.ctx(), wrong.id, "entered by mistake")
    data = client.get("/api/v1/finance/sales-summary").json()
    year = next(y for y in data["years"] if y["name"] == "2026-27")
    months = {m["month"][:7]: m for m in year["months"]}
    assert months["2026-07"]["sales"] == 150000 and months["2026-07"]["sales_tax"] == 18000
    assert months["2026-07"]["total"] == 168000 and months["2026-07"]["invoices"] == 2
    assert year["sales"] == 180000 and year["total"] == 198000 and year["invoices"] == 3
    assert data["totals"]["sales"] == 180000


def test_ledger_shows_which_invoices_a_receipt_paid(client, world, db):
    a = posted_invoice(world, amount=3000, taxed=False)
    b = posted_invoice(world, amount=4500, taxed=False)
    receipt(world, 6000, [(a, 3000), (b, 3000)], on=ON + timedelta(days=1))
    receipt(world, 500, on=ON + timedelta(days=2))
    rows = client.get("/api/v1/finance/ledger", params={"customer_id": str(world.customer.id)}).json()["rows"]
    paid, on_account = rows[2], rows[3]
    assert paid["narration"] == f"PAYMENT RECEIVED AGAINST INVOICES {a.doc_number}||3000, {b.doc_number}||3000"
    assert paid["invoice_no"] == f"{a.doc_number}, {b.doc_number}"
    assert on_account["narration"] == "PAYMENT RECEIVED ON ACCOUNT" and on_account["invoice_no"] is None
