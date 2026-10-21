"""
Quantities may not exceed the stock on hand (owner's rule, 14-Oct-2026).

A sales order or an outward gate pass cannot ask for more of a
product than is in stock: with 4 in stock, 5 is refused. Quotations are not
checked: they may offer what is not in stock yet (owner, 16-Oct-2026). Stock on hand is the
stock ledger's balance, the same figure the product cards and the forms show.

Not checked:
  - lines with no product (typed descriptions);
  - products in the service-type main categories (services, software, CAD:
    plotting, pattern making, licences), which are not goods on a shelf;
  - a document marked as a Service order.

Only what a save asks for beyond what the document already had is checked,
so an old document can still have its remarks corrected. A document that has
already taken its goods out of stock (a posted order, an approved gate pass)
is checked for the extra quantity only, since its own goods are already off
the balance.
"""

import uuid
from collections import defaultdict
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.inventory.models import InventoryItem, MainProduct
from app.inventory.stock import IN, StockLedgerEntry

NOT_STOCKED_CATEGORIES = {"SERVICES", "SOFTWARE", "CAD"}
ZERO = Decimal("0")


def quantities(lines) -> dict[uuid.UUID, Decimal]:
    """Total quantity per product over a document's lines (objects or dicts)."""
    out: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    for line in lines:
        item_id = line.get("item_id") if isinstance(line, dict) else line.item_id
        qty = line.get("quantity") if isinstance(line, dict) else line.quantity
        if item_id:
            out[uuid.UUID(str(item_id))] += Decimal(str(qty or 0))
    return out


def check(db: Session, company_id: uuid.UUID, wanted: dict, before: dict | None = None, *,
          already_out: bool = False, recheck_all: bool = False) -> None:
    """Refuse the save when a product's quantity is above its stock.

    wanted / before: quantity per product now and before this save.
    already_out: the document's goods are already off the stock balance.
    recheck_all: check every product, not only those increased (used when a
    document is about to take its goods out, e.g. posting a draft order)."""
    before = before or {}
    ids = [i for i, q in wanted.items() if q > 0 and (recheck_all or q > before.get(i, ZERO))]
    if not ids:
        return
    items = db.execute(
        select(InventoryItem.id, InventoryItem.item_code, InventoryItem.description, MainProduct.description)
        .outerjoin(MainProduct, MainProduct.id == InventoryItem.main_product_id)
        .where(InventoryItem.id.in_(ids))).all()
    stocked = {i: (code, name) for i, code, name, category in items
               if (category or "").strip().upper() not in NOT_STOCKED_CATEGORIES}
    if not stocked:
        return
    on_hand = dict(db.execute(
        select(StockLedgerEntry.item_id,
               func.sum(case((StockLedgerEntry.direction == IN, StockLedgerEntry.quantity),
                             else_=-StockLedgerEntry.quantity)))
        .where(StockLedgerEntry.company_id == company_id, StockLedgerEntry.item_id.in_(list(stocked)))
        .group_by(StockLedgerEntry.item_id)).all())
    short = []
    for item_id, (code, name) in stocked.items():
        balance = Decimal(on_hand.get(item_id) or 0)
        asked = wanted[item_id] - (before.get(item_id, ZERO) if already_out else ZERO)
        if asked > balance:
            short.append(f"{name} ({code}): {_n(wanted[item_id])} asked, "
                         f"{_n(max(balance, ZERO) + (before.get(item_id, ZERO) if already_out else ZERO))} in stock")
    if short:
        raise HTTPException(400, "Not enough stock. " + "; ".join(short)
                            + ". Lower the quantity, or receive the stock first.")


def _n(value: Decimal) -> str:
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text
