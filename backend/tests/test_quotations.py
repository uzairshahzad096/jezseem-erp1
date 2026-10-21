"""Quotations: reopening a closed quotation, and the suggested unit price."""

from datetime import date
from decimal import Decimal as D

from app.inventory.models import InventoryItem
from app.partners.models import BusinessPartner
from app.sales.models import QUOTATION, SALES_ORDER, SalesDocument, SalesDocumentLine


def quotation(world, customer, price, on, item=None, status="Sent", number=None, currency="PKR"):
    doc = SalesDocument(company_id=world.company.id, doc_type=QUOTATION, doc_number=number or f"Q{on:%m%d}{price}",
                        doc_date=on, customer_id=customer.id, status=status, currency=currency)
    doc.lines = [SalesDocumentLine(line_number=1, item_id=item.id if item else None, description="Spreader",
                                   quantity=D(1), unit_price=D(price), currency=currency)]
    world.db.add(doc)
    world.db.flush()
    return doc


def body(world, doc, status):
    return {"doc_date": str(doc.doc_date), "customer_id": str(doc.customer_id), "status": status,
            "lines": [{"description": "Spreader", "quantity": "1", "unit_price": "295000", "tax_percent": "18"}]}


def test_closed_quotation_can_be_reopened_by_changing_status(client, world, db, monkeypatch):
    import app.sales.router as sales_router
    monkeypatch.setattr(sales_router, "active_company_id", lambda db: world.company.id)
    q = quotation(world, world.customer, 295000, date(2026, 10, 8), status="Closed")

    # Saving it unchanged is still refused, with a pointer to how to reopen it.
    refused = client.put(f"/api/v1/sales/quotations/{q.id}", json=body(world, q, "Closed"))
    assert refused.status_code == 400 and "Change its status to reopen it" in refused.json()["detail"]

    # Changing the status reopens it, and the edit is saved with it.
    reopened = client.put(f"/api/v1/sales/quotations/{q.id}", json=body(world, q, "Approved"))
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "Approved"
    assert reopened.json()["net_receivable"] == 348100.0      # 295,000 + 18%

    # The status action works the same way.
    q.status = "Closed"
    db.flush()
    response = client.post(f"/api/v1/sales/quotations/{q.id}/status", json={"status": "Sent"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "Sent"


def test_reopened_quotation_still_cannot_become_a_second_order(world, db):
    from fastapi import HTTPException
    import pytest
    from app.sales import service
    q = quotation(world, world.customer, 1000, date(2026, 10, 1), status="Approved")
    db.add(SalesDocument(company_id=world.company.id, doc_type=SALES_ORDER, doc_number="SO-X", doc_date=date(2026, 10, 2),
                         customer_id=world.customer.id, status="Draft", source_document_id=q.id))
    db.flush()
    with pytest.raises(HTTPException) as refused:
        service.check_convertible(db, world.company.id, str(q.id))
    assert refused.value.status_code == 409


def partner(world, code):
    p = BusinessPartner(company_id=world.company.id, code=code, name=f"Customer {code}",
                        is_customer=True, is_supplier=False)
    world.db.add(p)
    world.db.flush()
    return p


def test_suggested_price_is_customers_last_else_most_common(client, world, db, monkeypatch):
    item = InventoryItem(company_id=world.company.id, item_code="SPR-1", description="Spreader")
    db.add(item)
    db.flush()
    d, e, token = partner(world, "C004"), partner(world, "C005"), partner(world, "C003")
    quotation(world, world.customer, 250000, date(2026, 1, 5), item)
    quotation(world, world.customer, 270000, date(2026, 6, 5), item)     # customer's latest
    quotation(world, world.customer2, 200000, date(2026, 2, 5), item)    # superseded by the next
    quotation(world, world.customer2, 310000, date(2026, 3, 5), item)    # customer2's latest
    quotation(world, d, 310000, date(2026, 4, 5), item)
    quotation(world, e, 270000, date(2026, 1, 9), item)                  # superseded by the next
    quotation(world, e, 310000, date(2026, 5, 9), item)
    quotation(world, world.customer2, 900, date(2026, 3, 6), item, currency="USD")  # other currency ignored
    quotation(world, token, 1, date(2026, 4, 1), item)                    # token price, left out

    import app.sales.router as sales_router
    monkeypatch.setattr(sales_router, "active_company_id", lambda db: world.company.id)

    known = client.get(f"/api/v1/sales/items/{item.id}/last-rate?customer_id={world.customer.id}").json()
    assert (known["last_rate"], known["suggested_rate"], known["basis"]) == (270000, 270000, "customer_last")

    first_time = world.supplier  # never quoted this item
    first = client.get(f"/api/v1/sales/items/{item.id}/last-rate?customer_id={first_time.id}").json()
    # One vote per customer, at their latest price: 310000 ×3, 270000 ×1.
    assert (first["last_rate"], first["suggested_rate"], first["basis"]) == (None, 310000, "most_common_other_customers")
    assert (first["customers_at_price"], first["customers_compared"]) == (3, 4)
    assert first["price_range"] == [270000, 310000]

    nobody = client.get(f"/api/v1/sales/items/{item.id}/last-rate").json()
    assert nobody["suggested_rate"] == 310000

    usd = client.get(f"/api/v1/sales/items/{item.id}/last-rate?customer_id={world.customer2.id}&currency=USD").json()
    assert usd["suggested_rate"] == 900


def test_most_common_price_tie_goes_to_the_latest(client, world, db, monkeypatch):
    item = InventoryItem(company_id=world.company.id, item_code="SPR-2", description="Spreader 2")
    db.add(item)
    db.flush()
    quotation(world, world.customer, 500, date(2026, 2, 1), item)
    quotation(world, world.customer2, 450, date(2026, 8, 1), item)       # more recent of the tie
    import app.sales.router as sales_router
    monkeypatch.setattr(sales_router, "active_company_id", lambda db: world.company.id)
    r = client.get(f"/api/v1/sales/items/{item.id}/last-rate?customer_id={world.supplier.id}").json()
    assert (r["suggested_rate"], r["customers_at_price"], r["customers_compared"]) == (450, 1, 2)
