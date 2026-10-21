"""Opening balances: import, validation, posting and reconciliation.
Spec tests 12–14. All figures are synthetic, made up for the test."""

import io
from datetime import date
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.finance import ledger, opening
from app.finance.errors import FinanceError
from app.finance.models import JournalEntry
from app.inventory.models import InventoryItem, ItemLocation

D = Decimal
CUTOVER = date(2026, 7, 1)

GL = [
    {"Account Code": "1110", "Account Name": "Cash", "Debit": "50,000", "Credit": ""},
    {"Account Code": "1121", "Account Name": "Bank", "Debit": 250000, "Credit": None},
    {"Account Code": "1130", "Account Name": "Receivables", "Debit": 180000, "Credit": 0},
    {"Account Code": "1140", "Account Name": "Inventory", "Debit": 120000, "Credit": 0},
    {"Account Code": "2110", "Account Name": "Payables", "Debit": 0, "Credit": 100000},
    {"Account Code": "3100", "Account Name": "Capital", "Debit": 0, "Credit": 400000},
    {"Account Code": "3200", "Account Name": "Retained earnings", "Debit": 0, "Credit": 100000},
]
AR = [
    {"Customer Code": "C001", "Invoice Reference": "INV-101", "Invoice Date": "15-06-2026",
     "Due Date": "15-07-2026", "Outstanding Amount": 130000},
    {"Customer Code": "", "Customer Name": "Beta Mills", "Invoice Reference": "INV-102",
     "Invoice Date": "20-06-2026", "Due Date": "20-07-2026", "Outstanding Amount": "50,000"},
]
AP = [
    {"Supplier Code": "S001", "Bill Reference": "B-77", "Bill Date": "10-06-2026",
     "Due Date": "10-07-2026", "Outstanding Amount": 100000},
]
BANK = [
    {"Bank": "HBL", "Account Number": "0012-345", "Account Code": "1121",
     "Statement Balance": 260000, "Uncleared Deposits": 15000, "Uncleared Payments": 25000},
]


@pytest.fixture
def stock(world, db):
    location = ItemLocation(company_id=world.company.id, location="Main Store")
    db.add(location)
    db.add_all([InventoryItem(company_id=world.company.id, item_code=code, description=f"Item {code}")
                for code in ("ITM-1", "ITM-2")])
    db.flush()
    return [
        {"Item Code": "ITM-1", "Warehouse": "Main Store", "Quantity": 100, "Unit Cost": 800,
         "Total Value": 80000},
        {"Item Code": "ITM-2", "Warehouse": "Main Store", "Quantity": 40, "Unit Cost": 1000},
    ]


def new_batch(world):
    return opening.create_batch(world.db, world.ctx(), {
        "financial_year_id": world.fy.id, "cutover_date": CUTOVER,
        "source_document": "Legacy TB signed 30-06-2026 (test)"})


def load_all(world, batch, stock_rows):
    ctx = world.ctx()
    for schedule, rows in (("GL", GL), ("AR", AR), ("AP", AP), ("INVENTORY", stock_rows), ("BANK", BANK)):
        opening.import_rows(world.db, ctx, batch, schedule, rows, file_name=f"{schedule}.csv",
                            file_hash=f"hash-{batch.id}-{schedule}")


# 12
def test_valid_batch_passes_validation(world, db, stock):
    batch = new_batch(world)
    load_all(world, batch, stock)
    result = opening.validate(db, world.ctx(), batch.id)
    assert result["problems"] == [] and result["passed"], result
    assert batch.status == "VALIDATED"
    assert batch.total_debit == batch.total_credit == D("600000.00")


def test_validation_catches_every_kind_of_problem(world, db, stock):
    batch = new_batch(world)
    ctx = world.ctx()
    bad_gl = GL[:-1] + [{"Account Code": "9999", "Debit": 0, "Credit": 100000}]
    opening.import_rows(db, ctx, batch, "GL", bad_gl, file_name="gl.csv", file_hash="h1")
    opening.import_rows(db, ctx, batch, "AR", AR[:1] + [
        {"Customer Code": "NOPE", "Invoice Reference": "X", "Outstanding Amount": 50000}],
        file_name="ar.csv", file_hash="h2")
    opening.import_rows(db, ctx, batch, "INVENTORY", [
        {"Item Code": "ITM-1", "Quantity": 100, "Unit Cost": 0},
        {"Item Code": "GHOST", "Quantity": 1, "Unit Cost": 5}], file_name="inv.csv", file_hash="h3")
    result = opening.validate(db, ctx, batch.id)
    assert not result["passed"] and batch.status == "DRAFT"
    errors = [e for line in batch.lines for e in line.errors]
    assert any("No account with code 9999" in e for e in errors)
    assert any("No customer with code NOPE" in e for e in errors)
    assert any("unit cost is missing or zero" in e for e in errors)
    assert any("No inventory item with code GHOST" in e for e in errors)
    text_ = " ".join(result["problems"])
    assert "1140 Inventory" in text_                                 # valuation does not tie
    assert "1121" in text_ and "no BANK schedule" in text_          # bank schedule missing
    assert "2110" in text_ and "100,000.00 Cr" in text_             # AP missing, shown on its natural side
    assert "row(s) have problems" in text_                           # the unknown customer blocks too


def test_unbalanced_trial_balance_rejected(world, db):
    batch = new_batch(world)
    opening.import_rows(db, world.ctx(), batch, "GL", [
        {"Account Code": "1110", "Debit": 1000}, {"Account Code": "3100", "Credit": 900}],
        file_name="gl.csv", file_hash="h")
    result = opening.validate(db, world.ctx(), batch.id)
    assert any("does not balance" in p for p in result["problems"])


def test_cutover_must_be_in_the_year(world):
    with pytest.raises(FinanceError, match="must fall within"):
        opening.create_batch(world.db, world.ctx(), {
            "financial_year_id": world.fy.id, "cutover_date": date(2025, 6, 30)})


def test_duplicate_file_detected(world, db):
    first, second = new_batch(world), new_batch(world)
    rows = [{"Account Code": "1110", "Debit": 10}, {"Account Code": "3100", "Credit": 10}]
    opening.import_rows(db, world.ctx(), first, "GL", rows, file_name="gl.csv", file_hash="same")
    with pytest.raises(FinanceError, match="already been imported into batch"):
        opening.import_rows(db, world.ctx(), second, "GL", rows, file_name="gl.csv", file_hash="same")


def test_duplicate_rows_detected(world, db):
    batch = new_batch(world)
    opening.import_rows(db, world.ctx(), batch, "AR", [AR[0], AR[0]], file_name="ar.csv", file_hash="d")
    assert any("Duplicate of row 1" in e for e in batch.lines[1].errors)


# 13
def test_import_from_template_workbook_then_post(world, db, stock):
    """Fill the real template, import it in one upload, and post."""
    workbook = load_workbook(io.BytesIO(opening.template_workbook()))
    for schedule, rows in (("GL", GL), ("AR", AR), ("AP", AP), ("INVENTORY", stock), ("BANK", BANK)):
        sheet = workbook[opening.SHEETS[schedule]]
        headers = [c.value for c in sheet[1]]
        for row in rows:
            sheet.append([row.get(h) for h in headers])
    stream = io.BytesIO()
    workbook.save(stream)

    batch = new_batch(world)
    ctx = world.ctx()
    imported = opening.import_file(db, ctx, batch, None, "opening.xlsx", stream.getvalue())
    assert imported == {"GL": 7, "AR": 2, "AP": 1, "INVENTORY": 2, "BANK": 1}

    assert opening.validate(db, ctx, batch.id)["passed"]
    preview = opening.preview(db, ctx, batch.id)
    assert preview["balanced"] and preview["total_debit"] == D("600000.00")
    assert all(row["difference"] == 0 for row in preview["tie_out"])

    opening.approve(db, ctx, batch.id)
    opening.post(db, ctx, batch.id)
    assert batch.status == "POSTED"
    journal = db.get(JournalEntry, batch.journal_entry_id)
    assert journal.journal_type == "OPENING" and journal.status == "POSTED"
    assert journal.journal_date == CUTOVER

    # The receivable account carries one line per customer invoice.
    ar_lines = [l for l in journal.lines if l.account_id == world.account("1130").id]
    assert sorted((l.customer_id, l.debit) for l in ar_lines) == sorted(
        [(world.customer.id, D("130000.00")), (world.customer2.id, D("50000.00"))])
    stock_lines = [l for l in journal.lines if l.inventory_item_id]
    assert sorted(l.debit for l in stock_lines) == [D("40000.00"), D("80000.00")]
    bank = [l for l in journal.lines if l.account_id == world.account("1121").id]
    assert bank[0].debit == D("250000.00")   # 260,000 + 15,000 − 25,000

    tb = ledger.trial_balance(db, ctx, date_to=CUTOVER)
    assert tb["is_balanced"] and tb["totals"]["closing_debit"] == D("600000.00")

    # Posted batches are frozen.
    with pytest.raises(FinanceError, match="frozen"):
        opening.import_rows(db, ctx, batch, "GL", GL, file_name="again.csv", file_hash="again")
    with pytest.raises(DBAPIError, match="frozen"):
        db.execute(text("update opening_balance_lines set debit = 1 where batch_id = :id"), {"id": batch.id})


def test_second_opening_batch_for_same_year_refused(world, db, stock):
    batch = new_batch(world)
    load_all(world, batch, stock)
    ctx = world.ctx()
    opening.validate(db, ctx, batch.id)
    opening.approve(db, ctx, batch.id)
    opening.post(db, ctx, batch.id)
    second = new_batch(world)
    opening.import_rows(db, ctx, second, "GL", [{"Account Code": "1110", "Debit": 5},
                                                {"Account Code": "3100", "Credit": 5}],
                        file_name="x.csv", file_hash="x")
    result = opening.validate(db, ctx, second.id)
    assert any("already posted for this year" in p for p in result["problems"])


# 14
def test_reconciliation_gates_completion(world, db, stock):
    batch = new_batch(world)
    load_all(world, batch, stock)
    ctx = world.ctx()
    opening.validate(db, ctx, batch.id)
    opening.approve(db, ctx, batch.id)
    opening.post(db, ctx, batch.id)

    state = opening.reconciliation(db, ctx, batch.id)
    erp = {r["category"]: r["erp_balance"] for r in state["rows"]}
    assert erp == {
        "TRIAL_BALANCE": D("600000.00"), "ACCOUNTS_RECEIVABLE": D("180000.00"),
        "ACCOUNTS_PAYABLE": D("100000.00"), "INVENTORY": D("120000.00"),
        "CASH": D("50000.00"), "BANK": D("250000.00"), "EQUITY": D("500000.00"),
    }
    assert all(s["difference"] == 0 for s in state["subledgers"])
    assert not state["can_complete"] and len(state["blocking"]) == 7

    # Legacy figures typed from the signed trial balance; AR differs by 1,000.
    legacy = {**erp, "ACCOUNTS_RECEIVABLE": D("181000.00")}
    state = opening.save_reconciliation(db, ctx, batch.id, [
        {"category": c, "legacy_balance": v} for c, v in legacy.items()])
    assert state["blocking"] == ["Accounts receivable"]
    with pytest.raises(FinanceError, match="unreconciled: Accounts receivable"):
        opening.complete(db, ctx, batch.id)

    state = opening.save_reconciliation(db, ctx, batch.id, [{
        "category": "ACCOUNTS_RECEIVABLE", "legacy_balance": "181000",
        "explanation": "Legacy ERP double-counted invoice INV-099 (credit note CN-12 not applied)."}])
    assert state["can_complete"]
    opening.complete(db, ctx, batch.id)
    assert batch.status == "COMPLETED"
    with pytest.raises(DBAPIError, match="can no longer change"):
        db.execute(text("update opening_balance_batches set notes = 'x' where id = :id"), {"id": batch.id})


def test_opening_journal_cannot_be_reversed(world, db, stock):
    from app.finance import posting
    batch = new_batch(world)
    load_all(world, batch, stock)
    ctx = world.ctx()
    opening.validate(db, ctx, batch.id)
    opening.approve(db, ctx, batch.id)
    opening.post(db, ctx, batch.id)
    journal = db.get(JournalEntry, batch.journal_entry_id)
    with pytest.raises(FinanceError, match="adjustment journal"):
        posting.reverse(db, journal, CUTOVER, "wrong numbers", world.audit)


def test_parsers():
    assert opening.parse_decimal("(1,250.50)") == D("-1250.50")
    assert opening.parse_decimal(" - ") is None
    assert opening.parse_decimal(0.1) == D("0.10")
    assert opening.parse_date("01-07-2026") == date(2026, 7, 1)
    assert opening.parse_date("2026-07-01") == date(2026, 7, 1)
    with pytest.raises(ValueError):
        opening.parse_decimal("abc")
