"""
Load opening stock per location from `product_stock_location_import`.

The uploaded sheet says how much of each product sits at each location, which
is the real opening picture. It replaces the placeholder balances posted
earlier from `inventory_items.opening_stock`, which knew the quantity but not
where it was and so put everything at the main office.

    python -m app.inventory.import_stock_locations            # report only
    python -m app.inventory.import_stock_locations --apply     # write it

Products are matched in three passes, most reliable first: exact SKU, then
exact description, then description with punctuation and case stripped — the
uploaded text has picked up mangled characters in a few places ("1.6¿X"
where the item reads "1.6″X"), and those should still find their product.

Running with --apply clears any previous opening balances first, so the
figures are replaced rather than added to. Every later movement — a sale, a
gate pass, a transfer — is untouched and still applies on top.
"""

import re
import sys
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.inventory import stock
from app.inventory.models import InventoryItem, ItemLocation

# Registers the tables the inventory foreign keys point at.
from app.companies.models import Branch, Company, FinancialYear  # noqa: F401
from app.partners.models import BusinessPartner  # noqa: F401
from app.users.models import User  # noqa: F401

SOURCE_TYPE = "opening_balance"
STAGING = "product_stock_location_import"


def normalise(value: str | None) -> str:
    """A description reduced to its letters and digits, for the last-resort
    match. Punctuation is where the uploaded text differs from the item."""
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def build_index(db: Session, company_id) -> tuple[dict, dict, dict]:
    by_sku: dict[str, InventoryItem] = {}
    by_description: dict[str, InventoryItem] = {}
    by_normalised: dict[str, InventoryItem] = {}

    for item in db.scalars(
        select(InventoryItem).where(InventoryItem.company_id == company_id)
    ).all():
        if item.sku and item.sku.strip():
            by_sku.setdefault(item.sku.strip(), item)
        if item.description:
            by_description.setdefault(item.description.strip().lower(), item)
            by_normalised.setdefault(normalise(item.description), item)
    return by_sku, by_description, by_normalised


def run(db: Session, apply: bool) -> None:
    company = db.scalar(select(Company).order_by(Company.created_at))

    locations = {
        row.location.strip().lower(): row
        for row in db.scalars(
            select(ItemLocation).where(ItemLocation.company_id == company.id)
        ).all()
    }
    by_sku, by_description, by_normalised = build_index(db, company.id)

    rows = db.execute(text(
        f"select product, uom, location, qty, sku from {STAGING} order by id"
    )).all()

    matched: list[tuple] = []
    unmatched: list[tuple] = []
    no_location: list[tuple] = []
    matched_by = {"sku": 0, "description": 0, "normalised": 0}

    for product, _uom, location_name, qty, sku in rows:
        location = locations.get((location_name or "").strip().lower())
        if location is None:
            no_location.append((product, location_name))
            continue

        item = None
        if sku and sku.strip():
            item = by_sku.get(sku.strip())
            if item is not None:
                matched_by["sku"] += 1
        if item is None and product:
            item = by_description.get(product.strip().lower())
            if item is not None:
                matched_by["description"] += 1
        if item is None and product:
            item = by_normalised.get(normalise(product))
            if item is not None:
                matched_by["normalised"] += 1

        if item is None:
            unmatched.append((product, location_name, qty))
        else:
            matched.append((item, location, Decimal(str(qty or 0))))

    existing = db.scalar(
        select(func.count()).select_from(stock.StockLedgerEntry)
        .where(stock.StockLedgerEntry.source_type == SOURCE_TYPE)
    ) or 0

    print(f"{'APPLYING' if apply else 'DRY RUN - no changes will be written'}\n")
    print(f"  rows in {STAGING:32} {len(rows):5}")
    print(f"  matched to a product                      {len(matched):5}")
    print(f"    ...by SKU                               {matched_by['sku']:5}")
    print(f"    ...by description                       {matched_by['description']:5}")
    print(f"    ...by description ignoring punctuation  {matched_by['normalised']:5}")
    print(f"  no matching product                       {len(unmatched):5}")
    print(f"  no matching location                      {len(no_location):5}")
    print(f"\n  opening balances already posted           {existing:5}"
          f"{'  (these will be replaced)' if existing and apply else ''}")

    by_location: dict = {}
    for _item, location, quantity in matched:
        entry = by_location.setdefault(location.location, [0, Decimal("0")])
        entry[0] += 1
        entry[1] += quantity
    print("\n  stock to post:")
    for name, (count, quantity) in sorted(by_location.items(), key=lambda kv: -kv[1][1]):
        print(f"    {name:20} {count:4} products  {quantity:>12,.2f} units")
    print(f"    {'TOTAL':20} {len(matched):4} rows      "
          f"{sum(q for _c, q in by_location.values()):>12,.2f} units")

    if unmatched:
        print("\n  could not be matched to a product:")
        for product, location_name, quantity in unmatched[:10]:
            print(f"    {str(location_name):18} {quantity:>10}  {(product or '')[:52]}")

    if apply:
        db.execute(
            stock.StockLedgerEntry.__table__.delete().where(
                stock.StockLedgerEntry.source_type == SOURCE_TYPE)
        )
        for item, location, quantity in matched:
            if quantity == 0:
                continue
            stock.post_movement(
                db,
                company_id=company.id,
                item_id=item.id,
                direction=stock.IN,
                quantity=quantity,
                source_type=SOURCE_TYPE,
                source_number="Opening balance",
                entry_date=date.today(),
                location_id=location.id,
                remarks=f"Opening balance at {location.location}",
            )
            # File the product at the location it was counted in, so the
            # product record and the stock agree.
            if item.location_id is None:
                item.location_id = location.id
        db.commit()
        print(f"\nCommitted. {len(matched):,} opening balances posted across "
              f"{len(by_location)} locations.")
    else:
        db.rollback()
        print("\nNothing written. Re-run with --apply to commit these changes.")


if __name__ == "__main__":
    session = SessionLocal()
    try:
        run(session, apply="--apply" in sys.argv)
    finally:
        session.close()
