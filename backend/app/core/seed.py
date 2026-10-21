"""
First-run seed: permission catalogue, Administrator role, first company,
branch, financial year and the initial superuser.

Run once after migrations:

    docker compose exec backend python -m app.core.seed

Credentials are taken from the environment, never hard-coded:

    SEED_ADMIN_USERNAME, SEED_ADMIN_EMAIL, SEED_ADMIN_PASSWORD

The script is idempotent — running it again adds any missing permissions
without duplicating existing records. An existing admin's password is left
alone unless you explicitly ask for it:

    docker compose exec backend python -m app.core.seed --reset-password
"""

import os
import sys
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.companies.models import Branch, Company, FinancialYear
from app.core.database import SessionLocal
from app.users.models import Permission, Role, User

# The nine ERP modules and the submodules currently defined in the frontend
# navigation. Keep this in step with frontend/lib/navigation.ts.
MODULES: dict[str, list[str]] = {
    "dashboard": ["view", "analytics", "management", "business"],
    "security": ["users", "roles", "permissions", "audit", "logins"],
    "finance": ["accounts", "journals", "invoices", "payments", "reports"],
    "leads": ["view", "assignments", "sources", "followups"],
    "crm": ["customers", "contacts", "opportunities", "activities"],
    "inventory": [
        # Setup Forms — confirmed from the existing ERP
        "racks", "locations", "main_products", "sub_categories",
        "sub_detail_categories", "items",
        # Transactions / In-house Orders / Reports — screens not yet discovered
        "transactions", "inhouse_orders", "reports",
        # Transactions — confirmed from the requirements document
        "gate_passes",
    ],
    "sales": ["quotations", "orders", "documents"],
    "procurement": [
        # The procurement chain: requirement, order, shipment, costing, receipt.
        "in_house_orders", "purchase_orders", "shipments", "landed_costs",
        "goods_receipts",
        # Kept so permissions granted against the earlier name still resolve.
        "mrn",
    ],
    "partners": ["customers", "suppliers", "contacts"],
    "projects": ["view", "tasks", "members", "documents"],
    "communication": ["messages", "notices", "announcements"],
    "hrms": ["employees", "attendance", "leave", "payroll", "setup", "loans"],
    "calibration": ["requests", "technicians", "due", "reports",
                    # The previous ERP's screens (migration 0019).
                    "machines", "customer_machines", "contracts", "invoices", "definitions"],
    "admin": ["companies", "branches", "financial_years", "settings"],
}

ACTIONS = ["view", "create", "edit", "delete", "approve", "post", "cancel", "export", "print"]

#: Finance Phase 1 permissions. Named in the finance spec rather than built
#: from MODULES × ACTIONS, because reverse, close_period and opening_balance
#: are not actions every module has. Migration 0008 inserts the same codes.
FINANCE_CODES: list[tuple[str, str]] = [
    ("view", "finance.view"), ("create", "finance.create"), ("edit", "finance.edit"),
    ("post", "finance.post"), ("approve", "finance.approve"), ("reverse", "finance.reverse"),
    ("close_period", "finance.close_period"), ("opening_balance", "finance.opening_balance"),
    ("chart_of_accounts", "finance.chart_of_accounts"), ("reports", "finance.reports"),
    ("audit", "finance.audit"),
]

#: Finance Phase 2: sales invoices and receivables. Migration 0009 inserts the same codes.
AR_CODES: list[tuple[str, str, str]] = [
    ("sales", "view", "sales.invoice.view"), ("sales", "create", "sales.invoice.create"),
    ("sales", "edit", "sales.invoice.edit"), ("sales", "confirm", "sales.invoice.confirm"),
    ("sales", "post", "sales.invoice.post"), ("sales", "cancel", "sales.invoice.cancel"),
    ("sales", "credit_approve", "sales.invoice.credit_approve"),
    ("ar", "view", "ar.view"), ("ar", "create", "ar.receipt.create"), ("ar", "post", "ar.receipt.post"),
    ("ar", "allocate", "ar.receipt.allocate"), ("ar", "reverse", "ar.receipt.reverse"),
    ("ar", "create", "ar.credit_note.create"), ("ar", "post", "ar.credit_note.post"),
    ("ar", "reverse", "ar.credit_note.reverse"), ("ar", "reports", "ar.reports"),
    ("ar", "settings", "ar.settings"),
]


def build_permission_codes() -> list[tuple[str, str, str]]:
    """Returns (module, action, code) triples for the whole catalogue."""
    codes: list[tuple[str, str, str]] = []
    for module, submodules in MODULES.items():
        codes.append((module, "view", f"{module}.module.view"))
        for sub in submodules:
            for action in ACTIONS:
                codes.append((module, action, f"{module}.{sub}.{action}"))
    codes.extend(("finance", action, code) for action, code in FINANCE_CODES)
    codes.extend(AR_CODES)
    return codes


def seed_permissions(db: Session) -> list[Permission]:
    existing = {p.code for p in db.scalars(select(Permission)).all()}
    created = 0
    for module, action, code in build_permission_codes():
        if code in existing:
            continue
        db.add(Permission(id=uuid.uuid4(), module=module, action=action, code=code))
        created += 1
    db.commit()
    print(f"  permissions: {created} added, {len(existing)} already present")
    return db.scalars(select(Permission)).all()
def seed_roles_and_lead_sources(
    db: Session,
    company: Company,
    permissions: list[Permission],
) -> None:
    """Initialize default roles and lead sources without duplicates."""

    dashboard_code = "dashboard.business.view"

    role_definitions = [
        (
            "Staff",
            "Every module except business dashboard figures and Security screens.",
        ),
        (
            "Business Dashboard",
            "Can view business figures on the home dashboard.",
        ),
    ]

    for name, description in role_definitions:
        role = db.scalar(
            select(Role).where(
                Role.company_id == company.id,
                Role.name == name,
            )
        )

        if role is None:
            role = Role(
                id=uuid.uuid4(),
                company_id=company.id,
                name=name,
                description=description,
                is_system_role=True,
            )
            db.add(role)
            db.flush()

        if name == "Staff":
            allowed = [
                permission
                for permission in permissions
                if permission.code != dashboard_code
                and not permission.code.startswith("security.")
            ]
        else:
            allowed = [
                permission
                for permission in permissions
                if permission.code == dashboard_code
            ]

        # Preserve existing assignments and add any missing defaults.
        existing_ids = {permission.id for permission in role.permissions}

        for permission in allowed:
            if permission.id not in existing_ids:
                role.permissions.append(permission)

        print(f"  role: {name} initialized")

    from app.leads.models import LeadSource

    default_sources = [
        "Website",
        "Referral",
        "Existing Customer",
        "Exhibition",
        "Cold Call",
        "WhatsApp / Phone",
        "Social Media",
        "Walk-in",
    ]

    existing_sources = set(
        db.scalars(
            select(LeadSource.name).where(
                LeadSource.company_id == company.id
            )
        ).all()
    )

    added = 0

    for order, name in enumerate(default_sources, start=1):
        if name in existing_sources:
            continue

        db.add(
            LeadSource(
                id=uuid.uuid4(),
                company_id=company.id,
                name=name,
                is_active=True,
                sort_order=order * 10,
            )
        )
        added += 1

    db.commit()
    print(f"  lead sources: {added} added")


def seed(db: Session) -> None:
    username = os.getenv("SEED_ADMIN_USERNAME", "admin")
    email = os.getenv("SEED_ADMIN_EMAIL", "admin@jezseem.local")
    password = os.getenv("SEED_ADMIN_PASSWORD")

    if not password:
        print(
            "ERROR: SEED_ADMIN_PASSWORD is not set.\n"
            "Add it to your .env file, then run this command again.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if len(password) < 10:
        print("ERROR: SEED_ADMIN_PASSWORD must be at least 10 characters.", file=sys.stderr)
        raise SystemExit(1)

    print("Seeding Jezseem ERP…")
    permissions = seed_permissions(db)

    company = db.scalar(select(Company).where(Company.code == "JEZ"))
    if not company:
        company = Company(
            id=uuid.uuid4(),
            name="Jezseem Traders",
            code="JEZ",
            legal_name="Jezseem Traders",
            default_currency="PKR",
        )
        db.add(company)
        db.commit()
        print("  company: Jezseem Traders created")
    else:
        print("  company: already present")

    if not db.scalar(select(Branch).where(Branch.company_id == company.id)):
        db.add(Branch(id=uuid.uuid4(), company_id=company.id, name="Head Office", code="HO"))
        db.commit()
        print("  branch: Head Office created")

    if not db.scalar(select(FinancialYear).where(FinancialYear.company_id == company.id)):
        # REQUIRES BUSINESS CONFIRMATION: the real financial-year start month
        # for Jezseem Traders. July–June is assumed here as the common
        # Pakistani fiscal year and must be verified before go-live.
        today = date.today()
        start_year = today.year if today.month >= 7 else today.year - 1
        db.add(
            FinancialYear(
                id=uuid.uuid4(),
                company_id=company.id,
                name=f"{start_year}-{str(start_year + 1)[2:]}",
                start_date=f"{start_year}-07-01",
                end_date=f"{start_year + 1}-06-30",
                is_current=True,
            )
        )
        db.commit()
        print("  financial year created (REQUIRES BUSINESS CONFIRMATION)")

    role = db.scalar(select(Role).where(Role.name == "Administrator"))
    if not role:
        role = Role(
            id=uuid.uuid4(),
            name="Administrator",
            description="Full access to every module.",
            is_system_role=True,
            company_id=company.id,
        )
        db.add(role)
        db.commit()
    role.permissions = permissions
    db.commit()
    print(f"  role: Administrator holds {len(permissions)} permissions")
    seed_roles_and_lead_sources(db, company, permissions)

    # Finance structure only: numbering, the standard chart if there is none,
    # posting rules and periods. No balance or journal is ever seeded.
    from app.finance.setup import install_defaults
    result = install_defaults(db, company.id, None)
    db.commit()
    print(f"  finance: {result['accounts_added']} accounts, {result['series_added']} numbering series, "
          f"{result['periods_generated']} periods added")

    reset_password = "--reset-password" in sys.argv
    user = db.scalar(select(User).where(User.username == username))
    if user and reset_password:
        user.hashed_password = hash_password(password)
        user.is_active = True
        if role not in user.roles:
            user.roles.append(role)
        db.commit()
        print(f"  user: '{username}' password reset from SEED_ADMIN_PASSWORD")
    elif user:
        print(
            f"  user: '{username}' already exists — password NOT changed.\n"
            f"        To apply a new SEED_ADMIN_PASSWORD, re-run with:\n"
            f"        python -m app.core.seed --reset-password"
        )
    else:
        user = User(
            id=uuid.uuid4(),
            username=username,
            email=email,
            full_name="System Administrator",
            hashed_password=hash_password(password),
            is_active=True,
            is_superuser=True,
        )
        user.roles = [role]
        db.add(user)
        db.commit()
        print(f"  user: '{username}' created")

    print("\nDone. Sign in at http://localhost:3000 with that username.")


if __name__ == "__main__":
    session = SessionLocal()
    try:
        seed(session)
    finally:
        session.close()
