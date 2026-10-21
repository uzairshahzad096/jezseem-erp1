"""Company isolation, branch isolation, permissions, and the API end to end.
Spec tests 15–17. Permission checks are real here (AUTH_DISABLED is forced off)."""

from datetime import date

from app.finance import journals
from tests.conftest import World, make_user

JUL = "2026-07-15"


def journal_body(world, amount="1000", branch_id=None):
    body = {"journal_date": JUL, "description": "API journal", "lines": [
        {"account_id": str(world.account("6110").id), "debit": amount, "credit": "0"},
        {"account_id": str(world.account("1110").id), "debit": "0", "credit": amount},
    ]}
    if branch_id:
        body["branch_id"] = str(branch_id)
    return body


def test_api_journal_workflow_end_to_end(client, world):
    created = client.post("/api/v1/finance/journals", json=journal_body(world))
    assert created.status_code == 201, created.text
    jid = created.json()["id"]
    assert created.json()["status"] == "DRAFT"

    for step, status in (("submit", "SUBMITTED"), ("approve", "APPROVED"), ("post", "POSTED")):
        response = client.post(f"/api/v1/finance/journals/{jid}/{step}")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status

    edit = client.put(f"/api/v1/finance/journals/{jid}", json=journal_body(world, "5"))
    assert edit.status_code == 400 and "only a draft" in edit.json()["detail"]
    assert client.delete(f"/api/v1/finance/journals/{jid}").status_code == 405

    tb = client.get("/api/v1/finance/trial-balance", params={"financial_year_id": str(world.fy.id)}).json()
    assert tb["is_balanced"] and tb["totals"]["closing_debit"] == 1000

    gl = client.get("/api/v1/finance/ledger", params={"account_id": str(world.account("1110").id)}).json()
    assert gl["closing_balance"] == -1000 and gl["rows"][0]["journal_id"] == jid

    reversed_ = client.post(f"/api/v1/finance/journals/{jid}/reverse",
                            json={"reversal_date": "2026-07-20", "reason": "wrong expense head"})
    assert reversed_.status_code == 200, reversed_.text
    assert reversed_.json()["reversed_entry"]["id"] == jid

    audit = client.get("/api/v1/finance/audit-logs", params={"entity_id": jid}).json()
    assert {"create", "submit", "approve", "post", "reverse"} <= {i["action"] for i in audit["items"]}


def test_api_rejects_unbalanced_with_readable_message(client, world):
    body = journal_body(world)
    body["lines"][1]["credit"] = "900"
    response = client.post("/api/v1/finance/journals", json=body)
    assert response.status_code == 400
    assert "not balanced" in response.json()["detail"]


def test_exports(client, world):
    for path, params in (("/api/v1/finance/trial-balance/export", {}),
                         ("/api/v1/finance/ledger/export", {"account_id": str(world.account("1110").id)})):
        for fmt in ("csv", "xlsx", "pdf"):
            response = client.get(path, params={**params, "format": fmt})
            assert response.status_code == 200, response.text
            assert "attachment" in response.headers["content-disposition"]


# 15
def test_company_isolation(client, world, db):
    other = World(db)
    # A journal in the other company…
    other_journal = journals.create(db, other.ctx(), {"journal_date": date(2026, 7, 15), "lines": [
        {"account_id": other.account("6110").id, "debit": 10, "credit": 0},
        {"account_id": other.account("1110").id, "debit": 0, "credit": 10}]})

    # …is invisible from this company.
    listing = client.get("/api/v1/finance/journals").json()
    assert other_journal.id not in {j["id"] for j in listing["items"]}
    assert client.get(f"/api/v1/finance/journals/{other_journal.id}").status_code == 404
    assert client.get(f"/api/v1/finance/accounts/{other.account('1110').id}").status_code == 404

    # An account of the other company cannot be posted to from this one.
    body = journal_body(world)
    body["lines"][0]["account_id"] = str(other.account("6110").id)
    response = client.post("/api/v1/finance/journals", json=body)
    assert response.status_code == 400 and "does not exist in this company" in response.json()["detail"]

    # A normal user without access to the other company is refused outright.
    user = make_user(db, codes=["finance.view"], company=world.company)
    client.state["user"] = user
    refused = client.get("/api/v1/finance/journals", headers={"X-Company-Id": str(other.company.id)})
    assert refused.status_code == 403


# 16
def test_branch_isolation(client, world, db):
    head_office = journals.create(db, world.ctx(), {
        "journal_date": date(2026, 7, 15), "branch_id": world.branch.id, "lines": [
            {"account_id": world.account("6110").id, "debit": 10, "credit": 0},
            {"account_id": world.account("1110").id, "debit": 0, "credit": 10}]})
    lahore = journals.create(db, world.ctx(), {
        "journal_date": date(2026, 7, 15), "branch_id": world.branch2.id, "lines": [
            {"account_id": world.account("6110").id, "debit": 20, "credit": 0},
            {"account_id": world.account("1110").id, "debit": 0, "credit": 20}]})

    user = make_user(db, codes=["finance.view", "finance.create"], company=world.company,
                     branches=[world.branch2])
    client.state["user"] = user

    visible = {j["id"] for j in client.get("/api/v1/finance/journals").json()["items"]}
    assert str(lahore.id) in visible and str(head_office.id) not in visible
    assert client.get(f"/api/v1/finance/journals/{head_office.id}").status_code == 404

    # Asking for a branch they do not hold is refused.
    assert client.get("/api/v1/finance/journals",
                      headers={"X-Branch-Id": str(world.branch.id)}).status_code == 403
    # Creating in another branch is refused; creating without one lands in theirs.
    assert client.post("/api/v1/finance/journals",
                       json=journal_body(world, branch_id=world.branch.id)).status_code == 403
    own = client.post("/api/v1/finance/journals", json=journal_body(world))
    assert own.status_code == 201 and own.json()["branch_id"] == str(world.branch2.id)


# 17
def test_permission_enforcement(client, world, db):
    viewer = make_user(db, codes=["finance.view"], company=world.company)
    client.state["user"] = viewer
    assert client.get("/api/v1/finance/journals").status_code == 200
    denied = client.post("/api/v1/finance/journals", json=journal_body(world))
    assert denied.status_code == 403 and "finance.create" in denied.json()["detail"]
    assert client.get("/api/v1/finance/trial-balance").status_code == 403       # needs finance.reports
    assert client.get("/api/v1/finance/audit-logs").status_code == 403          # needs finance.audit

    preparer = make_user(db, codes=["finance.view", "finance.create"], company=world.company)
    client.state["user"] = preparer
    jid = client.post("/api/v1/finance/journals", json=journal_body(world)).json()["id"]
    assert client.post(f"/api/v1/finance/journals/{jid}/submit").status_code == 200
    assert client.post(f"/api/v1/finance/journals/{jid}/approve").status_code == 403

    approver = make_user(db, codes=["finance.view", "finance.approve"], company=world.company)
    client.state["user"] = approver
    assert client.post(f"/api/v1/finance/journals/{jid}/approve").status_code == 200
    assert client.post(f"/api/v1/finance/journals/{jid}/post").status_code == 403

    poster = make_user(db, codes=["finance.view", "finance.post"], company=world.company)
    client.state["user"] = poster
    assert client.post(f"/api/v1/finance/journals/{jid}/post").status_code == 200
    assert client.post(f"/api/v1/finance/journals/{jid}/reverse",
                       json={"reversal_date": JUL, "reason": "test reversal"}).status_code == 403

    assert client.post("/api/v1/finance/accounts", json={
        "code": "6999", "name": "X", "account_type_id": str(world.account("6110").account_type_id),
    }).status_code == 403                                                          # needs chart_of_accounts
    period = world.period(date(2026, 8, 1))
    assert client.post(f"/api/v1/finance/periods/{period.id}/close", json={}).status_code == 403


def test_chart_of_accounts_rules(client, world):
    types = {t["code"]: t["id"] for t in client.get("/api/v1/finance/account-types").json()}
    header = str(world.account("6000").id)
    ok = client.post("/api/v1/finance/accounts", json={
        "code": "6195", "name": "Security Services", "account_type_id": types["EXPENSE"],
        "parent_id": header})
    assert ok.status_code == 201, ok.text
    wrong_type = client.post("/api/v1/finance/accounts", json={
        "code": "6196", "name": "X", "account_type_id": types["ASSET"], "parent_id": header})
    assert wrong_type.status_code == 400 and "same type" in wrong_type.json()["detail"]
    duplicate = client.post("/api/v1/finance/accounts", json={
        "code": "6195", "name": "Again", "account_type_id": types["EXPENSE"], "parent_id": header})
    assert duplicate.status_code == 400 and "already used" in duplicate.json()["detail"]
    under_posting = client.post("/api/v1/finance/accounts", json={
        "code": "6197", "name": "X", "account_type_id": types["EXPENSE"],
        "parent_id": str(world.account("6110").id)})
    assert under_posting.status_code == 400 and "header accounts" in under_posting.json()["detail"]


def test_account_with_postings_cannot_be_deleted(client, world):
    jid = client.post("/api/v1/finance/journals", json=journal_body(world)).json()["id"]
    assert jid
    response = client.delete(f"/api/v1/finance/accounts/{world.account('6110').id}")
    assert response.status_code == 400 and "Deactivate it instead" in response.json()["detail"]


def test_numbering_config_validated(client, world):
    series = {s["doc_type"]: s for s in client.get("/api/v1/finance/document-series").json()}
    jv = series["JV"]
    assert jv["next_number"] == "JV-000001"
    bad = client.put(f"/api/v1/finance/document-series/{jv['id']}", json={
        "name": "Journal Voucher", "prefix": "JV", "padding": 6, "format": "{prefix}-{seq}",
        "reset_each_fiscal_year": True, "per_branch": True})
    assert bad.status_code == 400 and "{branch}" in bad.json()["detail"]
    good = client.put(f"/api/v1/finance/document-series/{jv['id']}", json={
        "name": "Journal Voucher", "prefix": "JV", "padding": 5, "format": "{prefix}/{fy}/{seq}",
        "reset_each_fiscal_year": True, "per_branch": False})
    assert good.status_code == 200
    created = client.post("/api/v1/finance/journals", json=journal_body(world)).json()
    assert created["journal_number"] == "JV/2026-27/00001"


def test_dashboard_and_context(client, world):
    context = client.get("/api/v1/finance/context").json()
    assert context["company"]["id"] == str(world.company.id) and context["has_chart"]
    dash = client.get("/api/v1/finance/dashboard").json()
    assert dash["has_postings"] is False and dash["cash"] == 0
    jid = client.post("/api/v1/finance/journals", json=journal_body(world)).json()["id"]
    for step in ("submit", "approve", "post"):
        client.post(f"/api/v1/finance/journals/{jid}/{step}")
    dash = client.get("/api/v1/finance/dashboard").json()
    assert dash["posted_journals"] == 1
