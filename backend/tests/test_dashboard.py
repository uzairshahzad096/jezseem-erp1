"""The home dashboard's figures come back, from each module's own records."""

from app.inventory.router import active_company_id


def test_dashboard_overview(client, db):
    client.headers["X-Company-Id"] = str(active_company_id(db))
    r = client.get("/api/v1/dashboard/overview")
    assert r.status_code == 200, r.text
    d = r.json()
    for key in ("sales_month", "sales_year", "receivables", "cash", "bank", "stock_value", "pipeline", "customers_month"):
        assert key in d["kpis"]
    assert len(d["sales_trend"]) == 12
    assert {t["key"] for t in d["todo"]} >= {"followups_overdue", "quotes_waiting", "po_open", "costings", "contracts_to_bill"}


def test_business_figures_only_for_selected_users(client, db):
    """A Staff login sees the simple dashboard — no sales or money anywhere in it —
    until it is ticked for the business dashboard."""
    import uuid
    from app.users.models import User
    client.headers["X-Company-Id"] = str(active_company_id(db))
    tag = uuid.uuid4().hex[:6]
    made = client.post("/api/v1/security/users", json={
        "username": f"staff{tag}", "full_name": "Staff Test", "email": f"staff{tag}@test.local",
        "password": "longenough1", "role": "Staff", "business_dashboard": False})
    assert made.status_code == 201, made.text
    assert made.json()["business_dashboard"] is False
    staff = db.get(User, uuid.UUID(made.json()["id"]))

    admin = client.state["user"]
    client.state["user"] = staff
    d = client.get("/api/v1/dashboard/overview").json()
    assert d["mode"] == "simple" and d["can_see_business"] is False
    assert "kpis" not in d and "top_customers" not in d and "owing" not in d
    client.state["user"] = admin

    ticked = client.put(f"/api/v1/security/users/{staff.id}", json={
        "full_name": "Staff Test", "email": f"staff{tag}@test.local", "role": "Staff", "business_dashboard": True})
    assert ticked.status_code == 200 and ticked.json()["business_dashboard"] is True
    db.refresh(staff)
    client.state["user"] = staff
    assert client.get("/api/v1/dashboard/overview").json()["mode"] == "business"
    # Anyone can still look at the simple one.
    assert client.get("/api/v1/dashboard/overview", params={"view": "simple"}).json()["mode"] == "simple"
    client.state["user"] = admin
