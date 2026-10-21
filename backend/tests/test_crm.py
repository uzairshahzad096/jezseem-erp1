"""CRM: a customer seen whole, their contacts, and the activity log shared with Leads."""

import uuid
from datetime import date, timedelta

from app.inventory.router import active_company_id
from app.partners.models import BusinessPartner
from app.sales.models import QUOTATION, SALES_ORDER, SalesDocument

API = "/api/v1/crm"


def _customer(db, name):
    c = BusinessPartner(company_id=active_company_id(db), code=f"T-{uuid.uuid4().hex[:8]}", name=name,
                        is_customer=True, is_supplier=False, city="Faisalabad")
    db.add(c)
    db.flush()
    return c


def test_customer_360_brings_everything_together(client, db):
    company_id = active_company_id(db)
    client.headers["X-Company-Id"] = str(company_id)
    c = _customer(db, "CRM Test Mills")
    quote = SalesDocument(company_id=company_id, doc_type=QUOTATION, doc_number=f"Q{uuid.uuid4().hex[:6]}",
                          doc_date=date.today() - timedelta(days=40), customer_id=c.id, status="Closed",
                          net_receivable=120000)
    db.add(quote)
    db.flush()
    for days, amount, source in ((30, 120000, quote.id), (400, 80000, None)):
        db.add(SalesDocument(company_id=company_id, doc_type=SALES_ORDER, doc_number=f"T{uuid.uuid4().hex[:8]}",
                             doc_date=date.today() - timedelta(days=days), customer_id=c.id, status="Posted",
                             net_receivable=amount, source_document_id=source))
    db.flush()

    listed = client.get(f"{API}/customers", params={"search": "CRM Test Mills"}).json()["items"][0]
    assert listed["segment"] == "Active" and listed["orders"] == 2 and listed["sales_12m"] == 120000

    # A contact, and a customer activity with a follow-up, not tied to any lead.
    contact = client.post(f"{API}/contacts", json={"partner_id": str(c.id), "contact_name": "Mr. Kashif",
                                                   "title": "Cutting Manager", "cell": "0300-1111111",
                                                   "is_primary": True, "email": ""})
    assert contact.status_code == 201, contact.text
    logged = client.post(f"{API}/activities", json={
        "customer_id": str(c.id), "contact_id": contact.json()["id"], "activity_type": "Visit",
        "summary": "Courtesy visit, checked the plotter", "next_follow_up_date": (date.today() + timedelta(days=7)).isoformat(),
        "next_follow_up_note": "Offer the ink contract"})
    assert logged.status_code == 201, logged.text
    assert len(logged.json()["ids"]) == 2

    # A lead for them shows on the 360 too, with its activities in the same log.
    lead = client.post("/api/v1/leads", json={"title": "Second plotter", "customer_id": str(c.id),
                                             "estimated_value": "2500000"}).json()

    view = client.get(f"{API}/customers/{c.id}").json()
    k = view["kpis"]
    assert k["orders"] == 2 and k["sales_total"] == 200000 and k["quotation_conversion"] == 100
    assert k["open_leads"] == 1 and k["pipeline_value"] == 2500000
    assert view["contacts"][0]["contact_name"] == "Mr. Kashif" and view["contacts"][0]["is_primary"]
    summaries = [a["summary"] for a in view["activities"]]
    assert "Courtesy visit, checked the plotter" in summaries and any("Lead created" in s for s in summaries)
    assert len(view["sales_by_month"]) == 12

    # The to-do appears on the activity log, and can be ticked off.
    todo = client.get(f"{API}/activities", params={"scope": "todo", "customer_id": str(c.id)}).json()["items"]
    assert len(todo) == 1 and todo[0]["summary"] == "Offer the ink contract" and todo[0]["contact"] == "Mr. Kashif"
    done = client.post(f"{API}/activities/{todo[0]['id']}/done", json={"outcome": "Sent the offer"})
    assert done.status_code == 200, done.text
    assert client.get(f"{API}/activities", params={"scope": "todo", "customer_id": str(c.id)}).json()["items"] == []

    # Opportunities are the leads with our customers.
    opps = client.get("/api/v1/leads", params={"customers_only": True, "status": "open", "customer_id": str(c.id)}).json()
    assert [o["id"] for o in opps["items"]] == [lead["id"]]


def test_editing_a_customer_keeps_fields_the_form_does_not_show(client, db):
    """The customer form has no mobile, credit days or bank address box; saving it must keep them."""
    c = _customer(db, "Keep Mobile Test")
    c.cell, c.credit_days = "0300-9999999", 30
    db.flush()
    saved = client.put(f"/api/v1/partners/{c.id}", json={"code": c.code, "name": "Keep Mobile Test Ltd",
                                                          "city": "Lahore", "is_customer": True})
    assert saved.status_code == 200, saved.text
    db.refresh(c)
    assert c.name == "Keep Mobile Test Ltd" and c.cell == "0300-9999999" and c.credit_days == 30
