"""
Row builders for the procurement datasets (spec section 45).

Each returns flat dicts for the shared CSV / XLSX / PDF writers, and honours
the same filters as the screen it belongs to, so a download matches what the
user was looking at rather than the whole table.
"""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.partners.models import BusinessPartner
from app.inventory.models import ItemLocation
from app.procurement import models as pm
from app.reports import landed_costing

MAX_ROWS = 20_000


def _lookup(db: Session):
    partners = dict(db.execute(select(BusinessPartner.id, BusinessPartner.name)).all())
    warehouses = dict(db.execute(select(ItemLocation.id, ItemLocation.location)).all())
    return partners, warehouses


def in_house_order_rows(db: Session, company_id: uuid.UUID, search: str | None,
                        statuses: list[str], extra: dict | None = None) -> list[dict]:
    extra = extra or {}
    stmt = select(pm.InHouseOrder).where(pm.InHouseOrder.company_id == company_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            pm.InHouseOrder.doc_number.ilike(like),
            pm.InHouseOrder.purpose.ilike(like),
            pm.InHouseOrder.requested_by.ilike(like),
            pm.InHouseOrder.lines.any(pm.InHouseOrderLine.description.ilike(like))))
    if statuses:
        stmt = stmt.where(pm.InHouseOrder.status.in_(statuses))
    if extra.get("date_from"):
        stmt = stmt.where(pm.InHouseOrder.doc_date >= extra["date_from"])
    if extra.get("date_to"):
        stmt = stmt.where(pm.InHouseOrder.doc_date <= extra["date_to"])

    _, warehouses = _lookup(db)
    rows = []
    for order in db.scalars(stmt.order_by(pm.InHouseOrder.doc_date.desc()).limit(MAX_ROWS)):
        # One row per line: a requirement register that hides the items is
        # not much use for deciding what to buy.
        for line in order.lines:
            approved = line.approved_quantity or line.requested_quantity
            rows.append({
                "doc_number": order.doc_number,
                "doc_date": order.doc_date,
                "warehouse": warehouses.get(order.warehouse_id),
                "department": order.department,
                "requested_by": order.requested_by,
                "priority": order.priority,
                "source": order.source,
                "status": order.status,
                "required_date": line.required_date or order.required_date,
                "item_code": line.item_code,
                "description": line.description,
                "uom": line.uom,
                "available_stock": float(line.available_stock),
                "requested_quantity": float(line.requested_quantity),
                "approved_quantity": float(approved),
                "ordered_quantity": float(line.ordered_quantity),
                "received_quantity": float(line.received_quantity),
                "outstanding_quantity": float(max(0, approved - line.received_quantity)),
                "fulfilment_source": line.fulfilment_source,
                "purpose": order.purpose,
            })
    return rows


def purchase_order_rows(purchase_type: str | None = None):
    """Register for local orders, import orders, or both."""
    def fetch(db: Session, company_id: uuid.UUID, search: str | None,
              statuses: list[str], extra: dict | None = None) -> list[dict]:
        extra = extra or {}
        stmt = select(pm.PurchaseOrder).where(pm.PurchaseOrder.company_id == company_id)
        if purchase_type:
            stmt = stmt.where(pm.PurchaseOrder.purchase_type == purchase_type)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(
                pm.PurchaseOrder.doc_number.ilike(like),
                pm.PurchaseOrder.lc_number.ilike(like),
                pm.PurchaseOrder.commercial_invoice_number.ilike(like),
                pm.PurchaseOrder.lines.any(pm.PurchaseOrderLine.description.ilike(like))))
        if statuses:
            stmt = stmt.where(pm.PurchaseOrder.status.in_(statuses))
        if extra.get("date_from"):
            stmt = stmt.where(pm.PurchaseOrder.doc_date >= extra["date_from"])
        if extra.get("date_to"):
            stmt = stmt.where(pm.PurchaseOrder.doc_date <= extra["date_to"])

        partners, warehouses = _lookup(db)
        rows = []
        for order in db.scalars(
                stmt.order_by(pm.PurchaseOrder.doc_date.desc()).limit(MAX_ROWS)):
            for line in order.lines:
                rows.append({
                    "doc_number": order.doc_number,
                    "doc_date": order.doc_date,
                    "purchase_type": order.purchase_type,
                    "supplier": partners.get(order.supplier_id),
                    "supplier_country": order.supplier_country,
                    "country_of_origin": order.country_of_origin,
                    "warehouse": warehouses.get(order.warehouse_id),
                    "status": order.status,
                    "currency": order.currency,
                    "exchange_rate": float(order.exchange_rate),
                    "incoterm": order.incoterm,
                    "lc_number": order.lc_number,
                    "expected_delivery_date": order.expected_delivery_date,
                    "priority": order.priority,
                    "expected_arrival_date": order.expected_arrival_date,
                    "item_code": line.item_code,
                    "description": line.description,
                    "uom": line.uom,
                    "hs_code": line.hs_code,
                    "quantity": float(line.quantity),
                    "shipped_quantity": float(line.shipped_quantity),
                    "received_quantity": float(line.received_quantity),
                    "outstanding_quantity": float(max(
                        0, line.quantity - line.received_quantity)),
                    "unit_price": float(line.unit_price),
                    "net_amount": float(line.net_amount),
                    "net_payable": float(order.net_payable),
                    "net_payable_base": float(order.net_payable_base),
                })
        return rows
    return fetch


def shipment_rows(in_transit_only: bool = False):
    """Shipment register, or the goods-in-transit report."""
    def fetch(db: Session, company_id: uuid.UUID, search: str | None,
              statuses: list[str], extra: dict | None = None) -> list[dict]:
        extra = extra or {}
        stmt = select(pm.ImportShipment).where(pm.ImportShipment.company_id == company_id)
        if in_transit_only:
            stmt = stmt.where(pm.ImportShipment.transit_status.in_(pm.TRANSIT_IN_FLIGHT))
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(
                pm.ImportShipment.doc_number.ilike(like),
                pm.ImportShipment.container_number.ilike(like),
                pm.ImportShipment.bill_of_lading_number.ilike(like)))
        if statuses:
            stmt = stmt.where(pm.ImportShipment.status.in_(statuses))
        if extra.get("date_from"):
            stmt = stmt.where(pm.ImportShipment.doc_date >= extra["date_from"])
        if extra.get("date_to"):
            stmt = stmt.where(pm.ImportShipment.doc_date <= extra["date_to"])

        partners, warehouses = _lookup(db)
        orders = dict(db.execute(
            select(pm.PurchaseOrder.id, pm.PurchaseOrder.doc_number)).all())
        rows = []
        for ship in db.scalars(
                stmt.order_by(pm.ImportShipment.doc_date.desc()).limit(MAX_ROWS)):
            for line in ship.lines:
                rows.append({
                    "doc_number": ship.doc_number,
                    "doc_date": ship.doc_date,
                    "purchase_order": orders.get(ship.purchase_order_id),
                    "supplier": partners.get(ship.supplier_id),
                    "status": ship.status,
                    "transit_status": ship.transit_status,
                    "customs_status": ship.customs_status,
                    "container_number": ship.container_number,
                    "bill_of_lading_number": ship.bill_of_lading_number,
                    "vessel_or_flight": ship.vessel_or_flight,
                    "port_of_loading": ship.port_of_loading,
                    "port_of_discharge": ship.port_of_discharge,
                    "etd": ship.etd,
                    "eta": ship.eta,
                    "actual_arrival_date": ship.actual_arrival_date,
                    "clearing_agent": ship.clearing_agent,
                    "warehouse": warehouses.get(ship.warehouse_id),
                    "item_code": line.item_code,
                    "description": line.description,
                    "uom": line.uom,
                    "shipped_quantity": float(line.shipped_quantity),
                    "received_quantity": float(line.received_quantity),
                    "outstanding_quantity": float(max(
                        0, line.shipped_quantity - line.received_quantity)),
                    "currency": ship.currency,
                    "exchange_rate": float(ship.exchange_rate),
                    "line_value": float(line.line_value),
                })
        return rows
    return fetch


def goods_receipt_rows(db: Session, company_id: uuid.UUID, search: str | None,
                       statuses: list[str], extra: dict | None = None) -> list[dict]:
    extra = extra or {}
    G = pm.MaterialReceivingNote
    stmt = select(G).where(G.company_id == company_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            G.doc_number.ilike(like), G.supplier_invoice_number.ilike(like),
            G.lines.any(pm.MrnLine.description.ilike(like))))
    if statuses:
        stmt = stmt.where(G.status.in_(statuses))
    if extra.get("date_from"):
        stmt = stmt.where(G.doc_date >= extra["date_from"])
    if extra.get("date_to"):
        stmt = stmt.where(G.doc_date <= extra["date_to"])

    partners, warehouses = _lookup(db)
    orders = dict(db.execute(
        select(pm.PurchaseOrder.id, pm.PurchaseOrder.doc_number)).all())
    rows = []
    for grn in db.scalars(stmt.order_by(G.doc_date.desc()).limit(MAX_ROWS)):
        for line in grn.lines:
            rows.append({
                "doc_number": grn.doc_number,
                "doc_date": grn.doc_date,
                "supplier": partners.get(grn.supplier_id),
                "purchase_order": orders.get(grn.purchase_order_id),
                "warehouse": warehouses.get(line.warehouse_id or grn.warehouse_id),
                "status": grn.status,
                "is_posted": "Yes" if grn.is_posted else "No",
                "supplier_invoice_number": grn.supplier_invoice_number,
                "supplier_invoice_date": grn.supplier_invoice_date,
                "vehicle_number": grn.vehicle_number,
                "received_by": grn.received_by,
                "item_code": line.item_code,
                "description": line.description,
                "uom": line.uom,
                "ordered_quantity": float(line.ordered_quantity),
                "received_quantity": float(line.received_quantity),
                "remaining_quantity": float(line.remaining_quantity),
                "rejected_quantity": float(line.rejected_quantity),
                "unit_price": float(line.unit_price),
                "unit_cost_base": float(line.unit_cost_base),
                "net_amount": float(line.net_amount),
            })
    return rows


def landed_costing_rows(db: Session, company_id: uuid.UUID, search: str | None,
                        statuses: list[str], extra: dict | None = None) -> list[dict]:
    """The Import Landed Costing report, straight from the report module so
    the file and the screen cannot disagree."""
    extra = extra or {}
    rows, _ = landed_costing.fetch(
        db, company_id, limit=None, search=search,
        date_from=extra.get("date_from"), date_to=extra.get("date_to"),
        supplier_id=extra.get("supplier_id"),
        # A download of an unposted costing is legitimate — someone checking
        # the figures before approving it.
        posted_only=not bool(statuses) or "Draft" not in statuses,
    )
    return rows
