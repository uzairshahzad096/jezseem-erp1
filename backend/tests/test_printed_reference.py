"""Printed reference numbers follow the old ERP: year in front of a plain number."""

from datetime import date

from app.common.references import printed_reference
from app.gatepass.models import GatePass
from app.sales.models import QUOTATION, SalesDocument, SalesDocumentLine


def test_plain_number_gets_the_year():
    assert printed_reference("1538", date(2026, 11, 1)) == "20261538"
    assert printed_reference("1", date(2026, 9, 1)) == "20261"          # the supplied Service Invoice
    assert printed_reference("2026", date(2027, 1, 5)) == "20272026"    # a number that looks like a year


def test_dated_and_prefixed_references_print_as_stored():
    assert printed_reference("202607142", date(2026, 7, 14)) == "202607142"   # sales order
    assert printed_reference("202608291", date(2026, 9, 2)) == "202608291"    # dated even if the date moved
    assert printed_reference("SI-000001", date(2026, 9, 1)) == "SI-000001"
    assert printed_reference("LPO-2600006", date(2026, 9, 1)) == "LPO-2600006"
    assert printed_reference(None, date(2026, 9, 1)) == ""


def test_quotation_pdf_prints_year_prefixed_reference(client, world, db):
    q = SalesDocument(company_id=world.company.id, doc_type=QUOTATION, doc_number="1538",
                      doc_date=date(2026, 11, 1), customer_id=world.customer.id, status="Sent")
    q.lines = [SalesDocumentLine(line_number=1, description="Spreader service", quantity=7, unit_price=6000)]
    db.add(q)
    db.flush()
    response = client.get(f"/api/v1/documents/sales/{q.id}/service_invoice.pdf")
    assert response.status_code == 200
    assert 'filename="service_invoice-20261538.pdf"' in response.headers["content-disposition"]


def test_gate_pass_pdf_uses_the_same_rule(client, world, db):
    gp = GatePass(company_id=world.company.id, pass_type="outward", doc_number="14",
                  doc_date=date(2026, 4, 14), party_id=world.customer.id, status="Draft")
    db.add(gp)
    db.flush()
    response = client.get(f"/api/v1/documents/gate-passes/{gp.id}.pdf")
    assert response.status_code == 200
    assert "gate-pass-202614.pdf" in response.headers["content-disposition"]
