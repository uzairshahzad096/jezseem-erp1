"""The posting engine: events -> rules -> journals. Spec tests 18–21.

These post synthetic documents only. Nothing is read from, or written to,
the existing sales or procurement tables.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.finance import ledger, posting
from app.finance.errors import FinanceError
from app.finance.models import POSTED, Account, PostingRule
from app.finance.posting import PostingRequest

D = Decimal
ON = date(2026, 9, 1)


def lines_by_code(world, journal):
    out = {}
    for line in journal.lines:
        out.setdefault(world.db.get(Account, line.account_id).code, []).append(line)
    return out


def request(world, event, amounts, **kw) -> PostingRequest:
    return PostingRequest(event_code=event, company_id=world.company.id, journal_date=ON,
                          amounts={k: D(str(v)) for k, v in amounts.items()},
                          document_type=kw.pop("document_type", "TEST_DOC"),
                          document_id=kw.pop("document_id", uuid.uuid4()), **kw)


# 18
def test_sales_invoice_posting(world, db):
    journal = posting.post(db, request(
        world, "SALES_INVOICE_POSTED",
        {"receivable": "118000", "revenue": "100000", "output_tax": "18000",
         "cogs": "60000", "inventory": "60000"},
        customer_id=world.customer.id, source_reference="SI-TEST-1"), world.audit)
    assert journal.status == POSTED and journal.journal_type == "SYSTEM"
    assert journal.event_code == "SALES_INVOICE_POSTED"
    by = lines_by_code(world, journal)
    assert by["1130"][0].debit == D("118000.00") and by["1130"][0].customer_id == world.customer.id
    assert by["4100"][0].credit == D("100000.00")
    assert by["2130"][0].credit == D("18000.00")
    assert by["5100"][0].debit == D("60000.00")
    assert by["1140"][0].credit == D("60000.00")
    assert journal.total_debit == journal.total_credit == D("178000.00")
    assert ledger.trial_balance(db, world.ctx())["is_balanced"]


def test_sales_invoice_cannot_post_twice(world, db):
    doc = uuid.uuid4()
    amounts = {"receivable": 1180, "revenue": 1000, "output_tax": 180}
    posting.post(db, request(world, "SALES_INVOICE_POSTED", amounts, document_id=doc,
                             customer_id=world.customer.id), world.audit)
    with pytest.raises(FinanceError, match="already posted"):
        posting.post(db, request(world, "SALES_INVOICE_POSTED", amounts, document_id=doc,
                                 customer_id=world.customer.id), world.audit)


def test_sales_invoice_unbalanced_amounts_rejected(world, db):
    with pytest.raises(FinanceError, match="not balanced"):
        posting.post(db, request(world, "SALES_INVOICE_POSTED",
                                 {"receivable": 1000, "revenue": 900},
                                 customer_id=world.customer.id), world.audit)


def test_receivable_requires_customer(world, db):
    with pytest.raises(FinanceError, match="name the customer"):
        posting.post(db, request(world, "SALES_INVOICE_POSTED",
                                 {"receivable": 100, "revenue": 100}), world.audit)


def test_missing_posting_rule_is_reported(world, db):
    rule = db.scalar(select(PostingRule).where(PostingRule.company_id == world.company.id,
                                               PostingRule.event_code == "SALES_INVOICE_POSTED",
                                               PostingRule.line_key == "revenue"))
    rule.account_id = None
    db.flush()
    with pytest.raises(FinanceError, match="No account is set for 'Sales revenue'"):
        posting.post(db, request(world, "SALES_INVOICE_POSTED", {"receivable": 100, "revenue": 100},
                                 customer_id=world.customer.id), world.audit)


def test_rules_are_configurable(world, db):
    """Pointing the revenue rule at services revenue changes where sales post."""
    rule = db.scalar(select(PostingRule).where(PostingRule.company_id == world.company.id,
                                               PostingRule.event_code == "SALES_INVOICE_POSTED",
                                               PostingRule.line_key == "revenue"))
    rule.account_id = world.account("4200").id
    db.flush()
    journal = posting.post(db, request(world, "SALES_INVOICE_POSTED", {"receivable": 500, "revenue": 500},
                                       customer_id=world.customer.id), world.audit)
    assert "4200" in lines_by_code(world, journal)


# 19
def test_customer_receipt_posting(world, db):
    journal = posting.post(db, request(
        world, "CUSTOMER_RECEIPT_POSTED",
        {"bank_cash": "95000", "wht": "5000", "receivable": "100000"},
        customer_id=world.customer.id), world.audit)
    by = lines_by_code(world, journal)
    assert by["1121"][0].debit == D("95000.00")
    assert by["1185"][0].debit == D("5000.00")
    assert by["1130"][0].credit == D("100000.00") and by["1130"][0].customer_id == world.customer.id


def test_receipt_into_a_chosen_cash_account(world, db):
    journal = posting.post(db, request(
        world, "CUSTOMER_RECEIPT_POSTED", {"bank_cash": 2000, "receivable": 2000},
        customer_id=world.customer.id,
        account_overrides={"bank_cash": world.account("1110").id}), world.audit)
    assert "1110" in lines_by_code(world, journal)


# 20
def test_purchase_invoice_posting(world, db):
    journal = posting.post(db, request(
        world, "PURCHASE_INVOICE_POSTED",
        {"purchase": "50000", "input_tax": "9000", "payable": "59000"},
        supplier_id=world.supplier.id), world.audit)
    by = lines_by_code(world, journal)
    assert by["1140"][0].debit == D("50000.00")
    assert by["1180"][0].debit == D("9000.00")
    assert by["2110"][0].credit == D("59000.00") and by["2110"][0].supplier_id == world.supplier.id


def test_payable_requires_supplier_role(world, db):
    with pytest.raises(FinanceError, match="supplier does not exist"):
        posting.post(db, request(world, "PURCHASE_INVOICE_POSTED",
                                 {"purchase": 100, "payable": 100},
                                 supplier_id=world.customer.id), world.audit)


# 21
def test_supplier_payment_posting(world, db):
    journal = posting.post(db, request(
        world, "SUPPLIER_PAYMENT_POSTED",
        {"payable": "59000", "bank_cash": "56050", "wht": "2950"},
        supplier_id=world.supplier.id), world.audit)
    by = lines_by_code(world, journal)
    assert by["2110"][0].debit == D("59000.00") and by["2110"][0].supplier_id == world.supplier.id
    assert by["1121"][0].credit == D("56050.00")
    assert by["2140"][0].credit == D("2950.00")


def test_full_cycle_balances_and_subledgers_agree(world, db):
    """Sell, collect, buy, pay: the ledger balances and AR/AP equal their parties."""
    posting.post(db, request(world, "SALES_INVOICE_POSTED",
                             {"receivable": 11800, "revenue": 10000, "output_tax": 1800},
                             customer_id=world.customer.id), world.audit)
    posting.post(db, request(world, "CUSTOMER_RECEIPT_POSTED", {"bank_cash": 5000, "receivable": 5000},
                             customer_id=world.customer.id), world.audit)
    posting.post(db, request(world, "PURCHASE_INVOICE_POSTED",
                             {"purchase": 4000, "input_tax": 720, "payable": 4720},
                             supplier_id=world.supplier.id), world.audit)
    posting.post(db, request(world, "SUPPLIER_PAYMENT_POSTED", {"payable": 4720, "bank_cash": 4720},
                             supplier_id=world.supplier.id), world.audit)
    tb = ledger.trial_balance(db, world.ctx())
    rows = {r["account_code"]: r for r in tb["rows"]}
    assert tb["is_balanced"]
    assert rows["1130"]["balance"] == D("6800.00")
    assert rows["2110"]["balance"] == D("0.00")
    assert rows["1121"]["balance"] == D("280.00")
    control = ledger.balances_by_control_type(db, world.ctx(), None)
    assert control["RECEIVABLE"] == D("6800.00")


def test_negative_amount_posts_on_the_other_side(world, db):
    journal = posting.post(db, request(world, "STOCK_ISSUE_POSTED", {"cogs": -250, "inventory": -250}),
                           world.audit)
    by = lines_by_code(world, journal)
    assert by["5100"][0].credit == D("250.00")
    assert by["1140"][0].debit == D("250.00")


def test_preview_writes_nothing(world, db):
    from app.finance.models import JournalEntry
    before = db.scalar(select(JournalEntry.id).where(JournalEntry.company_id == world.company.id).limit(1))
    result = posting.preview(db, request(world, "STOCK_RECEIPT_POSTED", {"inventory": 900, "grni": 900}))
    assert result["balanced"] and result["problem"] is None
    assert [l["account_code"] for l in result["lines"]] == ["1140", "2115"]
    assert before is None
    assert db.scalar(select(JournalEntry.id).where(JournalEntry.company_id == world.company.id).limit(1)) is None


def test_decimal_precision_no_float_drift(world, db):
    """0.1 + 0.2 must be exactly 0.3 in the ledger."""
    journal = posting.post(db, request(world, "EXPENSE_POSTED",
                                       {"expense": "0.1", "input_tax": "0.2", "bank_cash": "0.3"}),
                           world.audit)
    assert journal.total_debit == journal.total_credit == D("0.30")
