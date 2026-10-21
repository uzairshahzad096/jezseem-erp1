"""
Test fixtures.

The tests run against the real PostgreSQL database named in .env, because
the rules that matter most (balance, immutability, closed periods) are
enforced by PostgreSQL triggers that SQLite could not run. Each test runs
inside one outer transaction that is rolled back at the end: the code under
test may commit as often as it likes (each commit only releases a savepoint)
and nothing it writes survives the test.

Every test builds its own company, branch and financial year, so it never
reads or depends on the ERP's real data.
"""

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import app.main  # noqa: F401 — registers every model and route
from app.audit.service import AuditContext
from app.auth.dependencies import get_current_user
from app.companies.models import Branch, Company, FinancialYear
from app.core.config import settings
from app.core.database import engine, get_db

from sqlalchemy.engine import make_url

# Safety: automated tests must use the isolated test database.
_test_database = make_url(settings.DATABASE_URL).database

if _test_database != "jezseem_erp_test":
    raise RuntimeError(
        "Tests blocked: DATABASE_URL must point to "
        "jezseem_erp_test, not the main ERP database."
    )

from app.finance.context import FinanceContext
from app.finance.setup import install_defaults
from app.partners.models import BusinessPartner
from app.users.models import Permission, Role, User, user_branch_access, user_company_access


@pytest.fixture
def db():
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint",
                      autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


def make_user(db: Session, *, superuser: bool = False, codes: list[str] | None = None,
              company: Company | None = None, branches: list[Branch] | None = None) -> User:
    tag = uuid.uuid4().hex[:8]
    user = User(username=f"test-{tag}", email=f"{tag}@test.local", full_name=f"Test {tag}",
                hashed_password="x", is_active=True, is_superuser=superuser)
    db.add(user)
    db.flush()
    if codes is not None:
        role = Role(name=f"Role {tag}", company_id=company.id if company else None)
        role.permissions = list(db.query(Permission).filter(Permission.code.in_(codes)))
        user.roles = [role]
        db.add(role)
    if company is not None:
        db.execute(user_company_access.insert().values(user_id=user.id, company_id=company.id))
    for branch in branches or []:
        db.execute(user_branch_access.insert().values(user_id=user.id, branch_id=branch.id))
    db.flush()
    return user


class World:
    """A throwaway company with the standard finance setup."""

    def __init__(self, db: Session):
        tag = uuid.uuid4().hex[:6].upper()
        self.db = db
        self.company = Company(name=f"Test Co {tag}", code=f"T{tag}", default_currency="PKR")
        db.add(self.company)
        db.flush()
        self.branch = Branch(company_id=self.company.id, name="Head Office", code="HO")
        self.branch2 = Branch(company_id=self.company.id, name="Lahore", code="LHR")
        self.fy = FinancialYear(company_id=self.company.id, name="2026-27",
                                start_date="2026-07-01", end_date="2027-06-30", is_current=True)
        db.add_all([self.branch, self.branch2, self.fy])
        db.flush()
        self.admin = make_user(db, superuser=True)
        self.audit = AuditContext.for_user(self.admin)
        install_defaults(db, self.company.id, self.audit)
        self.customer = BusinessPartner(company_id=self.company.id, code="C001", name="Alpha Traders",
                                        is_customer=True, is_supplier=False)
        self.customer2 = BusinessPartner(company_id=self.company.id, code="C002", name="Beta Mills",
                                         is_customer=True, is_supplier=False)
        self.supplier = BusinessPartner(company_id=self.company.id, code="S001", name="Gamma Supplies",
                                        is_customer=False, is_supplier=True)
        db.add_all([self.customer, self.customer2, self.supplier])
        db.flush()

    def ctx(self, user: User | None = None, branch_ids=None, branch_id=None) -> FinanceContext:
        user = user or self.admin
        return FinanceContext(company_id=self.company.id, user=user,
                              audit=AuditContext.for_user(user),
                              branch_id=branch_id, branch_ids=branch_ids)

    def account(self, code: str):
        from sqlalchemy import select
        from app.finance.models import Account
        return self.db.scalar(select(Account).where(Account.company_id == self.company.id,
                                                    Account.code == code))

    def period(self, on: date):
        from app.finance.periods import period_for_date
        return period_for_date(self.db, self.company.id, on)


@pytest.fixture
def world(db) -> World:
    return World(db)


@pytest.fixture
def client(db, world, monkeypatch):
    """API client acting as the world's superuser, scoped to its company."""
    state = {"user": world.admin}
    app.main.app.dependency_overrides[get_db] = lambda: db
    app.main.app.dependency_overrides[get_current_user] = lambda: state["user"]
    # Permission checks are real in tests even though .env disables them
    # for development.
    monkeypatch.setattr(settings, "AUTH_DISABLED", False)
    test_client = TestClient(app.main.app, raise_server_exceptions=True)
    test_client.headers["X-Company-Id"] = str(world.company.id)
    test_client.state = state
    try:
        yield test_client
    finally:
        app.main.app.dependency_overrides.clear()
