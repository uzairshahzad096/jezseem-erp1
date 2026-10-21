"""Calibration / Services: machines, contracts, service invoices in the ledger,
calibration definitions and certificates."""

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.finance.models import JournalEntry, JournalEntryLine, Account
from app.receivables.models import ARItem


def _customer(db):
    from app.inventory.router import active_company_id
    from app.partners.models import BusinessPartner
    customer = BusinessPartner(company_id=active_company_id(db), code=f"C-{uuid.uuid4().hex[:8]}",
                               name="Tiger Hosiery Test (Pvt) Ltd", is_customer=True, is_supplier=False,
                               address="5 KM Raiwind, Manga Road, Lahore")
    db.add(customer)
    db.flush()
    return customer


def test_calibration_module_end_to_end(client, db):
    api = "/api/v1/calibration"
    customer = _customer(db)

    md = client.post(f"{api}/machine-definitions", json={
        "machine_category": "AUTO CUTTER", "vendor_name": "MORGAN TECNICA", "model_number": "NEXT2",
        "origin": "Italy", "description": "CNC Fabric Cutter"})
    assert md.status_code == 201, md.text
    md = md.json()

    machine = client.post(f"{api}/customer-machines", json={
        "customer_id": str(customer.id), "machine_definition_id": md["id"], "machine_code": "Auto Cutter 01",
        "serial_number": "M005669", "machine_status": "ACTIVE", "machine_location": "Lahore"})
    assert machine.status_code == 201, machine.text
    machine = machine.json()
    listed = client.get(f"{api}/customer-machines", params={"customer_id": str(customer.id)}).json()
    assert listed["total"] == 1 and listed["items"][0]["model_number"] == "NEXT2"

    contract = client.post(f"{api}/contracts", json={
        "contract_date": "2026-09-01", "customer_id": str(customer.id), "start_date": "2026-09-01",
        "end_date": "2027-08-31", "billing_frequency": "MONTHLY", "charge_amount": "20000",
        "division": "Cutting Division", "reference": "JEZ-TGR.-0026", "response_hours": 24,
        "spare_parts_by": "Customer", "contract_status": "ACTIVE",
        "service_coverage": "Routine maintenance including inspection and necessary adjustments.",
        "lines": [{"description": "Spreaders", "customer_machine_id": machine["id"]}, {"description": "Plotters"}]})
    assert contract.status_code == 201, contract.text
    contract = contract.json()
    assert contract["contract_number"].startswith("CON/1/2026/")
    assert client.get(f"{api}/contracts/{contract['id']}/print.pdf").content[:4] == b"%PDF"

    # The contract fills in its first invoice: September, at the monthly charge.
    draft = client.get(f"{api}/contracts/{contract['id']}/next-invoice").json()
    assert draft["period_from"] == "2026-09-01" and draft["period_to"] == "2026-09-30"
    assert draft["lines"][0]["unit_price"] == 20000
    made = client.post(f"{api}/invoices", json={**draft, "invoice_date": "2026-09-30", "post": True})
    assert made.status_code == 201, made.text
    invoice = made.json()
    assert invoice["status"] == "Posted" and invoice["net_receivable"] == 20000

    # It bills the customer: Dr receivable, Cr Sales - Services, and a receivable item.
    journal = db.scalar(select(JournalEntry).where(JournalEntry.document_id == uuid.UUID(invoice["id"])))
    credits = {code: credit for code, credit in db.execute(
        select(Account.code, JournalEntryLine.credit).join(Account, Account.id == JournalEntryLine.account_id)
        .where(JournalEntryLine.journal_entry_id == journal.id, JournalEntryLine.credit > 0))}
    assert credits == {"4200": Decimal("20000.00")}
    item = db.scalar(select(ARItem).where(ARItem.journal_entry_id == journal.id))
    assert item.customer_id == customer.id and item.document_number == invoice["invoice_number"]

    # It is in the customer's ledger under its own number, and offered on Payment Receipts.
    client.headers["X-Company-Id"] = str(customer.company_id)   # the company the module works in
    rows = client.get("/api/v1/finance/ledger", params={"customer_id": str(customer.id)}).json()["rows"]
    mine = [r for r in rows if r.get("invoice_no") == invoice["invoice_number"]]
    assert mine and "SRV#" in mine[0]["narration"] and contract["contract_number"] in mine[0]["narration"]
    open_items = client.get(f"/api/v1/ar/customers/{customer.id}/open-items")
    assert open_items.status_code == 200, open_items.text
    assert invoice["invoice_number"] in open_items.text

    # The next invoice continues from October; a posted invoice's amounts cannot change.
    assert client.get(f"{api}/contracts/{contract['id']}/next-invoice").json()["period_from"] == "2026-10-01"
    body = {**draft, "invoice_date": "2026-09-30", "lines": [{**draft["lines"][0], "unit_price": 25000}]}
    assert client.put(f"{api}/invoices/{invoice['id']}", json=body).status_code == 400
    assert client.get(f"{api}/invoices/{invoice['id']}/print.pdf").content[:4] == b"%PDF"

    # Cancelling reverses it and cancels the receivable item.
    cancelled = client.post(f"{api}/invoices/{invoice['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    db.refresh(item)
    assert item.status == "CANCELLED"

    definition = client.post(f"{api}/definitions", json={
        "machine_definition_id": md["id"], "definition_name": "Auto Cutter 01", "validity_days": 90,
        "default_temperature": "35°C +/- 10°C", "standard_note": "CALIBRATION PASSED, INSTRUMENT IS CERTIFIED FOR OPERATION.",
        "tests": [{"seq": 1, "test_title": "Knife perpendicular test"},
                  {"seq": 2, "test_title": "Down Plate Movement Verification"}]})
    assert definition.status_code == 201, definition.text
    definition = definition.json()
    assert [t["test_title"] for t in definition["tests"]][0] == "Knife perpendicular test"

    report = client.post(f"{api}/reports", json={
        "customer_id": str(customer.id), "customer_machine_id": machine["id"],
        "calibration_definition_id": definition["id"], "contract_id": contract["id"],
        "calibration_date": "2026-10-01", "issue_date": "2026-10-01", "overall_result": "PASS",
        "report_status": "ISSUED", "temperature": "35°C +/- 10°C", "main_voltage": "3Φ, 400VAC",
        "results": [{"test_title": "Knife perpendicular test", "initial_reading": "✓", "observed": "✓",
                     "uncertainty": "0", "passed": True}]})
    assert report.status_code == 201, report.text
    report = report.json()
    assert report["certificate_number"].startswith("CAL/1/2026/")
    assert report["expiry_date"] == "2026-12-30"     # issue date + the definition's 90 days
    assert client.get(f"{api}/reports/{report['id']}/print.pdf").content[:4] == b"%PDF"
    # An issued certificate is not deleted, and a machine with a certificate is kept.
    assert client.delete(f"{api}/reports/{report['id']}").status_code == 400
    assert client.delete(f"{api}/customer-machines/{machine['id']}").status_code == 400
