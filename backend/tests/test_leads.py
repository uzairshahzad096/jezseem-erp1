"""Leads: a prospect from first contact to won, follow-ups, sources, assignments,
and opportunities among customers who have stopped ordering."""

import uuid
from datetime import date, timedelta

from app.inventory.router import active_company_id
from app.partners.models import BusinessPartner
from app.sales.models import SALES_ORDER, SalesDocument

API = "/api/v1/leads"


def test_lead_pipeline_end_to_end(client, db):
    company_id = active_company_id(db)
    client.headers["X-Company-Id"] = str(company_id)
    look = client.get(f"{API}/lookups").json()
    assert [s["name"] for s in look["stages"]][:2] == ["New", "Contacted"] and look["sources"]
    source = look["sources"][0]["id"]

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    made = client.post(f"{API}", json={
        "title": "2 x TKT plotters for the new cutting hall", "company_name": "Test Prospect Apparel",
        "contact_person": "Mr. Asif", "phone": "0300-0000000", "city": "Lahore", "source_id": source,
        "estimated_value": "5000000", "rating": "Hot", "expected_close_date": "",
        "follow_up_date": tomorrow, "follow_up_type": "Call", "follow_up_note": "Introduce the TKT range"})
    assert made.status_code == 201, made.text
    lead = made.json()
    assert lead["lead_number"].startswith("LD-") and lead["stage"] == "New"
    assert lead["next_follow_up"] == tomorrow and lead["weighted_value"] == 500000

    # The follow-up is on the list; doing it moves the lead on and plans the next one.
    upcoming = client.get(f"{API}/followups", params={"scope": "upcoming"}).json()
    follow = next(f for f in upcoming["items"] if f["lead_id"] == lead["id"])
    done = client.post(f"{API}/activities/{follow['id']}/done", json={
        "outcome": "Interested, wants a demo", "next_follow_up_date": tomorrow, "next_follow_up_type": "Visit"})
    assert done.status_code == 200, done.text
    assert done.json()["stage"] == "Contacted"

    moved = client.post(f"{API}/{lead['id']}/stage", json={"stage": "Quoted"})
    assert moved.json()["stage"] == "Quoted" and moved.json()["probability"] == 60
    assert client.post(f"{API}/{lead['id']}/stage", json={"stage": "Lost"}).status_code == 400   # needs a reason

    # Won as a new customer: the customer record is linked to the lead.
    customer = BusinessPartner(company_id=company_id, code=f"T-{uuid.uuid4().hex[:8]}", name="Test Prospect Apparel",
                               is_customer=True, is_supplier=False)
    db.add(customer)
    db.flush()
    linked = client.post(f"{API}/{lead['id']}/customer", json={"customer_id": str(customer.id)})
    assert linked.json()["customer_id"] == str(customer.id)
    won = client.post(f"{API}/{lead['id']}/stage", json={"stage": "Won"}).json()
    assert won["stage"] == "Won" and won["next_follow_up"] is None       # nothing left to chase

    summary = client.get(f"{API}/summary").json()
    assert summary["won_month_count"] >= 1
    sources = client.get(f"{API}/sources/all").json()["items"]
    assert next(s for s in sources if s["id"] == source)["won"] >= 1
    assert client.get(f"{API}/assignments").status_code == 200


def test_customer_opportunities_finds_customers_gone_quiet(client, db):
    company_id = active_company_id(db)
    client.headers["X-Company-Id"] = str(company_id)
    quiet = BusinessPartner(company_id=company_id, code=f"T-{uuid.uuid4().hex[:8]}", name="Quiet Test Mills",
                            is_customer=True, is_supplier=False)
    db.add(quiet)
    db.flush()
    db.add(SalesDocument(company_id=company_id, doc_type=SALES_ORDER, doc_number=f"T{uuid.uuid4().hex[:8]}",
                         doc_date=date.today() - timedelta(days=200), customer_id=quiet.id, status="Posted",
                         net_receivable=250000))
    db.flush()
    found = client.get(f"{API}/customer-opportunities", params={"min_days": 180, "search": "Quiet Test"}).json()
    row = found["items"][0]
    assert row["name"] == "Quiet Test Mills" and row["days_since"] == 200 and row["total_sales"] == 250000
    # A lead for an existing customer takes their details.
    made = client.post(f"{API}", json={"title": "Re-order of spare parts", "customer_id": str(quiet.id)})
    assert made.status_code == 201, made.text
    assert made.json()["company_name"] == "Quiet Test Mills" and made.json()["is_customer"]
