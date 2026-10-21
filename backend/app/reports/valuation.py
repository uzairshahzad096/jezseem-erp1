"""
What a product actually cost to get into inventory, and what its stock is worth.

The stock ledger already records the cost every unit came in at: the purchase
price on a local receipt, and the **landed** cost on an import — supplier
invoice plus freight, duty, taxes, port, clearing and bank charges, spread
across the goods. This reads those movements back.

Cost is a weighted average of the costed receipts:

    sum(quantity x unit cost) / sum(quantity)

chosen because it is what the ledger can actually support — FIFO would need
each issue matched to a specific receipt, which nothing in this system records —
and because it is the method a trading business reconciles most easily.

One honesty rule runs through the whole module. The 26,159 units carried over
from the old ERP arrived as opening balances with **no cost at all**, and a
product whose stock is entirely opening balance has no known cost. Those are
reported as unknown, never as zero: a zero cost silently understates stock and
is the kind of figure that ends up in a set of accounts.
"""

import uuid
from decimal import Decimal

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session

from app.inventory import stock
from app.inventory.models import (
    InventoryItem, InventorySubCategory, ItemLocation, MainProduct,
)
from app.partners.models import BusinessPartner
from app.procurement import models as pm

ZERO = Decimal("0")

#: Movements that bring goods in at a known cost. An opening balance carries
#: no cost, and a transfer only moves stock that was already costed.
COSTED_SOURCES = ("goods_receipt",)


def _balances(db: Session, company_id: uuid.UUID,
              location_id: uuid.UUID | None = None) -> dict[uuid.UUID, Decimal]:
    """On-hand quantity per product, from the ledger."""
    e = stock.StockLedgerEntry
    stmt = (
        select(e.item_id, func.coalesce(func.sum(
            case((e.direction == stock.IN, e.quantity), else_=-e.quantity)), 0))
        .where(e.company_id == company_id)
        .group_by(e.item_id)
    )
    if location_id:
        stmt = stmt.where(e.location_id == location_id)
    return {item_id: Decimal(str(qty)) for item_id, qty in db.execute(stmt).all()}


def _costs(db: Session, company_id: uuid.UUID) -> dict[uuid.UUID, dict]:
    """Weighted average cost per product, from its costed receipts."""
    e = stock.StockLedgerEntry
    rows = db.execute(
        select(
            e.item_id,
            func.sum(e.quantity).label("quantity"),
            func.sum(e.quantity * e.unit_cost).label("value"),
            func.min(e.unit_cost).label("lowest"),
            func.max(e.unit_cost).label("highest"),
            func.count().label("receipts"),
            func.max(e.entry_date).label("last_date"),
        )
        .where(
            e.company_id == company_id,
            e.direction == stock.IN,
            e.source_type.in_(COSTED_SOURCES),
            e.unit_cost.is_not(None),
            e.unit_cost > 0,
        )
        .group_by(e.item_id)
    ).all()

    out: dict[uuid.UUID, dict] = {}
    for row in rows:
        quantity = Decimal(str(row.quantity or 0))
        value = Decimal(str(row.value or 0))
        out[row.item_id] = {
            "costed_quantity": quantity,
            "costed_value": value,
            "average_cost": (value / quantity) if quantity else ZERO,
            "lowest_cost": Decimal(str(row.lowest or 0)),
            "highest_cost": Decimal(str(row.highest or 0)),
            "receipts": row.receipts,
            "last_costed_on": row.last_date,
        }
    return out


def _last_receipt(db: Session, company_id: uuid.UUID) -> dict[uuid.UUID, dict]:
    """The most recent costed receipt per product, and where it came from —
    which is what says whether a cost is a landed import cost or a local
    purchase price."""
    e = stock.StockLedgerEntry
    G = pm.MaterialReceivingNote

    rows = db.execute(
        select(e.item_id, e.entry_date, e.unit_cost, e.source_number,
               G.landed_cost_id, G.shipment_id, pm.PurchaseOrder.purchase_type)
        .outerjoin(G, G.id == e.source_id)
        .outerjoin(pm.PurchaseOrder, pm.PurchaseOrder.id == G.purchase_order_id)
        .where(e.company_id == company_id, e.direction == stock.IN,
               e.source_type.in_(COSTED_SOURCES), e.unit_cost.is_not(None))
        .order_by(e.item_id, e.entry_date.desc(), e.id.desc())
    ).all()

    out: dict[uuid.UUID, dict] = {}
    for row in rows:
        if row.item_id in out:
            continue  # ordered newest first, so the first one wins
        out[row.item_id] = {
            "last_cost": Decimal(str(row.unit_cost or 0)),
            "last_receipt": row.source_number,
            "last_receipt_date": row.entry_date,
            "purchase_type": row.purchase_type,
            "is_landed": row.landed_cost_id is not None,
        }
    return out


def rows(db: Session, company_id: uuid.UUID, *, search: str | None = None,
         main_product_id: uuid.UUID | None = None,
         sub_category_id: uuid.UUID | None = None,
         location_id: uuid.UUID | None = None,
         source: str | None = None,
         in_stock_only: bool = True,
         costed_only: bool = False) -> list[dict]:
    """One row per product: what it costs, and what its stock is worth."""
    balances = _balances(db, company_id, location_id)
    costs = _costs(db, company_id)
    last = _last_receipt(db, company_id)

    stmt: Select = select(InventoryItem).where(InventoryItem.company_id == company_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(InventoryItem.item_code.ilike(like),
                              InventoryItem.description.ilike(like),
                              InventoryItem.sku.ilike(like)))
    if main_product_id:
        stmt = stmt.where(InventoryItem.main_product_id == main_product_id)
    if sub_category_id:
        stmt = stmt.where(InventoryItem.sub_category_id == sub_category_id)

    categories = dict(db.execute(select(MainProduct.id, MainProduct.description)).all())
    subs = dict(db.execute(
        select(InventorySubCategory.id, InventorySubCategory.description)).all())

    out: list[dict] = []
    for item in db.scalars(stmt).all():
        balance = balances.get(item.id, ZERO)
        if in_stock_only and balance <= 0:
            continue

        cost = costs.get(item.id)
        recent = last.get(item.id, {})
        has_cost = cost is not None and cost["average_cost"] > 0
        if costed_only and not has_cost:
            continue

        average = cost["average_cost"] if has_cost else None
        # How much of what is on hand actually came in at a known cost. The
        # rest is opening balance carried over from the old ERP.
        costed_quantity = cost["costed_quantity"] if has_cost else ZERO
        uncosted = max(ZERO, balance - costed_quantity)

        where_from = (
            "Import" if recent.get("is_landed")
            else "Local purchase" if recent.get("purchase_type") == "Local"
            else "Purchase" if recent.get("last_receipt")
            else "Opening balance"
        )
        if source and where_from != source:
            continue

        out.append({
            "item_id": str(item.id),
            "item_code": item.item_code,
            "description": item.description,
            "sku": item.sku,
            "uom": item.uom,
            "main_product": categories.get(item.main_product_id),
            "sub_category": subs.get(item.sub_category_id),
            "quantity": float(balance),
            "average_cost": float(round(average, 4)) if average is not None else None,
            "stock_value": float(round(balance * average, 2)) if average is not None else None,
            "costed_quantity": float(costed_quantity),
            "uncosted_quantity": float(uncosted),
            # True when part of the balance predates any costed receipt, so the
            # value is an estimate applied to stock whose real cost is unknown.
            "is_estimate": bool(average is not None and uncosted > 0),
            "lowest_cost": float(cost["lowest_cost"]) if has_cost else None,
            "highest_cost": float(cost["highest_cost"]) if has_cost else None,
            "receipts": cost["receipts"] if has_cost else 0,
            "last_cost": float(recent["last_cost"]) if recent.get("last_cost") else None,
            "last_receipt": recent.get("last_receipt"),
            "last_receipt_date": recent.get("last_receipt_date"),
            "cost_source": where_from,
            "selling_price": float(item.price) if item.price else None,
            # What the product makes over what it cost. The number that says
            # whether an import was worth bringing in.
            "margin_percent": (
                float(round((Decimal(str(item.price)) - average) / average * 100, 2))
                if item.price and average and average > 0 else None
            ),
        })

    out.sort(key=lambda r: -(r["stock_value"] or 0))
    return out


def summarise(rows_in: list[dict]) -> dict:
    """Totals over every matching row, not just the page on screen."""
    valued = [r for r in rows_in if r["stock_value"] is not None]
    unknown = [r for r in rows_in if r["stock_value"] is None]
    total_value = sum(Decimal(str(r["stock_value"])) for r in valued) if valued else ZERO
    total_qty = sum(Decimal(str(r["quantity"])) for r in rows_in) if rows_in else ZERO
    imported = [r for r in valued if r["cost_source"] == "Import"]

    return {
        "products": len(rows_in),
        "total_quantity": float(total_qty),
        "products_valued": len(valued),
        "products_without_a_cost": len(unknown),
        "quantity_without_a_cost": float(
            sum(Decimal(str(r["quantity"])) for r in unknown) if unknown else ZERO),
        "total_stock_value": float(round(total_value, 2)),
        "average_unit_cost": float(round(
            total_value / sum(Decimal(str(r["quantity"])) for r in valued), 4))
            if valued and sum(Decimal(str(r["quantity"])) for r in valued) else 0.0,
        "imported_products": len(imported),
        "imported_stock_value": float(round(
            sum(Decimal(str(r["stock_value"])) for r in imported), 2)) if imported else 0.0,
        "estimated_rows": len([r for r in valued if r["is_estimate"]]),
    }


def cost_history(db: Session, company_id: uuid.UUID, item_id: uuid.UUID) -> dict:
    """Every costed receipt for one product — the full story of what it cost.

    For an import this breaks the unit cost into what the supplier charged and
    what the import added on top, which is the question landed costing exists
    to answer: not "what did we pay the supplier" but "what is this thing
    actually worth on our shelf".
    """
    item = db.get(InventoryItem, item_id)
    if item is None:
        return {}

    e = stock.StockLedgerEntry
    G = pm.MaterialReceivingNote

    receipts = db.execute(
        select(
            e.entry_date, e.quantity, e.unit_cost, e.source_number, e.source_id,
            ItemLocation.location, G.landed_cost_id, G.supplier_id,
            pm.PurchaseOrder.purchase_type, pm.PurchaseOrder.doc_number.label("po_number"),
            pm.PurchaseOrder.currency, pm.PurchaseOrder.exchange_rate,
        )
        .outerjoin(ItemLocation, ItemLocation.id == e.location_id)
        .outerjoin(G, G.id == e.source_id)
        .outerjoin(pm.PurchaseOrder, pm.PurchaseOrder.id == G.purchase_order_id)
        .where(e.company_id == company_id, e.item_id == item_id,
               e.direction == stock.IN, e.source_type.in_(COSTED_SOURCES))
        .order_by(e.entry_date.desc())
    ).all()

    # The landed-cost lines behind those receipts, so each one can show what
    # the supplier charged against what the import added.
    landed_ids = [r.landed_cost_id for r in receipts if r.landed_cost_id]
    breakdown: dict[uuid.UUID, dict] = {}
    if landed_ids:
        for row in db.execute(
            select(pm.LandedCostItem, pm.LandedCost.doc_number)
            .join(pm.LandedCost, pm.LandedCost.id == pm.LandedCostItem.landed_cost_id)
            .where(pm.LandedCostItem.landed_cost_id.in_(landed_ids),
                   pm.LandedCostItem.item_id == item_id)
        ).all():
            line, number = row
            breakdown[line.landed_cost_id] = {
                "landed_cost_number": number,
                "unit_purchase_cost": float(round(
                    line.purchase_cost_base / line.quantity, 4)) if line.quantity else 0.0,
                "unit_import_cost": float(round(
                    line.additional_cost / line.quantity, 4)) if line.quantity else 0.0,
                "unit_landed_cost": float(line.unit_landed_cost),
                "freight": float(line.freight_cost),
                "insurance": float(line.insurance_cost),
                "customs": float(line.customs_cost),
                "taxes": float(line.tax_cost),
                "port": float(line.port_cost),
                "clearing": float(line.clearing_cost),
                "bank": float(line.bank_cost),
                "other": float(line.other_cost),
            }

    partners = dict(db.execute(
        select(pm.BusinessPartner.id, pm.BusinessPartner.name)).all()) \
        if hasattr(pm, "BusinessPartner") else {}
    if not partners:
        from app.partners.models import BusinessPartner
        partners = dict(db.execute(
            select(BusinessPartner.id, BusinessPartner.name)).all())

    history = []
    total_qty = ZERO
    total_value = ZERO
    for r in receipts:
        quantity = Decimal(str(r.quantity or 0))
        unit = Decimal(str(r.unit_cost or 0))
        total_qty += quantity
        total_value += quantity * unit
        history.append({
            "entry_date": r.entry_date,
            "quantity": float(quantity),
            "unit_cost": float(unit),
            "total_cost": float(round(quantity * unit, 2)),
            "goods_receipt": r.source_number,
            "goods_receipt_id": str(r.source_id) if r.source_id else None,
            "warehouse": r.location,
            "supplier": partners.get(r.supplier_id),
            "purchase_order": r.po_number,
            "purchase_type": r.purchase_type,
            "currency": r.currency,
            "exchange_rate": float(r.exchange_rate) if r.exchange_rate else None,
            "landed": breakdown.get(r.landed_cost_id),
        })

    balances = _balances(db, company_id)
    balance = balances.get(item_id, ZERO)
    average = (total_value / total_qty) if total_qty else None

    return {
        "item_id": str(item_id),
        "item_code": item.item_code,
        "description": item.description,
        "uom": item.uom,
        "quantity_on_hand": float(balance),
        "costed_quantity": float(total_qty),
        "uncosted_quantity": float(max(ZERO, balance - total_qty)),
        "average_cost": float(round(average, 4)) if average else None,
        "stock_value": float(round(balance * average, 2)) if average else None,
        "selling_price": float(item.price) if item.price else None,
        "receipts": history,
    }
