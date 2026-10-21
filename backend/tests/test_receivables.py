"""Finance Phase 2 — sales invoices, receipts, credit notes and AR.
Numbers follow the brief's worked examples. Everything runs in the rolled-back
test transaction against a throwaway company."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.finance import ledger, posting
from app.finance.errors import FinanceError
from app.finance.models import Account, JournalEntry
from app.receivables import documents, receipts, reports, subledger
from app.receivables.models import ARSettings, PaymentMethod, TaxCode
from app.sales.models import (
    CREDIT_NOTE, DEBIT_NOTE, QUOTATION, SALES_INVOICE, SALES_ORDER, SalesDocument, SalesDocumentLine,
)
from tests.conftest import make_user

D = Decimal
ON = date(2026, 8, 10)


# ------------------------------------------------------------ helpers

def gst(world):
    return world.db.scalar(select(TaxCode).where(TaxCode.company_id == world.company.id, TaxCode.code == "GST18"))


def method(world, code="BANK_TRANSFER"):
    return world.db.scalar(select(PaymentMethod).where(PaymentMethod.company_id == world.company.id,
                                                       PaymentMethod.code == code))


def order(world, qty=100, price=1000, on=date(2026, 8, 1), status="Posted", customer=None):
    doc = SalesDocument(company_id=world.company.id, doc_type=SALES_ORDER, doc_number=f"SO-{uuid.uuid4().hex[:6]}",
                        doc_date=on, customer_id=(customer or world.customer).id, status=status, currency="PKR")
    doc.lines = [SalesDocumentLine(line_number=1, description="Bearing 6205", quantity=D(qty),
                                   delivered_quantity=D(qty), unit_price=D(price), tax_percent=D(18))]
    world.db.add(doc)
    world.db.flush()
    return doc


def invoice_data(world, *, amount=100000, taxed=True, customer=None, on=ON, **extra):
    return {"customer_id": (customer or world.customer).id, "doc_date": on,
            "lines": [{"description": "Services", "quantity": 1, "unit_price": amount,
                       "tax_code_id": gst(world).id if taxed else None}], **extra}


def posted_invoice(world, **kw):
    ctx = world.ctx()
    doc = documents.create(world.db, ctx, SALES_INVOICE, invoice_data(world, **kw))
    documents.confirm(world.db, ctx, doc.id)
    return documents.post(world.db, ctx, doc.id)


def receipt(world, amount, allocations=(), customer=None, on=ON, post=True, code="BANK_TRANSFER"):
    ctx = world.ctx()
    r = receipts.create(world.db, ctx, {
        "customer_id": (customer or world.customer).id, "receipt_date": on,
        "payment_method_id": method(world, code).id, "amount": D(str(amount)),
        "reference": "TRX-1", "allocations": [
            {"item_id": subledger.item_for_document(world.db, inv.id).id, "amount": D(str(a))}
            for inv, a in allocations]})
    return receipts.post(world.db, ctx, r.id) if post else r


def by_account(world, journal):
    out = {}
    for line in journal.lines:
        code = world.db.get(Account, line.account_id).code
        dr, cr = out.get(code, (D(0), D(0)))
        out[code] = (dr + line.base_debit, cr + line.base_credit)
    return out


def outstanding(world, doc):
    return documents.payment_state(world.db, doc)["outstanding"]


# ------------------------------------------------------------ invoices 1-8

def test_1_create_invoice(world, db):
    doc = documents.create(db, world.ctx(), SALES_INVOICE, invoice_data(world))
    assert doc.status == "DRAFT" and doc.doc_number == "SI-000001"
    assert (doc.excluding_tax_value, doc.sales_tax_value, doc.net_receivable) == (D("100000.00"), D("18000.00"), D("118000.00"))
    assert doc.due_date == ON  # default term: due immediately
    assert doc.financial_year_id == world.fy.id


def test_2_draft_does_not_touch_ledger(world, db):
    doc = documents.create(db, world.ctx(), SALES_INVOICE, invoice_data(world))
    documents.confirm(db, world.ctx(), doc.id)
    db.flush()
    assert db.scalar(select(JournalEntry.id).where(JournalEntry.company_id == world.company.id).limit(1)) is None
    assert ledger.trial_balance(db, world.ctx())["rows"] == []
    with pytest.raises(FinanceError, match="must be confirmed"):
        documents.post(db, world.ctx(), documents.create(db, world.ctx(), SALES_INVOICE, invoice_data(world)).id)


def test_3_to_5_posting_creates_correct_balanced_journal(world, db):
    """Example 2 — credit sale."""
    doc = posted_invoice(world)
    journal = db.get(JournalEntry, doc.journal_entry_id)
    assert journal.status == "POSTED" and journal.event_code == "SALES_INVOICE_POSTED"
    assert journal.document_type == "SALES_INVOICE" and journal.document_id == doc.id
    lines = by_account(world, journal)
    assert lines["1130"] == (D("118000.00"), D("0"))
    assert lines["4100"] == (D("0"), D("100000.00"))
    assert lines["2130"] == (D("0"), D("18000.00"))
    assert journal.total_debit == journal.total_credit == D("118000.00")
    revenue = next(l for l in journal.lines if db.get(Account, l.account_id).code == "4100")
    assert revenue.customer_id == world.customer.id          # sales by customer come from the ledger
    assert doc.status == "POSTED" and documents.payment_state(db, doc)["payment_status"] == "OPEN"


def test_example_1_cash_sale(world, db):
    cash = world.account("1110")
    doc = posted_invoice(world, is_cash_sale=True, cash_account_id=cash.id)
    lines = by_account(world, db.get(JournalEntry, doc.journal_entry_id))
    assert lines["1110"] == (D("118000.00"), D("0"))
    assert "1130" not in lines
    assert documents.payment_state(db, doc)["payment_status"] == "PAID"
    assert subledger.item_for_document(db, doc.id) is None


def test_6_duplicate_invoice_number_rejected(world, db):
    first = posted_invoice(world)
    second = documents.create(db, world.ctx(), SALES_INVOICE, invoice_data(world))
    db.flush()
    second.doc_number = first.doc_number
    with pytest.raises(DBAPIError, match="uq_sales_doc_number_fy"):
        db.flush()


def test_7_posted_invoice_cannot_be_edited(world, db):
    doc = posted_invoice(world)
    with pytest.raises(FinanceError, match="only a draft can be edited"):
        documents.update(db, world.ctx(), doc.id, invoice_data(world, amount=5))
    with pytest.raises(DBAPIError, match="posted and cannot be edited"), db.begin_nested():
        db.execute(text("update sales_documents set net_receivable = 1 where id = :id"), {"id": doc.id})
    with pytest.raises(DBAPIError, match="cannot be changed"), db.begin_nested():
        db.execute(text("update sales_document_lines set quantity = 9 where document_id = :id"), {"id": doc.id})


def test_8_posted_invoice_cannot_be_deleted(world, db):
    doc = posted_invoice(world)
    with pytest.raises(DBAPIError, match="cannot be deleted"), db.begin_nested():
        db.execute(text("delete from sales_documents where id = :id"), {"id": doc.id})
    with pytest.raises(DBAPIError, match="never deleted"), db.begin_nested():
        db.execute(text("delete from ar_items where sales_document_id = :id"), {"id": doc.id})


def test_invoice_journal_cannot_be_reversed_from_journal_screen(world, db):
    doc = posted_invoice(world)
    with pytest.raises(FinanceError, match="cancel or reverse that document"):
        posting.reverse(db, db.get(JournalEntry, doc.journal_entry_id), ON, "wrong", world.audit)


def test_cancel_posted_invoice_reverses_ledger(world, db):
    doc = posted_invoice(world)
    documents.cancel(db, world.ctx(), doc.id, "Raised against the wrong customer")
    assert doc.status == "CANCELLED" and doc.cancel_journal_id
    assert all(r["balance"] == 0 for r in ledger.trial_balance(db, world.ctx())["rows"])
    assert db.get(JournalEntry, doc.journal_entry_id).status == "REVERSED"


# ------------------------------------------------------------ sales order 9-12

def test_9_invoice_from_sales_order(world, db):
    so = order(world)
    draft = documents.draft_from_order(db, world.ctx(), so.id)
    assert draft["lines"][0]["quantity"] == D(100) and draft["customer_id"] == str(world.customer.id)
    draft["lines"][0]["tax_code_id"] = gst(world).id
    doc = documents.create(db, world.ctx(), SALES_INVOICE, {**draft, "doc_date": ON})
    assert doc.source_document_id == so.id and doc.lines[0].source_line_id == so.lines[0].id
    assert doc.net_receivable == D("118000.00")


def _invoice_qty(world, so, qty):
    draft = documents.draft_from_order(world.db, world.ctx(), so.id)
    draft["lines"][0].update(quantity=D(qty), tax_code_id=gst(world).id)
    return documents.create(world.db, world.ctx(), SALES_INVOICE, {**draft, "doc_date": ON})


def test_10_partial_invoicing(world, db):
    so = order(world)
    _invoice_qty(world, so, 40)
    progress = documents.order_progress(db, so)[0]
    assert (progress["ordered"], progress["invoiced"], progress["remaining"]) == (D(100), D(40), D(60))
    assert documents.draft_from_order(db, world.ctx(), so.id)["lines"][0]["quantity"] == D(60)


def test_11_over_invoicing_rejected(world, db):
    so = order(world)
    _invoice_qty(world, so, 40)
    with pytest.raises(FinanceError, match="at most 60.00 can be invoiced — not 70.00"):
        _invoice_qty(world, so, 70)


def test_12_fully_invoiced_order_refused(world, db):
    so = order(world)
    _invoice_qty(world, so, 100)
    with pytest.raises(FinanceError, match="fully invoiced"):
        documents.draft_from_order(db, world.ctx(), so.id)


def test_cancelled_invoice_frees_the_quantity(world, db):
    so = order(world)
    doc = _invoice_qty(world, so, 100)
    documents.cancel(db, world.ctx(), doc.id, "wrong quantity")
    assert documents.order_progress(db, so)[0]["remaining"] == D(100)


def test_historical_and_draft_orders_cannot_be_invoiced(world, db):
    old = order(world, on=date(2025, 3, 1))
    with pytest.raises(FinanceError, match="before invoicing started"):
        documents.draft_from_order(db, world.ctx(), old.id)
    draft = order(world, status="Draft")
    with pytest.raises(FinanceError, match="only a posted"):
        documents.draft_from_order(db, world.ctx(), draft.id)


def test_quotation_itself_never_posts_and_direct_invoice_is_off(world, db):
    q = SalesDocument(company_id=world.company.id, doc_type=QUOTATION, doc_number="Q-1", doc_date=ON,
                      customer_id=world.customer.id, status="Approved")
    db.add(q)
    db.flush()
    with pytest.raises(FinanceError, match="switched off"):
        documents.create(db, world.ctx(), SALES_INVOICE, invoice_data(world, quotation_id=q.id))
    assert db.scalar(select(JournalEntry.id).where(JournalEntry.document_id == q.id)) is None


def test_invoice_from_gate_pass(world, db):
    """Delivery → invoice: the invoice keeps the pass reference and cannot
    bill more than was dispatched. It moves no stock of its own."""
    from app.gatepass.models import GatePass, GatePassLine
    from app.inventory.stock import StockLedgerEntry
    gp = GatePass(company_id=world.company.id, pass_type="outward", doc_number="OGP-T1", doc_date=ON,
                  party_id=world.customer.id, status="Approved", is_approved=True)
    gp.lines = [GatePassLine(line_number=1, description="Pump", quantity=D(5), unit_price=D(2000), tax_percent=D(18))]
    db.add(gp)
    db.flush()
    stock_before = db.scalar(select(text("count(*)")).select_from(StockLedgerEntry))
    draft = documents.draft_from_gate_pass(db, world.ctx(), gp.id)
    assert draft["lines"][0]["quantity"] == D(5)
    draft["lines"][0]["quantity"] = D(6)
    with pytest.raises(FinanceError, match="left to invoice"):
        documents.create(db, world.ctx(), SALES_INVOICE, {**draft, "doc_date": ON})
    draft["lines"][0]["quantity"] = D(5)
    doc = documents.create(db, world.ctx(), SALES_INVOICE, {**draft, "doc_date": ON})
    documents.confirm(db, world.ctx(), doc.id)
    documents.post(db, world.ctx(), doc.id)
    assert doc.gate_pass_id == gp.id and doc.net_receivable == D("11800.00")
    assert db.scalar(select(text("count(*)")).select_from(StockLedgerEntry)) == stock_before
    with pytest.raises(FinanceError, match="fully invoiced"):
        documents.draft_from_gate_pass(db, world.ctx(), gp.id)


# ------------------------------------------------------------ receipts 13-19

def test_13_14_receipt_create_and_post(world, db):
    """Example 3 — customer pays the full invoice into the bank."""
    inv = posted_invoice(world)
    r = receipt(world, 118000, [(inv, 118000)], post=False)
    assert r.status == "DRAFT" and r.receipt_number == "BRV-000001"
    receipts.post(db, world.ctx(), r.id)
    lines = by_account(world, db.get(JournalEntry, r.journal_entry_id))
    assert lines["1121"] == (D("118000.00"), D("0"))
    assert lines["1130"] == (D("0"), D("118000.00"))
    assert documents.payment_state(db, inv)["payment_status"] == "PAID"


def test_15_16_partial_payment(world, db):
    """Example 4 — 50,000 against 118,000 leaves 68,000."""
    inv = posted_invoice(world)
    r = receipt(world, 50000, [(inv, 50000)])
    assert by_account(world, db.get(JournalEntry, r.journal_entry_id))["1130"] == (D("0"), D("50000.00"))
    assert outstanding(world, inv) == D("68000.00")
    assert documents.payment_state(db, inv)["payment_status"] == "PARTIALLY_PAID"


def test_17_multiple_invoice_allocation(world, db):
    a = posted_invoice(world, amount=100000, taxed=False)
    b = posted_invoice(world, amount=50000, taxed=False)
    receipt(world, 120000, [(a, 100000), (b, 20000)])
    assert outstanding(world, a) == 0 and outstanding(world, b) == D("30000.00")


def test_18_on_account_receipt_then_allocation(world, db):
    """Example 5 — money first, invoice later. The receipt credits the
    customer's receivable at once; allocating it later posts nothing more."""
    r = receipt(world, 50000)
    lines = by_account(world, db.get(JournalEntry, r.journal_entry_id))
    assert lines["1121"] == (D("50000.00"), D("0")) and lines["1130"] == (D("0"), D("50000.00"))
    inv = posted_invoice(world, amount=50000, taxed=False, on=ON + timedelta(days=5))
    journals = lambda: db.scalar(select(func.count()).select_from(JournalEntry).where(
        JournalEntry.company_id == world.company.id))
    before = journals()
    receipts.allocate(db, world.ctx(), r.id, [{"item_id": subledger.item_for_document(db, inv.id).id,
                                               "amount": D(50000)}], ON + timedelta(days=5))
    assert journals() == before
    assert outstanding(world, inv) == 0
    tb = {r_["account_code"]: r_ for r_ in ledger.trial_balance(db, world.ctx())["rows"]}
    assert "2160" not in tb and tb["1130"]["balance"] == 0


def test_over_allocation_rejected(world, db):
    inv = posted_invoice(world, amount=10000, taxed=False)
    with pytest.raises(FinanceError, match="only 10,000.00 outstanding"):
        receipt(world, 20000, [(inv, 15000)])


def test_19_receipt_reversal_restores_everything(world, db):
    a = posted_invoice(world, amount=60000, taxed=False)
    b = posted_invoice(world, amount=40000, taxed=False)
    r = receipt(world, 100000, [(a, 60000)])
    receipts.allocate(db, world.ctx(), r.id, [{"item_id": subledger.item_for_document(db, b.id).id,
                                               "amount": D(40000)}])
    receipts.reverse(db, world.ctx(), r.id, "Cheque bounced")
    assert r.status == "REVERSED"
    assert outstanding(world, a) == D("60000.00") and outstanding(world, b) == D("40000.00")
    tb = {row["account_code"]: row["balance"] for row in ledger.trial_balance(db, world.ctx())["rows"]}
    assert tb["1121"] == 0 and "2160" not in tb and tb["1130"] == D("100000.00")
    assert reports.reconciliation(db, world.ctx())["reconciled"]


def test_unallocate_leaves_the_money_on_the_customers_account(world, db):
    inv = posted_invoice(world, amount=30000, taxed=False)
    r = receipt(world, 30000, [(inv, 30000)])
    allocation = subledger.active_allocations(db, subledger.item_for_document(db, inv.id).id)[0]
    subledger.unallocate(db, world.audit, world.company.id, allocation.id, "Allocated to the wrong invoice")
    assert outstanding(world, inv) == D("30000.00")
    tb = {row["account_code"]: row["balance"] for row in ledger.trial_balance(db, world.ctx())["rows"]}
    # The invoice is unpaid again, the customer still has the money to their credit.
    assert "2160" not in tb and tb["1130"] == 0
    assert r.status == "POSTED" and receipts.summary(db, r)["unallocated"] == D("30000.00")


# ------------------------------------------------------------ credit notes 20-24

def test_20_to_24_credit_note(world, db):
    inv = posted_invoice(world)
    before = db.execute(text("select net_receivable, status, journal_entry_id from sales_documents where id=:id"),
                        {"id": inv.id}).one()
    draft = documents.draft_from_invoice(db, world.ctx(), inv.id, CREDIT_NOTE)
    draft["lines"][0]["unit_price"] = D(25000)          # price correction on a quarter of the value
    cn = documents.create(db, world.ctx(), CREDIT_NOTE, {**draft, "doc_date": ON, "reason_code": "PRICE_CORRECTION",
                                                         "reason": "Agreed discount"})
    assert cn.doc_number == "CN-000001" and cn.source_document_id == inv.id
    documents.confirm(db, world.ctx(), cn.id)
    documents.post(db, world.ctx(), cn.id)
    lines = by_account(world, db.get(JournalEntry, cn.journal_entry_id))
    assert lines["4900"] == (D("25000.00"), D("0"))
    assert lines["2130"] == (D("4500.00"), D("0"))
    assert lines["1130"] == (D("0"), D("29500.00"))
    after = db.execute(text("select net_receivable, status, journal_entry_id from sales_documents where id=:id"),
                       {"id": inv.id}).one()
    assert tuple(before) == tuple(after)                  # the invoice itself is untouched
    assert outstanding(world, inv) == D("88500.00")       # 118,000 − 29,500
    assert documents.payment_state(db, cn)["payment_status"] == "APPLIED"


def test_credit_note_quantity_limited_to_invoice(world, db):
    so = order(world, qty=10, price=100)
    inv = _invoice_qty(world, so, 10)
    documents.confirm(db, world.ctx(), inv.id)
    documents.post(db, world.ctx(), inv.id)
    draft = documents.draft_from_invoice(db, world.ctx(), inv.id, CREDIT_NOTE)
    draft["lines"][0]["quantity"] = D(11)
    with pytest.raises(FinanceError, match="at most 10.00 can be credited"):
        documents.create(db, world.ctx(), CREDIT_NOTE, {**draft, "doc_date": ON})


def test_credit_note_reversal(world, db):
    inv = posted_invoice(world, amount=1000, taxed=False)
    draft = documents.draft_from_invoice(db, world.ctx(), inv.id, CREDIT_NOTE)
    cn = documents.create(db, world.ctx(), CREDIT_NOTE, {**draft, "doc_date": ON})
    documents.confirm(db, world.ctx(), cn.id)
    documents.post(db, world.ctx(), cn.id)
    assert outstanding(world, inv) == 0
    documents.cancel(db, world.ctx(), cn.id, "Issued in error")
    assert outstanding(world, inv) == D("1000.00")
    assert reports.reconciliation(db, world.ctx())["reconciled"]


def test_debit_note(world, db):
    inv = posted_invoice(world, amount=1000, taxed=False)
    dn = documents.create(db, world.ctx(), DEBIT_NOTE, invoice_data(world, amount=200, source_document_id=inv.id))
    documents.confirm(db, world.ctx(), dn.id)
    documents.post(db, world.ctx(), dn.id)
    lines = by_account(world, db.get(JournalEntry, dn.journal_entry_id))
    assert lines["1130"] == (D("236.00"), D("0")) and lines["4100"] == (D("0"), D("200.00"))
    assert reports.customer_profile(db, world.ctx(), world.customer.id)["receivable"] == D("1236.00")


def test_invoice_with_allocations_cannot_be_cancelled(world, db):
    inv = posted_invoice(world, amount=500, taxed=False)
    receipt(world, 500, [(inv, 500)])
    with pytest.raises(FinanceError, match="Unallocate them first"):
        documents.cancel(db, world.ctx(), inv.id, "wrong")


# ------------------------------------------------------------ AR 25-29

def _scenario(world):
    a = posted_invoice(world, amount=100000, taxed=False, on=date(2026, 7, 5))      # due 5 Jul
    b = posted_invoice(world, amount=50000, taxed=False, on=date(2026, 8, 20))      # due 20 Aug
    receipt(world, 30000, [(a, 30000)], on=date(2026, 8, 25))
    receipt(world, 5000, on=date(2026, 8, 26))                                       # on account
    return a, b


def test_25_customer_balance(world, db):
    _scenario(world)
    p = reports.customer_profile(db, world.ctx(), world.customer.id)
    assert p["invoiced"] == D("150000.00") and p["receipts"] == D("35000.00")
    assert p["gross_outstanding"] == D("120000.00") and p["unallocated_receipts"] == D("5000.00")
    assert p["receivable"] == D("115000.00") and p["advances"] == 0
    assert p["net_balance"] == D("115000.00")
    assert p["ledger_receivable"] == p["receivable"] and p["ledger_advances"] == p["advances"]


def test_26_customer_statement(world, db):
    _scenario(world)
    s = reports.statement(db, world.ctx(), world.customer.id, date(2026, 8, 1), date(2026, 8, 31))
    assert s["opening_balance"] == D("100000.00")
    assert [(r["debit"], r["credit"]) for r in s["rows"]] == [
        (D("50000.00"), D("0")), (D("0"), D("30000.00")), (D("0"), D("5000.00"))]
    assert s["closing_balance"] == D("115000.00")
    assert all(r["document_id"] for r in s["rows"])      # drill-down to the source document


def test_27_aging(world, db):
    a, b = _scenario(world)
    aging = reports.aging(db, world.ctx(), as_of=date(2026, 9, 30))
    row = aging["customers"][0]
    labels = aging["labels"]
    assert labels[:3] == ["Current", "1–30 days", "31–60 days"]
    # A: 70,000 open, due 5 Jul → 87 days; B: 50,000, due 20 Aug → 41 days.
    # The 5,000 received on account comes off the oldest invoice, so the
    # buckets add up to the customer's ledger balance.
    assert row["buckets"][labels.index("61–90 days")] == D("65000.00")
    assert row["buckets"][labels.index("31–60 days")] == D("50000.00")
    assert row["on_account"] == D("5000.00") and row["credit_balance"] == 0
    assert row["total_due"] == row["net"] == D("115000.00")
    assert {i["document_number"]: i["outstanding"] for i in aging["invoices"]} == {
        a.doc_number: D("65000.00"), b.doc_number: D("50000.00")}


def test_28_29_reconciliation_control_equals_subledger(world, db):
    _scenario(world)
    other = posted_invoice(world, amount=7000, customer=world.customer2)
    documents.cancel(db, world.ctx(), other.id, "test")
    r = reports.reconciliation(db, world.ctx())
    assert r["reconciled"] and r["differences"] == []
    assert r["receivable"]["subledger"] == r["receivable"]["control_account"] == D("115000.00")
    assert r["advances"]["subledger"] == r["advances"]["control_account"] == 0
    # As at a past date too: on 21 Aug customer 2's invoice (8,260) was not yet
    # cancelled — its reversal is dated today — so it still counts then.
    past = reports.reconciliation(db, world.ctx(), as_of=date(2026, 8, 21))
    assert past["reconciled"] and past["receivable"]["control_account"] == D("158260.00")


def test_opening_ar_items_can_be_paid(world, db):
    from app.finance import opening
    ctx = world.ctx()
    batch = opening.create_batch(db, ctx, {"financial_year_id": world.fy.id, "cutover_date": date(2026, 7, 1)})
    opening.import_rows(db, ctx, batch, "GL", [{"Account Code": "1130", "Debit": 40000},
                                               {"Account Code": "2160", "Credit": 10000},
                                               {"Account Code": "3100", "Credit": 30000}],
                        file_name="gl", file_hash="g")
    opening.import_rows(db, ctx, batch, "AR", [
        {"Customer Code": "C001", "Invoice Reference": "OLD-1", "Outstanding Amount": 40000},
        {"Customer Code": "C002", "Invoice Reference": "ADV-1", "Outstanding Amount": -10000,
         "Account Code": "2160"}], file_name="ar", file_hash="a")
    assert opening.validate(db, ctx, batch.id)["passed"]
    opening.approve(db, ctx, batch.id)
    opening.post(db, ctx, batch.id)
    old = next(i for i in subledger.items_for(db, world.company.id) if i.document_number == "OLD-1")
    r = receipts.create(db, ctx, {"customer_id": world.customer.id, "receipt_date": ON,
                                  "payment_method_id": method(world).id, "amount": D(40000), "reference": "x",
                                  "allocations": [{"item_id": old.id, "amount": D(40000)}]})
    receipts.post(db, ctx, r.id)
    assert subledger.open_amounts(db, [old])[old.id] == 0
    assert reports.reconciliation(db, ctx)["reconciled"]
    assert reports.customer_profile(db, ctx, world.customer2.id)["advances"] == D("10000.00")


# ------------------------------------------------------------ credit limit, tax, currency

def test_credit_limit_policies(world, db):
    world.customer.credit_limit = D(100000)
    s = db.scalar(select(ARSettings).where(ARSettings.company_id == world.company.id))
    ctx = world.ctx()
    doc = documents.create(db, ctx, SALES_INVOICE, invoice_data(world))       # 118,000 > 100,000
    s.credit_limit_policy = "BLOCK"
    with pytest.raises(FinanceError, match="blocks"):
        documents.confirm(db, ctx, doc.id)
    s.credit_limit_policy = "APPROVAL"
    documents.confirm(db, ctx, doc.id)
    assert doc.credit_check_status == "APPROVAL_REQUIRED"
    with pytest.raises(FinanceError, match="credit approval"):
        documents.post(db, ctx, doc.id)
    documents.approve_credit(db, ctx, doc.id, "Owner approved")
    documents.post(db, ctx, doc.id)
    s.credit_limit_policy = "WARN"
    doc2 = documents.create(db, ctx, SALES_INVOICE, invoice_data(world, amount=10))
    _, check = documents.confirm(db, ctx, doc2.id)
    assert doc2.credit_check_status == "WARNING" and check["current_outstanding"] == D("118000.00")


def test_tax_inclusive_and_exempt(world, db):
    exempt = db.scalar(select(TaxCode).where(TaxCode.company_id == world.company.id, TaxCode.code == "EXEMPT"))
    doc = documents.create(db, world.ctx(), SALES_INVOICE, {
        "customer_id": world.customer.id, "doc_date": ON, "tax_inclusive": True,
        "lines": [{"description": "Retail", "quantity": 1, "unit_price": 118000, "tax_code_id": gst(world).id},
                  {"description": "Exempt", "quantity": 1, "unit_price": 500, "tax_code_id": exempt.id}]})
    assert doc.lines[0].taxable_amount == D("100000.00") and doc.lines[0].tax_amount == D("18000.00")
    assert doc.net_receivable == D("118500.00")


def test_foreign_currency_invoice_keeps_both_amounts(world, db):
    doc = posted_invoice(world, amount=1000, taxed=False, currency="USD", exchange_rate=D("278.4567"))
    journal = db.get(JournalEntry, doc.journal_entry_id)
    ar = next(l for l in journal.lines if db.get(Account, l.account_id).code == "1130")
    assert ar.debit == D("1000.00") and ar.currency == "USD" and ar.base_debit == D("278456.70")
    assert journal.total_debit == journal.total_credit
    item = subledger.item_for_document(db, doc.id)
    assert item.amount == D("1000.00") and item.amount_base == D("278456.70")
    assert reports.reconciliation(db, world.ctx())["reconciled"]


def test_inactive_customer_refused(world, db):
    world.customer.is_active = False
    db.flush()
    with pytest.raises(FinanceError, match="inactive"):
        documents.create(db, world.ctx(), SALES_INVOICE, invoice_data(world))


def test_audit_trail(world, db):
    inv = posted_invoice(world, amount=100, taxed=False)
    r = receipt(world, 100, [(inv, 100)])
    receipts.reverse(db, world.ctx(), r.id, "test")
    db.flush()
    actions = {a for (a,) in db.execute(text("select action from audit_logs where company_id = :c"),
                                        {"c": world.company.id})}
    assert {"create", "confirm", "post", "allocate", "unallocate", "reverse"} <= actions


# ------------------------------------------------------------ API & permissions 30-37

def test_api_flow_and_permissions(client, world, db):
    body = {"customer_id": str(world.customer.id), "doc_date": str(ON),
            "lines": [{"description": "API line", "quantity": "2", "unit_price": "500",
                       "tax_code_id": str(gst(world).id)}]}
    created = client.post("/api/v1/sales/invoices", json=body)
    assert created.status_code == 201, created.text
    inv_id = created.json()["id"]
    assert client.post(f"/api/v1/sales/invoices/{inv_id}/confirm").status_code == 200

    clerk = make_user(db, codes=["sales.invoice.view", "sales.invoice.create", "ar.view", "ar.receipt.create"],
                      company=world.company)
    client.state["user"] = clerk
    denied = client.post(f"/api/v1/sales/invoices/{inv_id}/post")
    assert denied.status_code == 403 and "sales.invoice.post" in denied.json()["detail"]      # 30

    client.state["user"] = world.admin
    assert client.post(f"/api/v1/sales/invoices/{inv_id}/post").json()["status"] == "POSTED"
    item_id = client.get(f"/api/v1/ar/customers/{world.customer.id}/open-items").json()[0]["item_id"]

    client.state["user"] = clerk
    rec = client.post("/api/v1/ar/receipts", json={
        "customer_id": str(world.customer.id), "receipt_date": str(ON), "amount": "1180",
        "payment_method_id": str(method(world).id), "reference": "API",
        "allocations": [{"item_id": item_id, "amount": "1180"}]})
    assert rec.status_code == 201, rec.text
    rid = rec.json()["id"]
    assert client.post(f"/api/v1/ar/receipts/{rid}/post").status_code == 403                  # 31

    client.state["user"] = world.admin
    assert client.post(f"/api/v1/ar/receipts/{rid}/post").json()["allocation_status"] == "FULLY_ALLOCATED"
    client.state["user"] = clerk
    assert client.post(f"/api/v1/ar/receipts/{rid}/reverse", json={"reason": "x"}).status_code == 403  # 32

    client.state["user"] = world.admin
    for path in ("/api/v1/ar/aging", "/api/v1/ar/balances", "/api/v1/ar/reconciliation", "/api/v1/ar/dashboard",
                 "/api/v1/ar/sales-summary", "/api/v1/ar/registers/invoices", "/api/v1/ar/registers/receipts",
                 f"/api/v1/ar/statement?customer_id={world.customer.id}"):
        assert client.get(path).status_code == 200, path
    for report in ("invoices", "receipts", "aging", "balances", "reconciliation", "sales-summary"):
        for fmt in ("xlsx", "pdf", "csv"):
            assert client.get(f"/api/v1/ar/export/{report}?format={fmt}").status_code == 200, (report, fmt)
    assert client.get(f"/api/v1/ar/receipts/{rid}/voucher.pdf").status_code == 200
    assert client.get(f"/api/v1/documents/sales/{inv_id}/sales_tax_invoice.pdf").status_code == 200


def test_33_to_36_existing_modules_still_respond(client):
    client.headers.pop("X-Company-Id", None)
    for path in ("/api/v1/partners?page_size=5", "/api/v1/sales/quotations?page_size=5",
                 "/api/v1/sales/orders?page_size=5", "/api/v1/inventory/items?page_size=5",
                 "/api/v1/finance/trial-balance"):
        assert client.get(path).status_code == 200, path


def test_customers_appear_under_the_receivable_account(client, world, db):
    """The chart of accounts lists each customer under Accounts Receivable
    with the balance its postings add up to."""
    posted_invoice(world)                                        # 118,000 to world.customer
    posted_invoice(world, amount=50000, taxed=False, customer=world.customer2)
    receipt(world, 18000)                                        # world.customer pays on account

    accounts = client.get("/api/v1/finance/accounts?with_balances=true").json()
    receivable = next(a for a in accounts if a["control_type"] == "RECEIVABLE")
    payable = next(a for a in accounts if a["control_type"] == "PAYABLE")
    assert receivable["subledger"] == {"kind": "customer", "count": 2}
    assert payable["subledger"] == {"kind": "supplier", "count": 1}
    assert next(a for a in accounts if a["code"] == "1110")["subledger"] is None      # cash has no parties

    parties = client.get(f"/api/v1/finance/accounts/{receivable['id']}/parties").json()
    balances = {p["code"]: p["balance"] for p in parties["items"]}
    # The on-account receipt comes straight off that customer's receivable.
    assert parties["kind"] == "customer" and balances == {"C001": 100000, "C002": 50000}
    # The customers add up to the control account: nothing is posted without one.
    assert parties["total"] == receivable["balance"] == 150000 and parties["unassigned"] == 0
    advances = next(a for a in accounts if a["control_type"] == "CUSTOMER_ADVANCE")
    held = client.get(f"/api/v1/finance/accounts/{advances['id']}/parties").json()
    assert {p["code"]: p["balance"] for p in held["items"]} == {"C001": 0, "C002": 0}

    suppliers = client.get(f"/api/v1/finance/accounts/{payable['id']}/parties").json()
    assert [(p["code"], p["balance"]) for p in suppliers["items"]] == [("S001", 0)]
    cash = next(a for a in accounts if a["code"] == "1110")
    assert client.get(f"/api/v1/finance/accounts/{cash['id']}/parties").json()["items"] == []


def test_general_ledger_for_one_customer(client, world, db):
    """The general ledger can be read for a customer: everything posted
    against them, across accounts, and nothing posted against anyone else."""
    posted_invoice(world)                                        # 118,000 to world.customer
    posted_invoice(world, amount=50000, taxed=False, customer=world.customer2)
    receipt(world, 18000)                                        # on account

    listed = {p["code"]: p for p in client.get("/api/v1/finance/ledger/parties").json()}
    assert listed["C001"]["balance"] == 100000 and listed["C002"]["balance"] == 50000
    assert listed["S001"]["kind"] == "supplier" and listed["S001"]["balance"] == 0

    gl = client.get("/api/v1/finance/ledger", params={"customer_id": str(world.customer.id)}).json()
    assert gl["account"] is None and gl["party"]["code"] == "C001"
    assert [(r["account_code"], r["debit"], r["credit"]) for r in gl["rows"]] == [
        ("1130", 118000, 0), ("1130", 0, 18000)]
    assert gl["closing_balance"] == 100000 and gl["rows"][-1]["running_balance"] == 100000

    # Narrowed to one account as well.
    receivable = world.account("1130")
    one = client.get("/api/v1/finance/ledger",
                     params={"customer_id": str(world.customer.id), "account_id": str(receivable.id)}).json()
    assert one["account"]["code"] == "1130" and one["closing_balance"] == 100000
    # The bank line of the receipt does not name the customer, but it is theirs.
    bank = client.get("/api/v1/finance/ledger",
                      params={"customer_id": str(world.customer.id), "account_id": str(world.account("1121").id)}).json()
    assert [(r["debit"], r["credit"]) for r in bank["rows"]] == [(18000, 0)]
    other = client.get("/api/v1/finance/ledger",
                       params={"customer_id": str(world.customer2.id), "account_id": str(world.account("1121").id)}).json()
    assert other["rows"] == []
    assert client.get("/api/v1/finance/ledger").status_code == 400
    export = client.get("/api/v1/finance/ledger/export",
                        params={"customer_id": str(world.customer.id), "format": "csv"})
    assert export.status_code == 200
    header = next(line for line in export.text.splitlines() if "Voucher No" in line)
    assert [c.strip('"﻿') for c in header.split(",")] ==["Voucher No", "Invoice No", "Date", "Journal", "Narration", "Cheque No / Ref No",
                                 "Cheque Date", "Debit", "Credit", "Balance"]


def test_aging_reads_invoices_from_an_old_narration():
    known = {"202510231": 1, "202510153": 1, "202510021": 1, "202510081": 1, "2025021721": 1}
    text = "PAYMENT RECEIVED AGAINST INVOICES 202510231||34680202510153||34680202510021||28680202510081||28680"
    assert reports.invoices_named(text, known) == [
        ("202510231", D("34680")), ("202510153", D("34680")), ("202510021", D("28680")), ("202510081", D("28680"))]
    assert reports.invoices_named("OROX CUTTER PARTS", known) == []
    assert reports.invoices_named(None, known) == []
    assert reports.invoices_named("against invoice no# 202510153 and 202510021", known) == [("202510153", None), ("202510021", None)]


def test_new_customer_gets_the_next_code_and_is_usable_everywhere(client, world, db):
    code = client.get("/api/v1/partners/next-code?role=customer").json()["code"]
    assert code.startswith("111112") and code[6:].isdigit()
    made = client.post("/api/v1/partners", json={"code": code, "name": "Uzair Traders"})
    assert made.status_code == 201
    following = client.get("/api/v1/partners/next-code?role=customer").json()["code"]
    assert int(following[6:]) == int(code[6:]) + 1
    # The same name again is refused, whatever its case or spacing.
    again = client.post("/api/v1/partners", json={"code": following, "name": "  uzair traders "})
    assert again.status_code == 400 and "already exists" in again.json()["detail"]
    # Customer pickers across the system read this list.
    found = client.get("/api/v1/partners", params={"role": "customer", "search": "Uzair Traders"}).json()["items"]
    assert [p["code"] for p in found] == [code]

def test_posting_a_sales_order_bills_the_customer_and_cancelling_reverses_it(client, db):
    """A sales order entered here reaches the customer's ledger when it is
    posted, keeps its figures while it is there, and leaves it when cancelled."""
    from app.finance.models import JournalEntry
    from app.inventory.router import active_company_id
    from app.partners.models import BusinessPartner
    from app.receivables.models import ARItem
    company_id = active_company_id(db)
    customer = BusinessPartner(company_id=company_id, code=f"T-{uuid.uuid4().hex[:8]}", name="Ledger Test Customer",
                               is_customer=True, is_supplier=False)
    db.add(customer)
    db.flush()
    body = {"doc_date": "2026-10-14", "customer_id": str(customer.id), "status": "Draft", "with_sales_tax": False,
            "lines": [{"description": "Plotter service", "quantity": "1", "unit_price": "7000"}]}
    made = client.post("/api/v1/sales/orders", json=body)
    assert made.status_code == 201, made.text
    order_id = made.json()["id"]
    order = db.get(SalesDocument, uuid.UUID(order_id))
    assert order.journal_entry_id is None                      # a draft is not billed

    posted = client.put(f"/api/v1/sales/orders/{order_id}", json={**body, "status": "Posted"})
    assert posted.status_code == 200, posted.text
    db.refresh(order)
    journal = db.get(JournalEntry, order.journal_entry_id)
    assert journal is not None and journal.status == "POSTED" and journal.total_debit == D("7000.00")
    item = db.scalar(select(ARItem).where(ARItem.sales_document_id == order.id))
    assert item.status == "OPEN" and item.amount == D("7000.00")

    # Its amount cannot change under the ledger entry.
    changed = client.put(f"/api/v1/sales/orders/{order_id}", json={
        **body, "status": "Posted", "lines": [{"description": "Plotter service", "quantity": "1", "unit_price": "8000"}]})
    assert changed.status_code == 400 and "posted to the customer's ledger" in changed.json()["detail"]
    # Other details can.
    other = client.put(f"/api/v1/sales/orders/{order_id}", json={**body, "status": "Posted", "remarks": "x"})
    assert other.status_code == 200, other.text

    cancelled = client.put(f"/api/v1/sales/orders/{order_id}", json={**body, "status": "Cancelled"})
    assert cancelled.status_code == 200, cancelled.text
    db.refresh(journal)
    db.refresh(item)
    assert journal.status == "REVERSED" and item.status == "CANCELLED"

def test_quantity_may_not_exceed_stock_on_hand(world, db):
    """With 4 in stock, 4 is accepted and 5 refused; service-type products,
    typed lines and quantities a document already had are not held back."""
    import pytest
    from fastapi import HTTPException
    from app.inventory import availability, stock
    from app.inventory.models import InventoryItem, MainProduct
    parts = MainProduct(company_id=world.company.id, description="SPARE PARTS")
    services = MainProduct(company_id=world.company.id, description="SERVICES")
    db.add_all([parts, services])
    db.flush()
    knife = InventoryItem(company_id=world.company.id, item_code=f"K-{uuid.uuid4().hex[:6]}", description="KNIFE",
                          main_product_id=parts.id)
    plotting = InventoryItem(company_id=world.company.id, item_code=f"P-{uuid.uuid4().hex[:6]}",
                             description="Marker plotting", main_product_id=services.id)
    db.add_all([knife, plotting])
    db.flush()
    stock.post_movement(db, company_id=world.company.id, item_id=knife.id, direction=stock.IN, quantity=D("4"),
                        source_type="test", source_id=None, source_number="T", entry_date=date(2026, 10, 1))
    db.flush()
    check = lambda wanted, before=None, **kw: availability.check(db, world.company.id, wanted, before, **kw)  # noqa: E731

    check({knife.id: D("4")})
    with pytest.raises(HTTPException) as refused:
        check({knife.id: D("5")})
    assert "Not enough stock" in refused.value.detail and "5 asked, 4 in stock" in refused.value.detail
    check({plotting.id: D("500")})                               # a service is not stock
    check({knife.id: D("9")}, {knife.id: D("9")})                # unchanged on an old document
    with pytest.raises(HTTPException):
        check({knife.id: D("9")}, {knife.id: D("9")}, recheck_all=True)   # but checked when it posts
    check({knife.id: D("10")}, {knife.id: D("6")}, already_out=True)      # 6 already out, 4 more fits
    assert availability.quantities([{"item_id": str(knife.id), "quantity": "2"},
                                    {"item_id": str(knife.id), "quantity": "3"},
                                    {"item_id": None, "quantity": "7"}]) == {knife.id: D("5")}

def test_inward_gate_pass_returns_against_the_outward_pass(client, db):
    """Goods go out on a returnable pass and come back on inward passes raised
    against it: never more than went out, and the outward pass closes when
    everything is back and reopens if a return is cancelled."""
    from app.gatepass.models import GatePass
    from app.inventory.router import active_company_id
    from app.partners.models import BusinessPartner
    company_id = active_company_id(db)
    party = BusinessPartner(company_id=company_id, code=f"T-{uuid.uuid4().hex[:8]}", name="Gate Test Party",
                            is_customer=True, is_supplier=False)
    db.add(party)
    db.flush()
    out = client.post("/api/v1/gate-passes/outward", json={
        "doc_date": "2026-10-14", "party_id": str(party.id), "issue_type": "Returnable",
        "expected_return_date": "2026-10-30", "status": "Approved",
        "lines": [{"description": "Cutter head", "quantity": "3"}, {"description": "Knife", "quantity": "2"}]})
    assert out.status_code == 201, out.text
    ogp = out.json()
    assert ogp["status"] == "Approved" and ogp["return_status"] == "Pending return"

    # The customer's open outward passes, and what is still out on this one.
    open_ = client.get("/api/v1/gate-passes/outward/open", params={"party_id": str(party.id)}).json()["items"]
    assert [o["id"] for o in open_] == [ogp["id"]]
    lines = client.get(f"/api/v1/gate-passes/outward/{ogp['id']}/returnable").json()["lines"]
    head, knife = lines

    def inward(qty_head, qty_knife, status="Approved"):
        return client.post("/api/v1/gate-passes/inward", json={
            "doc_date": "2026-10-20", "party_id": str(party.id), "reference_gate_pass_id": ogp["id"],
            "status": status,
            "lines": [l for l in (
                {"description": "Cutter head", "quantity": str(qty_head), "reference_line_id": head["id"]} if qty_head else None,
                {"description": "Knife", "quantity": str(qty_knife), "reference_line_id": knife["id"]} if qty_knife else None) if l]})

    too_many = inward(4, 0)
    assert too_many.status_code == 400 and "3 still out" in too_many.json()["detail"]
    first = inward(2, 2)
    assert first.status_code == 201, first.text
    after = client.get(f"/api/v1/gate-passes/outward/{ogp['id']}").json()
    assert after["status"] == "Approved" and after["return_status"] == "Partly returned" and after["pending_quantity"] == 1
    second = inward(1, 0)
    assert second.status_code == 201
    assert client.get(f"/api/v1/gate-passes/outward/{ogp['id']}").json()["status"] == "Closed"
    assert client.get("/api/v1/gate-passes/outward/open", params={"party_id": str(party.id)}).json()["items"] == []

    # The outward pass cannot be cancelled while returns stand against it…
    assert client.post(f"/api/v1/gate-passes/outward/{ogp['id']}/status", json={"status": "Cancelled"}).status_code == 400
    # …and cancelling a return reopens it.
    undo = client.post(f"/api/v1/gate-passes/inward/{second.json()['id']}/status", json={"status": "Cancelled"})
    assert undo.status_code == 200, undo.text
    again = client.get(f"/api/v1/gate-passes/outward/{ogp['id']}").json()
    assert again["status"] == "Approved" and again["pending_quantity"] == 1

def test_previous_price_for_the_customer_includes_sales_orders(client, db):
    """A customer's own previous price comes from a quotation or a sales
    order; with none, nothing customer-specific is suggested."""
    from app.inventory.models import InventoryItem
    from app.inventory.router import active_company_id
    from app.partners.models import BusinessPartner
    company_id = active_company_id(db)
    item = InventoryItem(company_id=company_id, item_code=f"PR-{uuid.uuid4().hex[:6]}", description="Price test",
                         price=D("900"))
    buyer = BusinessPartner(company_id=company_id, code=f"T-{uuid.uuid4().hex[:8]}", name="Price Test Buyer",
                            is_customer=True, is_supplier=False)
    newcomer = BusinessPartner(company_id=company_id, code=f"T-{uuid.uuid4().hex[:8]}", name="Price Test New",
                               is_customer=True, is_supplier=False)
    db.add_all([item, buyer, newcomer])
    db.flush()
    made = client.post("/api/v1/sales/orders", json={
        "doc_date": "2026-10-15", "customer_id": str(buyer.id), "status": "Draft", "with_sales_tax": False,
        "is_service": True, "lines": [{"item_id": str(item.id), "description": "Price test", "quantity": "1",
                                       "unit_price": "750"}]})
    assert made.status_code == 201, made.text
    own = client.get(f"/api/v1/sales/items/{item.id}/last-rate", params={"customer_id": str(buyer.id)}).json()
    assert own["basis"] == "customer_last" and own["suggested_rate"] == 750 and own["doc_type"] == "sales_order"
    first_time = client.get(f"/api/v1/sales/items/{item.id}/last-rate", params={"customer_id": str(newcomer.id)}).json()
    assert first_time["basis"] != "customer_last"     # the form then starts from the product's price, 900

def test_goods_receipt_takes_only_accepted_quantities_into_stock(client, db):
    """GRN template: excess may be received and recorded, only what is owed can
    be accepted, a line under inspection cannot be posted, and only the
    accepted quantity goes into stock and counts against the order."""
    from app.inventory import stock
    from app.inventory.models import InventoryItem, ItemLocation
    from app.inventory.router import active_company_id
    from app.partners.models import BusinessPartner
    from app.procurement.models import PurchaseOrderLine
    company_id = active_company_id(db)
    supplier = BusinessPartner(company_id=company_id, code=f"S-{uuid.uuid4().hex[:8]}", name="GRN Test Supplier",
                               is_customer=False, is_supplier=True)
    item = InventoryItem(company_id=company_id, item_code=f"G-{uuid.uuid4().hex[:6]}", description="Cutter blade")
    shelf = ItemLocation(company_id=company_id, location=f"GRN TEST {uuid.uuid4().hex[:4]}")
    db.add_all([supplier, item, shelf])
    db.flush()
    po = client.post("/api/v1/procurement/purchase-orders", json={
        "doc_date": "2026-10-15", "supplier_id": str(supplier.id), "warehouse_id": str(shelf.id), "priority": "High",
        "lines": [{"item_id": str(item.id), "description": "Cutter blade", "quantity": "10", "unit_price": "500"}]})
    assert po.status_code == 201, po.text
    order = po.json()
    assert order["priority"] == "High"
    assert client.post(f"/api/v1/procurement/purchase-orders/{order['id']}/status", json={"status": "Approved"}).status_code == 200
    line_id = client.get("/api/v1/procurement/receivable", params={"purchase_order_id": order["id"]}).json()["lines"][0]["purchase_order_line_id"]

    def grn(received, accepted, condition="Good"):
        return client.post("/api/v1/procurement/goods-receipts", json={
            "doc_date": "2026-10-15", "supplier_id": str(supplier.id), "purchase_order_id": order["id"],
            "warehouse_id": str(shelf.id), "delivery_note_number": "DC-77", "bill_to_finance": "Hold",
            "inspection_notes": "2 blades bent", "checked_by": "Store keeper",
            "lines": [{"purchase_order_line_id": line_id, "received_quantity": str(received),
                       "accepted_quantity": str(accepted), "condition": condition, "unit_price": "500"}]})

    assert grn(12, 13).status_code == 400                       # more accepted than received
    under = grn(12, 10, "Under Inspection")
    assert under.status_code == 201
    refused = client.post(f"/api/v1/procurement/goods-receipts/{under.json()['id']}/status", json={"status": "Posted"})
    assert refused.status_code == 400 and "under inspection" in refused.json()["detail"].lower()

    good = grn(12, 10, "Excess")
    assert good.status_code == 201, good.text
    detail = client.get(f"/api/v1/procurement/goods-receipts/{good.json()['id']}").json()
    assert detail["delivery_note_number"] == "DC-77" and detail["bill_to_finance"] == "Hold"
    l = detail["lines"][0]
    assert (l["received_quantity"], l["accepted_quantity"], l["rejected_quantity"], l["short_excess_quantity"]) == (12, 10, 2, 2)
    assert detail["net_payable"] == 5000                          # valued on what was accepted
    posted = client.post(f"/api/v1/procurement/goods-receipts/{good.json()['id']}/status", json={"status": "Posted"})
    assert posted.status_code == 200, posted.text
    assert stock.stock_balance(db, company_id, item.id) == D("10")
    assert db.get(PurchaseOrderLine, uuid.UUID(line_id)).received_quantity == D("10")
    pdf = client.get(f"/api/v1/documents/goods-receipts/{good.json()['id']}.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert client.get(f"/api/v1/documents/purchase-orders/{order['id']}.pdf").status_code == 200

def test_updating_a_product_keeps_its_picture_and_untouched_fields(client, db):
    from app.inventory.models import InventoryItem
    from app.inventory.router import active_company_id
    item = InventoryItem(company_id=active_company_id(db), item_code=f"IMG-{uuid.uuid4().hex[:6]}",
                         description="Clamp padding", image_path="items/sample.jpg", market_name="Clamp pad",
                         min_level=D("5"), currency="\u20ac", price=D("171"))
    db.add(item)
    db.flush()
    saved = client.put(f"/api/v1/inventory/items/{item.id}", json={"description": "Clamp padding 10*15MM", "price": 180})
    assert saved.status_code == 200, saved.text
    db.refresh(item)
    assert item.description == "Clamp padding 10*15MM" and item.price == D("180")
    assert item.image_path == "items/sample.jpg" and item.market_name == "Clamp pad" and item.min_level == D("5")

def test_import_purchase_order_follows_the_template(client, db):
    """Template fields are kept, the extra charges are in the total, an issued
    order's revision goes up when edited, it can be marked Sent and
    Acknowledged, and it prints in the template layout."""
    from app.inventory.router import active_company_id
    from app.partners.models import BusinessPartner
    company_id = active_company_id(db)
    supplier = BusinessPartner(company_id=company_id, code=f"S-{uuid.uuid4().hex[:8]}", name="Orox Test S.r.l.",
                               is_customer=False, is_supplier=True, country="Italy", currency="EUR",
                               bank_name="Intesa", bank_swift="BCITITMM", bank_iban="IT00X")
    db.add(supplier)
    db.flush()
    body = {"doc_date": "2026-10-18", "purchase_type": "Import", "supplier_id": str(supplier.id), "currency": "EUR",
            "exchange_rate": "318", "incoterm": "CIF", "purchase_category": "Spare Parts", "named_place": "Karachi",
            "partial_shipment": "Not allowed", "payment_method": "Advance TT", "advance_percent": "50",
            "bank_charges": "SHA", "goods_condition": "New", "packing_amount": "10", "insurance_amount": "5",
            "other_charges": "2.5", "freight_amount": "20",
            "lines": [{"description": "Knife motor", "quantity": "4", "unit_price": "170", "origin_country": "Italy"}]}
    made = client.post("/api/v1/procurement/purchase-orders", json=body)
    assert made.status_code == 201, made.text
    po = made.json()
    assert po["purchase_category"] == "Spare Parts" and po["bank_charges"] == "SHA" and po["revision"] == 0
    assert po["net_payable"] == 680 + 20 + 10 + 5 + 2.5 and po["freight_amount"] == 20
    assert po["lines"][0]["origin_country"] == "Italy"
    for status in ("Approved", "Sent", "Acknowledged"):   # approving opens it; it is then sent and acknowledged
        moved = client.post(f"/api/v1/procurement/purchase-orders/{po['id']}/status", json={"status": status})
        assert moved.status_code == 200, moved.text
    edited = client.put(f"/api/v1/procurement/purchase-orders/{po['id']}", json={**body, "named_place": "Karachi Port"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["revision"] == 1 and edited.json()["status"] == "Acknowledged"
    pdf = client.get(f"/api/v1/documents/purchase-orders/{po['id']}.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    from app.documents.import_po_pdf import amount_in_words
    assert amount_in_words("1570", "EUR") == "Euros One Thousand Five Hundred Seventy Only"
    assert amount_in_words("717.50", "USD") == "US Dollars Seven Hundred Seventeen and Cents Fifty Only"

def test_sales_order_may_exceed_stock(client, db):
    """An order is not held back by stock (owner, 19-Oct-2026): with none on hand it is
    still saved and posted, and goes into the customer's ledger."""
    from app.inventory.models import InventoryItem
    from app.inventory.router import active_company_id
    from app.partners.models import BusinessPartner
    company_id = active_company_id(db)
    item = InventoryItem(company_id=company_id, item_code=f"NS-{uuid.uuid4().hex[:6]}", description="Belt, none in stock")
    buyer = BusinessPartner(company_id=company_id, code=f"T-{uuid.uuid4().hex[:8]}", name="No Stock Buyer",
                            is_customer=True, is_supplier=False)
    db.add_all([item, buyer])
    db.flush()
    made = client.post("/api/v1/sales/orders", json={
        "doc_date": "2026-10-19", "customer_id": str(buyer.id), "status": "Posted", "with_sales_tax": False,
        "lines": [{"item_id": str(item.id), "description": "Belt", "quantity": "2", "unit_price": "7975"}]})
    assert made.status_code == 201, made.text
    assert made.json()["status"] == "Posted"


def test_purchase_order_saves_with_boxes_left_empty(client, db):
    """Freight, dates and other optional boxes left empty on the form arrive as "";
    the order still saves, with those treated as not filled in (owner, 19-Oct-2026)."""
    from app.inventory.router import active_company_id
    from app.partners.models import BusinessPartner
    supplier = BusinessPartner(company_id=active_company_id(db), code=f"S-{uuid.uuid4().hex[:8]}", name="Blank Box Supplier",
                               is_customer=False, is_supplier=True, currency="USD")
    db.add(supplier)
    db.flush()
    made = client.post("/api/v1/procurement/purchase-orders", json={
        "doc_date": "2026-10-19", "purchase_type": "Import", "supplier_id": str(supplier.id), "currency": "USD",
        "exchange_rate": "280", "freight_amount": "", "document_discount": "", "expiry_date": "",
        "exchange_rate_date": "", "lc_date": "", "credit_days": "", "advance_amount": "",
        "lines": [{"description": "Encoder strip", "quantity": "10", "unit_price": "20", "free_quantity": "",
                   "unit_weight": "", "discount_percent": ""}]})
    assert made.status_code == 201, made.text
    assert made.json()["freight_amount"] == 0 and made.json()["net_payable"] == 200
