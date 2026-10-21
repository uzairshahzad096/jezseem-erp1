"""
One-off: put the imported opening stock into the ledger at the main location.

`inventory_items.opening_stock` holds the balance carried over from the old
ERP, but it belongs to no location — so "how much is at JEZ FSD" could not be
answered and there was nothing for a transfer to move.

All stock sits at the main office, so this posts each item's opening balance
as a single inward ledger movement there. From then on the ledger is the only
source of stock: the report stops adding `opening_stock` separately, because
the figure is now in the ledger and counting both would double it.

    python -m app.inventory.post_opening_stock --location "JEZ FSD"
    python -m app.inventory.post_opening_stock --location "JEZ FSD" --apply

Safe to think of as a starting point, not a correction: every later movement —
a sale, a gate pass, a transfer, an adjustment — is recorded on top of it.
"""

import sys
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.inventory import stock
from app.inventory.models import InventoryItem, ItemLocation

# Registers the tables the inventory foreign keys point at.
from app.companies.models import Branch, Company, FinancialYear  # noqa: F401
from app.partners.models import BusinessPartner  # noqa: F401
from app.users.models import User  # noqa: F401

SOURCE_TYPE = "opening_balance"


def argument(flag: str, default: str | None = None) -> str | None:
    if flag in sys.argv:
        index = sys.argv.index(flag)
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return default


def run(db: Session, location_name: str, apply: bool) -> None:
    company = db.scalar(select(Company).order_by(Company.created_at))
    location = db.scalar(
        select(ItemLocation).where(
            ItemLocation.company_id == company.id,
            func.lower(func.trim(ItemLocation.location)) == location_name.strip().lower(),
        )
    )
    if location is None:
        names = [r[0] for r in db.execute(
            select(ItemLocation.location).where(ItemLocation.company_id == company.id)
        ).all()]
        print(f"No location called {location_name!r}. Known locations: {names}")
        return

    already = db.scalar(
        select(func.count()).select_from(stock.StockLedgerEntry)
        .where(stock.StockLedgerEntry.source_type == SOURCE_TYPE)
    ) or 0
    if already:
        print(f"Opening balances have already been posted ({already} entries). "
              "Nothing to do — posting again would double the stock.")
        return

    items = list(db.scalars(
        select(InventoryItem).where(
            InventoryItem.company_id == company.id,
            InventoryItem.opening_stock.is_not(None),
            InventoryItem.opening_stock > 0,
        ).order_by(InventoryItem.item_code)
    ).all())

    total = sum((Decimal(str(i.opening_stock)) for i in items), Decimal("0"))

    print(f"{'APPLYING' if apply else 'DRY RUN - no changes will be written'}\n")
    print(f"  location          : {location.location}")
    print(f"  products with stock: {len(items):,}")
    print(f"  total units        : {total:,.2f}")
    print("\n  first five:")
    for item in items[:5]:
        print(f"    {item.item_code:16} {Decimal(str(item.opening_stock)):>10,.2f}  "
              f"{(item.description or '')[:46]}")

    if apply:
        for item in items:
            stock.post_movement(
                db,
                company_id=company.id,
                item_id=item.id,
                direction=stock.IN,
                quantity=Decimal(str(item.opening_stock)),
                source_type=SOURCE_TYPE,
                source_number="Opening balance",
                entry_date=date.today(),
                location_id=location.id,
                remarks=f"Opening balance carried over to {location.location}",
            )
        db.commit()
        print(f"\nCommitted. {len(items):,} opening movements posted at {location.location}.")
    else:
        db.rollback()
        print("\nNothing written. Re-run with --apply to commit these changes.")


if __name__ == "__main__":
    session = SessionLocal()
    try:
        run(session, argument("--location", "JEZ FSD"), apply="--apply" in sys.argv)
    finally:
        session.close()
