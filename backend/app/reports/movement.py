"""
Stock movement analysis: which products keep selling, which are dead, and
which need restocking.

A sale is a line on a POSTED sales order ("Un-Posted" and draft orders are
not sales). Quotations never count. Every figure is computed from those
lines and the stock ledger; nothing is stored.

Movement, per product (the period is chosen on screen, default: the current
financial year to date):

  REPEAT      sold on `repeat_min` (default 3) or more separate orders in the period
  OCCASIONAL  sold on 1 or 2 orders in the period
  SLOW        not sold in the period, but sold within the last `dead_days` (default 365)
  DEAD        in stock, and not sold for `dead_days` or more, or never sold
  INACTIVE    no stock and no sale within `dead_days`: nothing to act on

Restock is measured against the stock that was last added. The "added level"
is the quantity on hand right after the most recent addition (opening balance
or goods receipt): had 5, received 95, the added level is 100. A product is
flagged when what remains is `restock_percent` (default 40) of that level or
less: 40 of 100 left, restock. Receipts that were later reversed do not count
as additions, and transfers between locations are not additions.

A product with no addition on record has no level to compare with. Its stock
is then nil, so it shows 0% left, but it is flagged only when it actually sells (REPEAT, OCCASIONAL
or SLOW). Thousands of catalogue items have no stock and have never sold;
flagging them all would bury the products that matter. Services and software
(by main product category) are never flagged.

Priority is HIGH for repeat sellers, MEDIUM for occasional and LOW for
everything else. The suggested quantity refills to the added level, or to
`cover_months` (default 2) of the product's average monthly sales over the
last 12 months if that is more.
"""

import math
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from app.companies.models import FinancialYear
from app.inventory import stock
from app.inventory.models import InventoryItem, InventorySubCategory, ItemLocation, MainProduct
from app.sales.models import SALES_ORDER, SalesDocument, SalesDocumentLine

SOLD_STATUSES = ("Posted", "Delivered")
MOVEMENTS = ["REPEAT", "OCCASIONAL", "SLOW", "DEAD", "INACTIVE"]
MOVEMENT_LABELS = {
    "REPEAT": "Repeat seller", "OCCASIONAL": "Occasional", "SLOW": "Slow mover",
    "DEAD": "Dead stock", "INACTIVE": "Inactive",
}
PRIORITY = {"REPEAT": "HIGH", "OCCASIONAL": "MEDIUM", "SLOW": "LOW"}
#: Ledger movements that add stock. Transfers only move it between locations.
ADDITIONS = {"opening_balance", "opening", "goods_receipt"}
#: Main product categories that are not held in stock. They still show their
#: movement (a service sold on many orders is a repeat seller), but they are
#: never flagged for restocking.
NON_STOCK_CATEGORIES = {"SERVICES", "SOFTWARE"}


@dataclass
class Settings:
    period_from: date
    period_to: date
    period_label: str
    repeat_min: int = 3
    dead_days: int = 365
    restock_percent: float = 40
    cover_months: float = 2


def resolve_period(db: Session, company_id: uuid.UUID, period: str, date_from: date | None,
                   date_to: date | None, today: date | None = None) -> tuple[date, date, str]:
    today = today or date.today()
    if period == "custom" and date_from:
        end = date_to or today
        return date_from, end, f"{date_from:%d-%b-%Y} to {end:%d-%b-%Y}"
    if period == "calendar":
        return date(today.year, 1, 1), today, f"Calendar year {today.year} to date"
    if period == "last12":
        return today - timedelta(days=365), today, "Last 12 months"
    fy = db.scalar(select(FinancialYear).where(FinancialYear.company_id == company_id,
                                               FinancialYear.is_current.is_(True)))
    if fy is not None:
        start = date.fromisoformat(fy.start_date)
        return start, today, f"Financial year {fy.name} to date"
    return date(today.year, 1, 1), today, f"Calendar year {today.year} to date"


def _sales(db: Session, company_id: uuid.UUID, start: date, end: date) -> dict:
    """Per item: separate orders, quantity, customers and value in [start, end]."""
    rows = db.execute(
        select(SalesDocumentLine.item_id,
               func.count(func.distinct(SalesDocument.id)),
               func.sum(SalesDocumentLine.quantity),
               func.count(func.distinct(SalesDocument.customer_id)),
               func.sum(SalesDocumentLine.taxable_amount))
        .join(SalesDocument, SalesDocument.id == SalesDocumentLine.document_id)
        .where(SalesDocument.company_id == company_id, SalesDocument.doc_type == SALES_ORDER,
               SalesDocument.status.in_(SOLD_STATUSES), SalesDocumentLine.item_id.is_not(None),
               SalesDocument.doc_date >= start, SalesDocument.doc_date <= end)
        .group_by(SalesDocumentLine.item_id)).all()
    return {r[0]: {"orders": int(r[1]), "qty": float(r[2] or 0), "customers": int(r[3]),
                   "value": float(r[4] or 0)} for r in rows}


def _last_sale(db: Session, company_id: uuid.UUID) -> dict:
    rows = db.execute(
        select(SalesDocumentLine.item_id, func.max(SalesDocument.doc_date), func.count(func.distinct(SalesDocument.id)))
        .join(SalesDocument, SalesDocument.id == SalesDocumentLine.document_id)
        .where(SalesDocument.company_id == company_id, SalesDocument.doc_type == SALES_ORDER,
               SalesDocument.status.in_(SOLD_STATUSES), SalesDocumentLine.item_id.is_not(None))
        .group_by(SalesDocumentLine.item_id)).all()
    return {r[0]: (r[1], int(r[2])) for r in rows}


def _added_levels(db: Session, company_id: uuid.UUID, location_id=None) -> dict:
    """Per item: (stock on hand right after the latest addition, its date).

    Additions on the same day count together, before that day's other
    movements: opening 5 and a receipt of 95 on one day make a level of 100.
    A movement that was reversed nets to nothing, so it and its reversal are
    both left out.
    """
    ledger = stock.StockLedgerEntry
    stmt = select(ledger.item_id, ledger.entry_date, ledger.direction, ledger.quantity,
                  ledger.source_type, ledger.source_id).where(ledger.company_id == company_id)
    if location_id:
        stmt = stmt.where(ledger.location_id == location_id)
    entries = db.execute(stmt).all()
    reversed_ids = {e.source_id for e in entries if e.source_type.endswith("_reversal") and e.source_id}
    by_item: dict = {}
    for e in entries:
        if e.source_id in reversed_ids:
            continue
        by_item.setdefault(e.item_id, []).append(e)

    levels = {}
    for item_id, rows in by_item.items():
        added_on = max((e.entry_date for e in rows if e.direction == stock.IN and e.source_type in ADDITIONS),
                       default=None)
        if added_on is None:
            continue
        before = sum((e.quantity if e.direction == stock.IN else -e.quantity)
                     for e in rows if e.entry_date < added_on)
        added = sum(e.quantity for e in rows if e.entry_date == added_on
                    and e.direction == stock.IN and e.source_type in ADDITIONS)
        level = float(before + added)
        if level > 0:
            levels[item_id] = (level, added_on)
    return levels


def analyse(db: Session, company_id: uuid.UUID, cfg: Settings, *, search: str | None = None,
            main_product_id=None, sub_category_id=None, location_id=None, today: date | None = None) -> list[dict]:
    """One row per product with stock, sales and movement figures."""
    today = today or date.today()
    by_location = stock.stock_balances_by_location(db, company_id, location_id)
    balances: dict = {}
    where_held: dict = {}
    locations = dict(db.execute(select(ItemLocation.id, ItemLocation.location)
                                .where(ItemLocation.company_id == company_id)).all())
    for (item_id, loc_id), quantity in by_location.items():
        balances[item_id] = balances.get(item_id, 0.0) + float(quantity)
        if quantity:
            where_held.setdefault(item_id, []).append(locations.get(loc_id) or "Unassigned")

    stmt = select(InventoryItem).where(InventoryItem.company_id == company_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(InventoryItem.description.ilike(like), InventoryItem.item_code.ilike(like)))
    if main_product_id:
        stmt = stmt.where(InventoryItem.main_product_id == main_product_id)
    if sub_category_id:
        stmt = stmt.where(InventoryItem.sub_category_id == sub_category_id)
    if location_id:
        held = [i for (i, _l) in by_location]
        stmt = stmt.where(or_(InventoryItem.id.in_(held) if held else false(),
                              InventoryItem.location_id == location_id))
    items = db.scalars(stmt).all()

    period = _sales(db, company_id, cfg.period_from, cfg.period_to)
    year = _sales(db, company_id, today - timedelta(days=365), today)
    last = _last_sale(db, company_id)
    added_levels = _added_levels(db, company_id, location_id)
    dead_after = today - timedelta(days=cfg.dead_days)
    mp = dict(db.execute(select(MainProduct.id, MainProduct.description)).all())
    sc = dict(db.execute(select(InventorySubCategory.id, InventorySubCategory.description)).all())

    rows = []
    for item in items:
        qty = round(balances.get(item.id, 0.0), 4)
        p = period.get(item.id, {"orders": 0, "qty": 0.0, "customers": 0, "value": 0.0})
        last_date, lifetime_orders = last.get(item.id, (None, 0))
        sold_recently = last_date is not None and last_date >= dead_after

        if p["orders"] >= cfg.repeat_min:
            movement = "REPEAT"
        elif p["orders"] > 0:
            movement = "OCCASIONAL"
        elif sold_recently:
            movement = "SLOW"
        elif qty > 0:
            movement = "DEAD"
        else:
            movement = "INACTIVE"

        monthly = year.get(item.id, {"qty": 0.0})["qty"] / 12
        stock_item = (mp.get(item.main_product_id) or "").strip().upper() not in NON_STOCK_CATEGORIES
        added_level, added_on = added_levels.get(item.id, (None, None))
        if added_level:
            remaining_pct = round(max(qty, 0) / added_level * 100, 1)
        else:
            # Nothing added on record. Stock only arrives through additions,
            # so this is (almost always) an empty shelf: nothing is left,
            # whatever the original amount was.
            remaining_pct = 0.0 if qty <= 0 else None
        if not stock_item:
            restock, reason = False, None
        elif added_level:
            restock = remaining_pct <= cfg.restock_percent
            reason = f"{remaining_pct:g}% of {added_level:g} left" if restock else None
        else:
            restock = movement in PRIORITY and qty <= 0
            reason = "Out of stock, no stock added on record" if restock else None
        refill_to = added_level or 1
        target = max(refill_to, math.ceil(monthly * cfg.cover_months)) if restock else 0
        rows.append({
            "item_id": str(item.id), "item_code": item.item_code, "description": item.description,
            "uom": item.uom, "main_product": mp.get(item.main_product_id),
            "sub_category": sc.get(item.sub_category_id), "item_status": item.item_status,
            "quantity": qty,
            "location": ", ".join(sorted(where_held.get(item.id, []))) or locations.get(item.location_id),
            "stock_location": ", ".join(sorted(where_held.get(item.id, []))) or None,
            "assigned_location": locations.get(item.location_id),
            "min_level": float(item.min_level or 0), "re_order_qty": float(item.re_order_qty or 0),
            "below_reorder": bool(item.re_order_qty) and qty < float(item.re_order_qty or 0),
            "movement": movement, "movement_label": MOVEMENT_LABELS[movement],
            "orders_in_period": p["orders"], "qty_sold_in_period": round(p["qty"], 4),
            "customers_in_period": p["customers"], "sales_value_in_period": round(p["value"], 2),
            "last_sold": last_date, "days_since_sale": (today - last_date).days if last_date else None,
            "lifetime_orders": lifetime_orders, "avg_monthly_qty": round(monthly, 2),
            "stock_item": stock_item,
            "added_level": added_level, "added_on": added_on, "remaining_pct": remaining_pct,
            "restock": restock, "restock_reason": reason,
            "restock_priority": PRIORITY.get(movement, "LOW") if restock else None,
            "suggested_restock_qty": max(0, math.ceil(target - qty)) if restock else 0,
            "stock_value_basis": float(item.price or 0),
        })
    return rows


def summary(rows: list[dict]) -> dict:
    counts = {m: 0 for m in MOVEMENTS}
    for r in rows:
        counts[r["movement"]] += 1
    dead = [r for r in rows if r["movement"] == "DEAD"]
    restock = [r for r in rows if r["restock"]]
    return {
        "counts": counts,
        "dead_quantity": round(sum(r["quantity"] for r in dead), 2),
        "dead_list_value": round(sum(r["quantity"] * r["stock_value_basis"] for r in dead), 2),
        "restock_total": len(restock),
        "restock_high": sum(1 for r in restock if r["restock_priority"] == "HIGH"),
        "restock_medium": sum(1 for r in restock if r["restock_priority"] == "MEDIUM"),
        "restock_low": sum(1 for r in restock if r["restock_priority"] == "LOW"),
        "top_repeat": sorted((r for r in rows if r["movement"] == "REPEAT"),
                             key=lambda r: (-r["orders_in_period"], -r["qty_sold_in_period"]))[:10],
    }
