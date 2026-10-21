"""
Import Landed Costing report (spec sections 29 to 34).

One row per product per costing, showing what the supplier charged and what
the import added on top of it:

    purchase + freight + insurance + customs + taxes
            + clearing + port + bank + other = total landed cost
    total landed cost / quantity              = unit landed cost

Reads only posted vouchers by default, because an unposted costing has not
affected inventory valuation and putting it in the same total as posted ones
would overstate what stock is worth.

The four analyses in section 33 (supplier, country, product, shipment) are
the same rows grouped four ways, so they are computed from one query rather
than four round trips.
"""

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.partners.models import BusinessPartner
from app.procurement import models as m

#: The cost-group columns, in the order section 31 lists them.
COMPONENTS = (
    ("freight_cost", "Freight"),
    ("insurance_cost", "Insurance"),
    ("customs_cost", "Customs"),
    ("tax_cost", "Taxes"),
    ("clearing_cost", "Clearing"),
    ("port_cost", "Port"),
    ("bank_cost", "Bank"),
    ("other_cost", "Other"),
)


def _base_query(company_id: uuid.UUID) -> Select:
    """Costing items joined to everything the report filters or groups by."""
    return (
        select(
            m.LandedCost, m.LandedCostItem, m.PurchaseOrder,
            m.ImportShipment, BusinessPartner.name,
        )
        .join(m.LandedCostItem, m.LandedCostItem.landed_cost_id == m.LandedCost.id)
        .outerjoin(m.PurchaseOrder, m.PurchaseOrder.id == m.LandedCost.purchase_order_id)
        .outerjoin(m.ImportShipment, m.ImportShipment.id == m.LandedCost.shipment_id)
        .outerjoin(BusinessPartner, BusinessPartner.id == m.LandedCost.supplier_id)
        .where(m.LandedCost.company_id == company_id)
    )


def apply_filters(
    stmt: Select,
    *,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    purchase_order_id: uuid.UUID | None = None,
    shipment_id: uuid.UUID | None = None,
    landed_cost_id: uuid.UUID | None = None,
    goods_receipt_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    supplier_country: str | None = None,
    country_of_origin: str | None = None,
    item_id: uuid.UUID | None = None,
    main_product_id: uuid.UUID | None = None,
    sub_category_id: uuid.UUID | None = None,
    hs_code: str | None = None,
    warehouse_id: uuid.UUID | None = None,
    port: str | None = None,
    clearing_agent: str | None = None,
    currency: str | None = None,
    shipment_status: str | None = None,
    customs_status: str | None = None,
    posted_only: bool = True,
) -> Select:
    """Every filter section 30 asks for."""
    if posted_only:
        stmt = stmt.where(m.LandedCost.is_posted.is_(True))
    if date_from:
        stmt = stmt.where(m.LandedCost.doc_date >= date_from)
    if date_to:
        stmt = stmt.where(m.LandedCost.doc_date <= date_to)
    if purchase_order_id:
        stmt = stmt.where(m.LandedCost.purchase_order_id == purchase_order_id)
    if shipment_id:
        stmt = stmt.where(m.LandedCost.shipment_id == shipment_id)
    if landed_cost_id:
        stmt = stmt.where(m.LandedCost.id == landed_cost_id)
    if goods_receipt_id:
        # Which costing did that receipt take its unit costs from?
        stmt = stmt.where(m.LandedCost.id.in_(
            select(m.MaterialReceivingNote.landed_cost_id)
            .where(m.MaterialReceivingNote.id == goods_receipt_id)))
    if supplier_id:
        stmt = stmt.where(m.LandedCost.supplier_id == supplier_id)
    if supplier_country:
        stmt = stmt.where(func.lower(m.PurchaseOrder.supplier_country)
                          == supplier_country.strip().lower())
    if country_of_origin:
        stmt = stmt.where(func.lower(m.PurchaseOrder.country_of_origin)
                          == country_of_origin.strip().lower())
    if item_id:
        stmt = stmt.where(m.LandedCostItem.item_id == item_id)
    if hs_code:
        stmt = stmt.where(m.LandedCostItem.hs_code.ilike(f"%{hs_code.strip()}%"))
    if warehouse_id:
        stmt = stmt.where(or_(m.ImportShipment.warehouse_id == warehouse_id,
                              m.PurchaseOrder.warehouse_id == warehouse_id))
    if port:
        like = f"%{port.strip()}%"
        stmt = stmt.where(or_(m.ImportShipment.port_of_discharge.ilike(like),
                              m.ImportShipment.port_of_loading.ilike(like),
                              m.PurchaseOrder.port_of_discharge.ilike(like)))
    if clearing_agent:
        like = f"%{clearing_agent.strip()}%"
        stmt = stmt.where(or_(m.ImportShipment.clearing_agent.ilike(like),
                              m.PurchaseOrder.clearing_agent.ilike(like)))
    if currency:
        stmt = stmt.where(m.LandedCost.currency == currency.strip().upper())
    if shipment_status:
        stmt = stmt.where(m.ImportShipment.transit_status == shipment_status)
    if customs_status:
        stmt = stmt.where(m.ImportShipment.customs_status == customs_status)
    if main_product_id or sub_category_id:
        from app.inventory.models import InventoryItem
        sub = select(InventoryItem.id)
        if main_product_id:
            sub = sub.where(InventoryItem.main_product_id == main_product_id)
        if sub_category_id:
            sub = sub.where(InventoryItem.sub_category_id == sub_category_id)
        stmt = stmt.where(m.LandedCostItem.item_id.in_(sub))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            m.LandedCost.doc_number.ilike(like),
            m.LandedCost.supplier_invoice_number.ilike(like),
            m.LandedCostItem.description.ilike(like),
            m.LandedCostItem.item_code.ilike(like),
            m.PurchaseOrder.doc_number.ilike(like),
            m.ImportShipment.doc_number.ilike(like),
            m.ImportShipment.container_number.ilike(like),
        ))
    return stmt


def _row(voucher, item, order, shipment, supplier_name) -> dict:
    """One report line — section 31's columns."""
    unit_purchase = (item.purchase_cost_base / item.quantity) if item.quantity else Decimal("0")
    return {
        "landed_cost_id": str(voucher.id),
        "landed_cost_number": voucher.doc_number,
        "doc_date": voucher.doc_date,
        "status": voucher.status,
        "is_posted": voucher.is_posted,
        "po_number": order.doc_number if order else None,
        "purchase_order_id": str(order.id) if order else None,
        "shipment_number": shipment.doc_number if shipment else None,
        "shipment_id": str(shipment.id) if shipment else None,
        "container_number": shipment.container_number if shipment else None,
        "supplier": supplier_name,
        "supplier_id": str(voucher.supplier_id) if voucher.supplier_id else None,
        "supplier_country": order.supplier_country if order else None,
        "country_of_origin": order.country_of_origin if order else None,
        "country": (order.country_of_origin or order.supplier_country) if order else None,
        "invoice_number": voucher.supplier_invoice_number,
        "currency": voucher.currency,
        "exchange_rate": float(voucher.exchange_rate),
        "port_of_discharge": shipment.port_of_discharge if shipment else None,
        "clearing_agent": (shipment.clearing_agent if shipment
                           else (order.clearing_agent if order else None)),
        "transit_status": shipment.transit_status if shipment else None,
        "customs_status": shipment.customs_status if shipment else None,
        "item_id": str(item.item_id) if item.item_id else None,
        "item_code": item.item_code,
        "item": item.description,
        "uom": item.uom,
        "hs_code": item.hs_code,
        "quantity": float(item.quantity),
        "unit_price": float(item.unit_price),
        "purchase_cost_foreign": float(item.purchase_cost),
        "purchase_cost": float(item.purchase_cost_base),
        "unit_purchase_cost": float(round(unit_purchase, 4)),
        "freight": float(item.freight_cost),
        "insurance": float(item.insurance_cost),
        "customs": float(item.customs_cost),
        "taxes": float(item.tax_cost),
        "clearing": float(item.clearing_cost),
        "port": float(item.port_cost),
        "bank": float(item.bank_cost),
        "other": float(item.other_cost),
        "additional_cost": float(item.additional_cost),
        "total_landed_cost": float(item.total_landed_cost),
        "unit_landed_cost": float(item.unit_landed_cost),
        # Section 34: how much the import added, as a percentage of the
        # supplier's price. The number that says whether it was worth it.
        "additional_cost_percent": (
            float(round(item.additional_cost / item.purchase_cost_base * 100, 2))
            if item.purchase_cost_base else None),
    }


def fetch(db: Session, company_id: uuid.UUID, *, sort: str = "doc_date",
          direction: str = "desc", limit: int | None = None,
          offset: int = 0, **filters) -> tuple[list[dict], int]:
    stmt = apply_filters(_base_query(company_id), **filters)

    total = db.scalar(
        stmt.with_only_columns(func.count(m.LandedCostItem.id)).order_by(None)) or 0

    column = {
        "doc_date": m.LandedCost.doc_date,
        "landed_cost_number": m.LandedCost.doc_number,
        "item": m.LandedCostItem.description,
        "quantity": m.LandedCostItem.quantity,
        "purchase_cost": m.LandedCostItem.purchase_cost_base,
        "additional_cost": m.LandedCostItem.additional_cost,
        "total_landed_cost": m.LandedCostItem.total_landed_cost,
        "unit_landed_cost": m.LandedCostItem.unit_landed_cost,
    }.get(sort, m.LandedCost.doc_date)
    stmt = stmt.order_by(
        column.desc() if direction == "desc" else column.asc(),
        m.LandedCost.doc_number.desc(), m.LandedCostItem.line_number.asc())

    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)
    return [_row(*row) for row in db.execute(stmt).all()], total


def summarise(db: Session, company_id: uuid.UUID, **filters) -> dict:
    """The figures section 32 wants, over every matching row — not just the
    page on screen, which is the whole point of a summary."""
    rows, _ = fetch(db, company_id, limit=None, **filters)

    def total(key: str) -> float:
        return float(round(sum(Decimal(str(r[key])) for r in rows), 2)) if rows else 0.0

    purchase = total("purchase_cost")
    additional = total("additional_cost")
    quantity = total("quantity")
    landed = total("total_landed_cost")

    return {
        "total_import_pos": len({r["po_number"] for r in rows if r["po_number"]}),
        "total_shipments": len({r["shipment_number"] for r in rows if r["shipment_number"]}),
        "total_landed_costs": len({r["landed_cost_number"] for r in rows}),
        "total_products": len({r["item_code"] or r["item"] for r in rows}),
        "total_quantity": quantity,
        "total_foreign_value": total("purchase_cost_foreign"),
        "total_purchase_value": purchase,
        "total_freight": total("freight"),
        "total_insurance": total("insurance"),
        "total_customs": total("customs"),
        "total_taxes": total("taxes"),
        "total_clearing": total("clearing"),
        "total_port": total("port"),
        "total_bank": total("bank"),
        "total_other": total("other"),
        "total_additional_cost": additional,
        "total_landed_cost": landed,
        "average_unit_landed_cost": round(landed / quantity, 4) if quantity else 0.0,
        "additional_cost_percent": round(additional / purchase * 100, 2) if purchase else 0.0,
        "currencies": sorted({r["currency"] for r in rows if r["currency"]}),
    }


def _group(rows: list[dict], key: str, label: str) -> list[dict]:
    """Roll the rows up by one field, keeping the component breakdown."""
    buckets: dict[str, dict] = defaultdict(lambda: {
        "quantity": Decimal("0"), "purchase_cost": Decimal("0"),
        "freight": Decimal("0"), "insurance": Decimal("0"), "customs": Decimal("0"),
        "taxes": Decimal("0"), "clearing": Decimal("0"), "port": Decimal("0"),
        "bank": Decimal("0"), "other": Decimal("0"),
        "additional_cost": Decimal("0"), "total_landed_cost": Decimal("0"),
        "lines": 0,
    })

    for row in rows:
        name = row.get(key) or "(not stated)"
        bucket = buckets[name]
        bucket["lines"] += 1
        for field in ("quantity", "purchase_cost", "freight", "insurance", "customs",
                      "taxes", "clearing", "port", "bank", "other",
                      "additional_cost", "total_landed_cost"):
            bucket[field] += Decimal(str(row[field]))

    out = []
    for name, bucket in buckets.items():
        purchase = bucket["purchase_cost"]
        quantity = bucket["quantity"]
        out.append({
            label: name,
            "lines": bucket["lines"],
            **{field: float(round(bucket[field], 2)) for field in (
                "quantity", "purchase_cost", "freight", "insurance", "customs",
                "taxes", "clearing", "port", "bank", "other",
                "additional_cost", "total_landed_cost")},
            "unit_landed_cost": float(round(bucket["total_landed_cost"] / quantity, 4))
            if quantity else 0.0,
            "landed_cost_percent": float(round(
                bucket["additional_cost"] / purchase * 100, 2)) if purchase else None,
        })
    return sorted(out, key=lambda r: -r["total_landed_cost"])


def analyse(db: Session, company_id: uuid.UUID, **filters) -> dict:
    """The four analyses in section 33, from one pass over the rows."""
    rows, _ = fetch(db, company_id, limit=None, **filters)
    return {
        "by_supplier": _group(rows, "supplier", "supplier"),
        "by_country": _group(rows, "country", "country"),
        "by_product": _group(rows, "item", "product"),
        "by_shipment": _group(rows, "shipment_number", "shipment"),
    }


def cost_components(db: Session, company_id: uuid.UUID, **filters) -> list[dict]:
    """Where the import cost went, by component — section 44's Cost Component
    Analysis. Read from the allocation rows, so it reconciles to the charges
    rather than to the rolled-up columns."""
    rows, _ = fetch(db, company_id, limit=None, **filters)
    additional = sum(Decimal(str(r["additional_cost"])) for r in rows) or Decimal("1")

    out = []
    for field, label in COMPONENTS:
        key = {"freight_cost": "freight", "insurance_cost": "insurance",
               "customs_cost": "customs", "tax_cost": "taxes",
               "clearing_cost": "clearing", "port_cost": "port",
               "bank_cost": "bank", "other_cost": "other"}[field]
        amount = sum(Decimal(str(r[key])) for r in rows)
        out.append({
            "component": label,
            "amount": float(round(amount, 2)),
            "share_percent": float(round(amount / additional * 100, 2)),
        })
    return out
