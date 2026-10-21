"""
Procurement API: requirements, purchasing, imports, costing, receipts.

Routes are grouped the way the work flows:

    /procurement/availability          should we buy this at all?
    /procurement/in-house-orders       the requirement, and its approval
    /procurement/purchase-orders       local and import ordering
    /procurement/shipments             what left the supplier, and where it is
    /procurement/charge-types          the import costs a company meets
    /procurement/landed-costs          what an import really cost
    /procurement/goods-receipts        what arrived — the only thing that
                                       moves stock

Status changes go through their own endpoint rather than a field on the save,
because some of them do work: posting a receipt writes the stock ledger, and
posting a costing fixes the value the goods enter stock at.
"""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status as http
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import require_permission
from app.common.calculations import LineInput, calculate_document, money
from app.common.numbering import next_number
from app.core.database import get_db
from app.inventory.models import ItemLocation
from app.inventory.router import active_company_id
from app.partners.models import BusinessPartner
from app.procurement import models as m
from app.procurement import schemas as s
from app.procurement import service
from app.users.models import User

PRIORITIES = ("Urgent", "High", "Medium", "Low")
# Fields from the company's Import Purchase Order template, stored as entered.
TEMPLATE_FIELDS = (
    "purchase_category", "buyer_designation", "supplier_contact", "supplier_contact_designation",
    "ship_to_address", "bill_to_address", "incoterm_edition", "named_place", "partial_shipment",
    "transshipment", "packing_marks", "country_of_export", "payment_method", "balance_trigger",
    "bank_charges", "payment_reference", "goods_condition", "warranty_terms", "defect_remedy",
    "special_packing", "pre_shipment_inspection", "special_instructions")
TEMPLATE_AMOUNTS = ("packing_amount", "insurance_amount", "other_charges", "advance_amount", "advance_percent")

router = APIRouter(prefix="/procurement", tags=["procurement"])

ZERO = Decimal("0")


def _fiscal_year(db: Session, company_id: uuid.UUID) -> str:
    from app.companies.models import FinancialYear
    year = db.scalar(
        select(FinancialYear).where(
            FinancialYear.company_id == company_id, FinancialYear.is_current.is_(True))
    )
    return year.name if year else str(date.today().year)


def _number(db: Session, company_id: uuid.UUID, doc_type: str,
            fiscal_year: str, prefix: str) -> str:
    return next_number(db, company_id, doc_type, fiscal_year, prefix=prefix)


def _uid(value) -> uuid.UUID | None:
    return None if value in (None, "") else uuid.UUID(str(value))


def _names(db: Session, ids) -> dict:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return dict(db.execute(
        select(BusinessPartner.id, BusinessPartner.name)
        .where(BusinessPartner.id.in_(ids))
    ).all())


def _warehouses(db: Session, ids) -> dict:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return dict(db.execute(
        select(ItemLocation.id, ItemLocation.location).where(ItemLocation.id.in_(ids))
    ).all())


# ============================================================= availability

@router.get("/availability")
def stock_availability(
    item_id: uuid.UUID,
    warehouse_id: uuid.UUID | None = None,
    required_quantity: Decimal = Query(Decimal("0"), ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("inventory.items.view")),
):
    """The stock picture for one product, and what is actually short.

    `transfer_options` lists warehouses that could supply it instead, which
    is the cheaper answer whenever one of them can cover the shortfall.
    """
    company_id = active_company_id(db)
    picture = service.availability(db, company_id, item_id, warehouse_id)
    short = service.shortfall(picture, required_quantity)
    picture["required_quantity"] = float(required_quantity)
    picture["shortfall"] = float(short)
    picture["needs_purchase"] = short > 0
    picture["transfer_options"] = service.transfer_candidates(
        db, company_id, item_id, warehouse_id, short or Decimal("1"))
    return picture


# =========================================================== in-house orders

def _iho_summary(order: m.InHouseOrder, warehouses: dict) -> dict:
    return {
        "id": str(order.id),
        "doc_number": order.doc_number,
        "doc_date": order.doc_date,
        "warehouse": warehouses.get(order.warehouse_id),
        "warehouse_id": str(order.warehouse_id) if order.warehouse_id else None,
        "department": order.department,
        "requested_by": order.requested_by,
        "required_date": order.required_date,
        "priority": order.priority,
        "source": order.source,
        "status": order.status,
        "purpose": order.purpose,
        "remarks": order.remarks,
        "total_items": order.total_items,
    }


def _iho_detail(db: Session, order: m.InHouseOrder) -> dict:
    warehouses = _warehouses(db, [order.warehouse_id]
                             + [l.destination_warehouse_id for l in order.lines])
    data = _iho_summary(order, warehouses)
    data["lines"] = [
        {
            "id": str(line.id),
            "line_number": line.line_number,
            "item_id": str(line.item_id) if line.item_id else None,
            "item_code": line.item_code,
            "description": line.description,
            "uom": line.uom,
            "stock_on_hand": float(line.stock_on_hand),
            "reserved_stock": float(line.reserved_stock),
            "available_stock": float(line.available_stock),
            "stock_other_warehouses": float(line.stock_other_warehouses),
            "stock_on_order": float(line.stock_on_order),
            "goods_in_transit": float(line.goods_in_transit),
            "reorder_level": float(line.reorder_level) if line.reorder_level else None,
            "min_level": float(line.min_level) if line.min_level else None,
            "max_level": float(line.max_level) if line.max_level else None,
            "requested_quantity": float(line.requested_quantity),
            "approved_quantity": float(line.approved_quantity),
            "ordered_quantity": float(line.ordered_quantity),
            "received_quantity": float(line.received_quantity),
            "outstanding_quantity": float(max(
                ZERO, (line.approved_quantity or line.requested_quantity)
                - line.received_quantity)),
            "fulfilment_source": line.fulfilment_source,
            "required_date": line.required_date,
            "destination_warehouse": warehouses.get(line.destination_warehouse_id),
            "destination_warehouse_id": (
                str(line.destination_warehouse_id) if line.destination_warehouse_id else None),
            "remarks": line.remarks,
        }
        for line in order.lines
    ]
    return data


@router.get("/departments")
def requisition_departments(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.in_house_orders.view")),
):
    """The HR departments, for the Department picker on an in-house order:
    active ones, each sub department shown under its department
    ("Production / Cutting"). Read here so whoever raises a requirement need
    not hold HR permissions."""
    from app.hrms.models import Department
    rows = db.scalars(select(Department).where(
        Department.company_id == active_company_id(db), Department.is_active.is_(True))).all()
    names = {d.id: d.name for d in rows}
    items = [{"id": str(d.id), "code": d.code,
              "name": f"{names[d.parent_id]} / {d.name}" if d.parent_id in names else d.name}
             for d in rows]
    return {"items": sorted(items, key=lambda d: d["name"].lower())}


@router.get("/in-house-orders")
def list_in_house_orders(
    search: str | None = None,
    status_filter: list[str] = Query(default=[], alias="status"),
    source: list[str] = Query(default=[]),
    priority: list[str] = Query(default=[]),
    warehouse_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = "doc_date",
    direction: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.in_house_orders.view")),
):
    company_id = active_company_id(db)
    stmt = select(m.InHouseOrder).where(m.InHouseOrder.company_id == company_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            m.InHouseOrder.doc_number.ilike(like),
            m.InHouseOrder.remarks.ilike(like),
            m.InHouseOrder.purpose.ilike(like),
            m.InHouseOrder.requested_by.ilike(like),
            m.InHouseOrder.lines.any(m.InHouseOrderLine.description.ilike(like)),
        ))
    if status_filter:
        stmt = stmt.where(m.InHouseOrder.status.in_(status_filter))
    if source:
        stmt = stmt.where(m.InHouseOrder.source.in_(source))
    if priority:
        stmt = stmt.where(m.InHouseOrder.priority.in_(priority))
    if warehouse_id:
        stmt = stmt.where(m.InHouseOrder.warehouse_id == warehouse_id)
    if date_from:
        stmt = stmt.where(m.InHouseOrder.doc_date >= date_from)
    if date_to:
        stmt = stmt.where(m.InHouseOrder.doc_date <= date_to)

    total = db.scalar(stmt.with_only_columns(
        func.count(m.InHouseOrder.id)).order_by(None)) or 0

    column = {
        "doc_number": m.InHouseOrder.doc_number,
        "doc_date": m.InHouseOrder.doc_date,
        "status": m.InHouseOrder.status,
        "priority": m.InHouseOrder.priority,
        "required_date": m.InHouseOrder.required_date,
    }.get(sort, m.InHouseOrder.doc_date)
    stmt = stmt.order_by(column.desc() if direction == "desc" else column.asc(),
                         m.InHouseOrder.doc_number.desc())

    rows = db.scalars(
        stmt.options(selectinload(m.InHouseOrder.lines))
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    warehouses = _warehouses(db, [r.warehouse_id for r in rows])
    return {
        "items": [_iho_summary(r, warehouses) for r in rows],
        "total": total, "page": page, "page_size": page_size,
    }


def _owned_iho(db: Session, order_id: uuid.UUID) -> m.InHouseOrder:
    order = db.scalar(
        select(m.InHouseOrder)
        .options(selectinload(m.InHouseOrder.lines))
        .where(m.InHouseOrder.id == order_id,
               m.InHouseOrder.company_id == active_company_id(db))
    )
    if order is None:
        raise HTTPException(404, "That in-house order does not exist.")
    return order


@router.get("/in-house-orders/{order_id}")
def get_in_house_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.in_house_orders.view")),
):
    return _iho_detail(db, _owned_iho(db, order_id))


def _apply_iho_lines(db: Session, order: m.InHouseOrder,
                     raw_lines: list[s.InHouseOrderLineIn]) -> None:
    """Rebuild a requirement's lines, taking a fresh stock snapshot.

    The availability figures are captured here rather than accepted from the
    client: what the browser last saw may be minutes old, and the snapshot is
    meant to record the true position when the requirement was written.
    """
    if not raw_lines:
        raise HTTPException(400, "A requirement needs at least one line.")

    previous = {line.id: line for line in order.lines}
    new_lines: list[m.InHouseOrderLine] = []

    for index, raw in enumerate(raw_lines, start=1):
        item_id = _uid(raw.item_id)
        picture = (service.availability(db, order.company_id, item_id, order.warehouse_id)
                   if item_id else {})
        kept = previous.get(_uid(raw.id)) if raw.id else None

        description = (raw.description or picture.get("description") or "").strip()
        if not description:
            raise HTTPException(400, f"Line {index}: a description is required.")

        new_lines.append(m.InHouseOrderLine(
            id=kept.id if kept else uuid.uuid4(),
            line_number=index,
            item_id=item_id,
            item_code=raw.item_code or picture.get("item_code"),
            description=description,
            uom=raw.uom or picture.get("uom"),
            stock_on_hand=service.qty(picture.get("stock_on_hand", 0)),
            reserved_stock=service.qty(picture.get("reserved_stock", 0)),
            available_stock=service.qty(picture.get("available_stock", 0)),
            stock_other_warehouses=service.qty(picture.get("stock_other_warehouses", 0)),
            stock_on_order=service.qty(picture.get("stock_on_order", 0)),
            goods_in_transit=service.qty(picture.get("goods_in_transit", 0)),
            reorder_level=(Decimal(str(picture["reorder_level"]))
                           if picture.get("reorder_level") else None),
            min_level=(Decimal(str(picture["min_level"]))
                       if picture.get("min_level") else None),
            max_level=(Decimal(str(picture["max_level"]))
                       if picture.get("max_level") else None),
            requested_quantity=service.qty(raw.requested_quantity),
            # Until somebody approves it, approved tracks requested: a line
            # that reads "approved 0" would be refused by the PO builder for
            # the wrong reason.
            approved_quantity=service.qty(
                raw.approved_quantity if raw.approved_quantity is not None
                else raw.requested_quantity),
            ordered_quantity=kept.ordered_quantity if kept else ZERO,
            received_quantity=kept.received_quantity if kept else ZERO,
            fulfilment_source=raw.fulfilment_source,
            required_date=raw.required_date or order.required_date,
            destination_warehouse_id=_uid(raw.destination_warehouse_id) or order.warehouse_id,
            remarks=raw.remarks,
        ))

    order.lines = new_lines
    order.total_items = len(new_lines)


@router.post("/in-house-orders", status_code=http.HTTP_201_CREATED)
def create_in_house_order(
    payload: s.InHouseOrderIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.in_house_orders.create")),
):
    company_id = active_company_id(db)
    fiscal_year = _fiscal_year(db, company_id)
    order = m.InHouseOrder(
        company_id=company_id,
        branch_id=_uid(payload.branch_id),
        doc_number=_number(db, company_id, "in_house_order", fiscal_year, "IHO-"),
        doc_date=payload.doc_date,
        fiscal_year=fiscal_year,
        warehouse_id=service.resolve_warehouse(db, company_id, _uid(payload.warehouse_id)),
        department=payload.department,
        requested_by=payload.requested_by,
        requested_by_user_id=user.id,
        required_date=payload.required_date,
        priority=payload.priority,
        purpose=payload.purpose,
        source=payload.source,
        source_document_type=payload.source_document_type,
        source_document_id=_uid(payload.source_document_id),
        remarks=payload.remarks,
        status="Draft",
        created_by=user.id,
    )
    db.add(order)
    _apply_iho_lines(db, order, payload.lines)
    db.commit()
    db.refresh(order)
    return _iho_detail(db, order)


@router.put("/in-house-orders/{order_id}")
def update_in_house_order(
    order_id: uuid.UUID,
    payload: s.InHouseOrderIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.in_house_orders.edit")),
):
    order = _owned_iho(db, order_id)
    if order.status not in ("Draft", "Submitted", "Pending Approval", "Rejected"):
        raise HTTPException(
            400,
            f"This requirement is {order.status!r}. Purchase orders have been raised "
            "against it, so its lines can no longer be rewritten.")

    order.doc_date = payload.doc_date
    order.warehouse_id = service.resolve_warehouse(db, order.company_id,
                                                   _uid(payload.warehouse_id))
    order.department = payload.department
    order.requested_by = payload.requested_by
    order.required_date = payload.required_date
    order.priority = payload.priority
    order.purpose = payload.purpose
    order.source = payload.source
    order.remarks = payload.remarks
    order.updated_by = user.id
    _apply_iho_lines(db, order, payload.lines)
    db.commit()
    db.refresh(order)
    return _iho_detail(db, order)


@router.post("/in-house-orders/{order_id}/status")
def set_in_house_order_status(
    order_id: uuid.UUID,
    payload: s.StatusChangeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.in_house_orders.approve")),
):
    order = _owned_iho(db, order_id)
    service.check_transition(service.IHO_TRANSITIONS, order.status,
                             payload.status, "in-house order")
    if payload.status == "Submitted":
        order.submitted_at = date.today()
    if payload.status == "Approved":
        order.approved_at = date.today()
        order.approved_by = user.id
        # Approving is what releases it to procurement, so it goes straight
        # on rather than waiting for somebody to move it again by hand.
        order.status = "Approved"
        db.flush()
        order.status = "Pending Procurement"
    else:
        order.status = payload.status
    order.updated_by = user.id
    db.commit()
    return {"id": str(order.id), "status": order.status}


@router.get("/in-house-orders/{order_id}/outstanding")
def in_house_order_outstanding(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.purchase_orders.create")),
):
    """What is still to be bought — the list the PO builder works from."""
    order = _owned_iho(db, order_id)
    return {
        "id": str(order.id),
        "doc_number": order.doc_number,
        "status": order.status,
        "lines": service.outstanding_requirements(db, order),
    }


# ========================================================== purchase orders

def _extra_charges(payload) -> Decimal:
    return sum((Decimal(str(getattr(payload, f) or 0)) for f in ("packing_amount", "insurance_amount", "other_charges")),
               Decimal("0"))


def _po_summary(order: m.PurchaseOrder, suppliers: dict, warehouses: dict) -> dict:
    return {
        "revision": order.revision,
        **{f: getattr(order, f) for f in TEMPLATE_FIELDS},
        **{f: float(getattr(order, f) or 0) for f in TEMPLATE_AMOUNTS},
        "id": str(order.id),
        "doc_number": order.doc_number,
        "doc_date": order.doc_date,
        "purchase_type": order.purchase_type,
        "supplier_id": str(order.supplier_id),
        "supplier": suppliers.get(order.supplier_id),
        "supplier_country": order.supplier_country,
        "country_of_origin": order.country_of_origin,
        "warehouse": warehouses.get(order.warehouse_id),
        "in_house_order_id": (
            str(order.in_house_order_id) if order.in_house_order_id else None),
        "status": order.status,
        "po_status": order.po_status,
        "purchaser": order.purchaser,
        "currency": order.currency,
        "exchange_rate": float(order.exchange_rate),
        "incoterm": order.incoterm,
        "lc_number": order.lc_number,
        "expected_delivery_date": order.expected_delivery_date,
        "priority": order.priority,
        "expected_arrival_date": order.expected_arrival_date,
        "payment_terms": order.payment_terms,
        "remarks": order.remarks,
        "excluding_tax_value": float(order.excluding_tax_value),
        "sales_tax_value": float(order.sales_tax_value),
        "gross_amount": float(order.gross_amount),
        "discount_amount": float(order.discount_amount),
        "freight_amount": float(order.freight_amount),
        "net_payable": float(order.net_payable),
        "net_payable_base": float(order.net_payable_base),
        "total_items": order.total_items,
    }


def _po_detail(db: Session, order: m.PurchaseOrder) -> dict:
    suppliers = _names(db, [order.supplier_id])
    warehouses = _warehouses(db, [order.warehouse_id]
                             + [l.warehouse_id for l in order.lines])
    data = _po_summary(order, suppliers, warehouses)
    data.update({
        "branch_id": str(order.branch_id) if order.branch_id else None,
        "warehouse_id": str(order.warehouse_id) if order.warehouse_id else None,
        "purchaser_email": order.purchaser_email,
        "contact_number": order.contact_number,
        "po_type": order.po_type,
        "expiry_date": order.expiry_date,
        "target_date": order.target_date,
        "delivery_terms": order.delivery_terms,
        "shipping_terms": order.shipping_terms,
        "credit_days": order.credit_days,
        "indent_number": order.indent_number,
        "supplier_quotation_number": order.supplier_quotation_number,
        "supplier_quotation_date": order.supplier_quotation_date,
        "exchange_rate_date": order.exchange_rate_date,
        "shipping_mode": order.shipping_mode,
        "port_of_loading": order.port_of_loading,
        "port_of_discharge": order.port_of_discharge,
        "expected_shipment_date": order.expected_shipment_date,
        "commercial_invoice_number": order.commercial_invoice_number,
        "commercial_invoice_date": order.commercial_invoice_date,
        "packing_list_number": order.packing_list_number,
        "bill_of_lading_number": order.bill_of_lading_number,
        "airway_bill_number": order.airway_bill_number,
        "container_number": order.container_number,
        "lc_date": order.lc_date,
        "bank_name": order.bank_name,
        "freight_forwarder": order.freight_forwarder,
        "clearing_agent": order.clearing_agent,
        "insurance_provider": order.insurance_provider,
        "customs_reference": order.customs_reference,
        "import_reference": order.import_reference,
        "lines": [
            {
                "id": str(line.id),
                "line_number": line.line_number,
                "in_house_order_line_id": (
                    str(line.in_house_order_line_id)
                    if line.in_house_order_line_id else None),
                "item_id": str(line.item_id) if line.item_id else None,
                "item_code": line.item_code,
                "description": line.description,
                "uom": line.uom,
                "hs_code": line.hs_code,
                "origin_country": line.origin_country,
                "quantity": float(line.quantity),
                "free_quantity": float(line.free_quantity),
                "shipped_quantity": float(line.shipped_quantity),
                "received_quantity": float(line.received_quantity),
                "outstanding_quantity": float(max(
                    ZERO, line.quantity - line.received_quantity)),
                "unit_price": float(line.unit_price),
                "discount_percent": float(line.discount_percent),
                "tax_percent": float(line.tax_percent),
                "gross_amount": float(line.gross_amount),
                "discount_amount": float(line.discount_amount),
                "taxable_amount": float(line.taxable_amount),
                "tax_amount": float(line.tax_amount),
                "net_amount": float(line.net_amount),
                "unit_weight": float(line.unit_weight) if line.unit_weight else None,
                "unit_volume": float(line.unit_volume) if line.unit_volume else None,
                "warehouse_id": str(line.warehouse_id) if line.warehouse_id else None,
                "required_date": line.required_date,
                "remarks": line.remarks,
            }
            for line in order.lines
        ],
    })
    return data


def _owned_po(db: Session, order_id: uuid.UUID) -> m.PurchaseOrder:
    order = db.scalar(
        select(m.PurchaseOrder)
        .options(selectinload(m.PurchaseOrder.lines))
        .where(m.PurchaseOrder.id == order_id,
               m.PurchaseOrder.company_id == active_company_id(db))
    )
    if order is None:
        raise HTTPException(404, "That purchase order does not exist.")
    return order


@router.get("/purchase-orders")
def list_purchase_orders(
    search: str | None = None,
    status_filter: list[str] = Query(default=[], alias="status"),
    purchase_type: str | None = None,
    supplier_id: uuid.UUID | None = None,
    in_house_order_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = "doc_date",
    direction: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.purchase_orders.view")),
):
    company_id = active_company_id(db)
    stmt = select(m.PurchaseOrder).where(m.PurchaseOrder.company_id == company_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            m.PurchaseOrder.doc_number.ilike(like),
            m.PurchaseOrder.remarks.ilike(like),
            m.PurchaseOrder.lc_number.ilike(like),
            m.PurchaseOrder.commercial_invoice_number.ilike(like),
            m.PurchaseOrder.lines.any(m.PurchaseOrderLine.description.ilike(like)),
        ))
    if status_filter:
        stmt = stmt.where(m.PurchaseOrder.status.in_(status_filter))
    if purchase_type:
        stmt = stmt.where(m.PurchaseOrder.purchase_type == purchase_type.title())
    if supplier_id:
        stmt = stmt.where(m.PurchaseOrder.supplier_id == supplier_id)
    if in_house_order_id:
        stmt = stmt.where(m.PurchaseOrder.in_house_order_id == in_house_order_id)
    if date_from:
        stmt = stmt.where(m.PurchaseOrder.doc_date >= date_from)
    if date_to:
        stmt = stmt.where(m.PurchaseOrder.doc_date <= date_to)

    total = db.scalar(stmt.with_only_columns(
        func.count(m.PurchaseOrder.id)).order_by(None)) or 0

    column = {
        "doc_number": m.PurchaseOrder.doc_number,
        "doc_date": m.PurchaseOrder.doc_date,
        "status": m.PurchaseOrder.status,
        "net_payable": m.PurchaseOrder.net_payable,
        "net_payable_base": m.PurchaseOrder.net_payable_base,
    }.get(sort, m.PurchaseOrder.doc_date)
    stmt = stmt.order_by(column.desc() if direction == "desc" else column.asc(),
                         m.PurchaseOrder.doc_number.desc())

    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    suppliers = _names(db, [r.supplier_id for r in rows])
    warehouses = _warehouses(db, [r.warehouse_id for r in rows])
    return {
        "items": [_po_summary(r, suppliers, warehouses) for r in rows],
        "total": total, "page": page, "page_size": page_size,
    }


@router.get("/purchase-orders/{order_id}")
def get_purchase_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.purchase_orders.view")),
):
    return _po_detail(db, _owned_po(db, order_id))


def _write_po_header(order: m.PurchaseOrder, payload: s.PurchaseOrderIn,
                     supplier: BusinessPartner) -> None:
    order.doc_date = payload.doc_date
    order.purchase_type = payload.purchase_type
    order.supplier_id = supplier.id
    order.purchaser = payload.purchaser
    order.purchaser_email = payload.purchaser_email
    order.contact_number = payload.contact_number
    order.po_type = payload.po_type
    order.expiry_date = payload.expiry_date
    order.target_date = payload.target_date
    order.expected_delivery_date = payload.expected_delivery_date
    order.priority = payload.priority if payload.priority in PRIORITIES else "Medium"
    order.payment_terms = payload.payment_terms or supplier.payment_terms
    order.delivery_terms = payload.delivery_terms
    order.shipping_terms = payload.shipping_terms
    order.credit_days = payload.credit_days if payload.credit_days is not None \
        else supplier.credit_days
    order.indent_number = payload.indent_number
    order.supplier_quotation_number = payload.supplier_quotation_number
    order.supplier_quotation_date = payload.supplier_quotation_date
    order.remarks = payload.remarks
    order.currency = payload.currency
    order.exchange_rate = payload.exchange_rate or Decimal("1")
    order.exchange_rate_date = payload.exchange_rate_date or payload.doc_date
    for field in TEMPLATE_FIELDS:
        setattr(order, field, getattr(payload, field))
    for field in TEMPLATE_AMOUNTS:
        setattr(order, field, Decimal(str(getattr(payload, field) or 0)))

    if payload.purchase_type == m.IMPORT:
        order.supplier_country = payload.supplier_country or supplier.country
        order.country_of_origin = payload.country_of_origin or supplier.country_of_origin
        order.incoterm = payload.incoterm or supplier.incoterm
        order.shipping_mode = payload.shipping_mode
        order.port_of_loading = payload.port_of_loading
        order.port_of_discharge = payload.port_of_discharge
        order.expected_shipment_date = payload.expected_shipment_date
        order.expected_arrival_date = payload.expected_arrival_date
        order.commercial_invoice_number = payload.commercial_invoice_number
        order.commercial_invoice_date = payload.commercial_invoice_date
        order.packing_list_number = payload.packing_list_number
        order.bill_of_lading_number = payload.bill_of_lading_number
        order.airway_bill_number = payload.airway_bill_number
        order.container_number = payload.container_number
        order.lc_number = payload.lc_number
        order.lc_date = payload.lc_date
        order.bank_name = payload.bank_name or supplier.bank_name
        order.freight_forwarder = payload.freight_forwarder
        order.clearing_agent = payload.clearing_agent
        order.insurance_provider = payload.insurance_provider
        order.customs_reference = payload.customs_reference
        order.import_reference = payload.import_reference
    else:
        # A local order carries no shipping block. Cleared rather than left
        # behind, so switching a draft from Import to Local does not print a
        # bill of lading on a delivery from Faisalabad.
        for field in ("supplier_country", "country_of_origin", "incoterm", "shipping_mode",
                      "port_of_loading", "port_of_discharge", "expected_shipment_date",
                      "expected_arrival_date", "commercial_invoice_number",
                      "commercial_invoice_date", "packing_list_number",
                      "bill_of_lading_number", "airway_bill_number", "container_number",
                      "lc_number", "lc_date", "freight_forwarder", "clearing_agent",
                      "insurance_provider", "customs_reference", "import_reference"):
            setattr(order, field, None)


@router.post("/purchase-orders", status_code=http.HTTP_201_CREATED)
def create_purchase_order(
    payload: s.PurchaseOrderIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.purchase_orders.create")),
):
    company_id = active_company_id(db)
    supplier = service.require_supplier(db, company_id, payload.supplier_id)
    if payload.purchase_type == m.IMPORT and payload.currency == "PKR":
        raise HTTPException(
            400,
            "An import order in PKR is almost always a mistake — set the supplier's "
            "currency and the exchange rate, or make this a Local purchase.")

    fiscal_year = _fiscal_year(db, company_id)
    prefix = "IPO-" if payload.purchase_type == m.IMPORT else "LPO-"
    order = m.PurchaseOrder(
        company_id=company_id,
        branch_id=_uid(payload.branch_id),
        doc_number=_number(db, company_id, f"purchase_order_{payload.purchase_type.lower()}",
                           fiscal_year, prefix),
        fiscal_year=fiscal_year,
        in_house_order_id=_uid(payload.in_house_order_id),
        warehouse_id=service.resolve_warehouse(db, company_id, _uid(payload.warehouse_id)),
        status="Draft",
        created_by=user.id,
    )
    _write_po_header(order, payload, supplier)
    db.add(order)
    service.apply_po_lines(db, order, [l.model_dump() for l in payload.lines],
                           payload.freight_amount, payload.document_discount, _extra_charges(payload))
    db.flush()
    service.claim_requirement(db, order)
    db.commit()
    db.refresh(order)
    return _po_detail(db, order)


@router.post("/in-house-orders/{order_id}/purchase-orders",
             status_code=http.HTTP_201_CREATED)
def create_purchase_order_from_requirement(
    order_id: uuid.UUID,
    payload: s.PurchaseOrderFromRequirementIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.purchase_orders.create")),
):
    """Raise an order for chosen lines of an approved requirement.

    One requirement can produce several orders — some local, some import —
    so this takes only the lines and quantities asked for and leaves the rest
    outstanding (spec section 10).
    """
    company_id = active_company_id(db)
    iho = _owned_iho(db, order_id)
    if iho.status in ("Draft", "Submitted", "Pending Approval", "Rejected", "Cancelled"):
        raise HTTPException(
            400,
            f"This requirement is {iho.status!r}. Approve it before raising a purchase "
            "order against it.")

    supplier = service.require_supplier(db, company_id, payload.supplier_id)
    purchase_type = (payload.purchase_type or "Local").strip().title()
    by_id = {str(line.id): line for line in iho.lines}

    chosen: list[dict] = []
    for entry in payload.lines:
        line = by_id.get(str(entry.get("line_id")))
        if line is None:
            raise HTTPException(400, "One of the chosen lines is not on this requirement.")
        quantity = Decimal(str(entry.get("quantity") or 0))
        if quantity <= 0:
            continue
        chosen.append({
            "in_house_order_line_id": str(line.id),
            "item_id": str(line.item_id) if line.item_id else None,
            "item_code": line.item_code,
            "description": line.description,
            "uom": line.uom,
            "quantity": quantity,
            "unit_price": Decimal(str(entry.get("unit_price") or 0)),
            "discount_percent": Decimal(str(entry.get("discount_percent") or 0)),
            "tax_percent": Decimal(str(entry.get("tax_percent") or 0)),
            "hs_code": entry.get("hs_code"),
            "unit_weight": entry.get("unit_weight"),
            "unit_volume": entry.get("unit_volume"),
            "required_date": line.required_date,
        })

    if not chosen:
        raise HTTPException(400, "Choose at least one line and a quantity to order.")

    fiscal_year = _fiscal_year(db, company_id)
    prefix = "IPO-" if purchase_type == m.IMPORT else "LPO-"
    currency = payload.currency or supplier.currency or (
        "USD" if purchase_type == m.IMPORT else "PKR")
    order = m.PurchaseOrder(
        company_id=company_id,
        doc_number=_number(db, company_id, f"purchase_order_{purchase_type.lower()}",
                           fiscal_year, prefix),
        doc_date=payload.doc_date or date.today(),
        fiscal_year=fiscal_year,
        purchase_type=purchase_type,
        supplier_id=supplier.id,
        in_house_order_id=iho.id,
        warehouse_id=service.resolve_warehouse(
            db, company_id, _uid(payload.warehouse_id) or iho.warehouse_id),
        status="Draft",
        currency=currency,
        exchange_rate=payload.exchange_rate or Decimal("1"),
        exchange_rate_date=payload.doc_date or date.today(),
        supplier_country=supplier.country if purchase_type == m.IMPORT else None,
        country_of_origin=supplier.country_of_origin if purchase_type == m.IMPORT else None,
        incoterm=supplier.incoterm if purchase_type == m.IMPORT else None,
        payment_terms=supplier.payment_terms,
        credit_days=supplier.credit_days,
        remarks=payload.remarks or f"Raised from requirement {iho.doc_number}",
        created_by=user.id,
    )
    db.add(order)
    service.apply_po_lines(db, order, chosen, ZERO, ZERO)
    db.flush()
    service.claim_requirement(db, order)
    db.commit()
    db.refresh(order)
    return _po_detail(db, order)


@router.put("/purchase-orders/{order_id}")
def update_purchase_order(
    order_id: uuid.UUID,
    payload: s.PurchaseOrderIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.purchase_orders.edit")),
):
    order = _owned_po(db, order_id)
    # An order already approved or sent is re-issued when edited: its revision
    # goes up so the supplier copy shows which version it is (PO / Revision).
    if order.status not in ("Draft", "Pending Approval"):
        order.revision = (order.revision or 0) + 1
    if order.status in ("Fully Received", "Fully Invoiced", "Closed", "Cancelled"):
        raise HTTPException(
            400, f"This order is {order.status!r} and can no longer be edited.")

    supplier = service.require_supplier(db, order.company_id, payload.supplier_id)
    # Hand the old quantities back before the lines are replaced, or the
    # requirement would count both the old and the new.
    service.release_requirement(db, order)
    _write_po_header(order, payload, supplier)
    order.warehouse_id = service.resolve_warehouse(
        db, order.company_id, _uid(payload.warehouse_id))
    order.updated_by = user.id
    service.apply_po_lines(db, order, [l.model_dump() for l in payload.lines],
                           payload.freight_amount, payload.document_discount, _extra_charges(payload))
    db.flush()
    service.claim_requirement(db, order)
    db.commit()
    db.refresh(order)
    return _po_detail(db, order)


@router.post("/purchase-orders/{order_id}/status")
def set_purchase_order_status(
    order_id: uuid.UUID,
    payload: s.StatusChangeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.purchase_orders.approve")),
):
    order = _owned_po(db, order_id)
    service.check_transition(service.PO_TRANSITIONS, order.status,
                             payload.status, "purchase order")
    if payload.status == "Cancelled":
        if any(l.received_quantity > 0 for l in order.lines):
            raise HTTPException(
                400,
                "Goods have already been received against this order. Close it instead, "
                "which keeps the receipts and stops anything further being taken in.")
        service.release_requirement(db, order)
    if payload.status == "Approved":
        order.approved_at = date.today()
        order.approved_by = user.id
        order.status = "Approved"
        db.flush()
        # An approved order is immediately open to receive against; leaving it
        # to a second click only produces orders stuck at Approved.
        order.status = "Open"
    else:
        order.status = payload.status
    order.updated_by = user.id
    db.commit()
    return {"id": str(order.id), "status": order.status}


# ========================================================== import shipments

def _shipment_summary(ship: m.ImportShipment, suppliers: dict, warehouses: dict,
                      po_numbers: dict) -> dict:
    return {
        "id": str(ship.id),
        "doc_number": ship.doc_number,
        "doc_date": ship.doc_date,
        "purchase_order_id": str(ship.purchase_order_id),
        "purchase_order": po_numbers.get(ship.purchase_order_id),
        "supplier_id": str(ship.supplier_id),
        "supplier": suppliers.get(ship.supplier_id),
        "warehouse": warehouses.get(ship.warehouse_id),
        "warehouse_id": str(ship.warehouse_id) if ship.warehouse_id else None,
        "status": ship.status,
        "transit_status": ship.transit_status,
        "customs_status": ship.customs_status,
        "clearance_status": ship.clearance_status,
        "currency": ship.currency,
        "exchange_rate": float(ship.exchange_rate),
        "container_number": ship.container_number,
        "bill_of_lading_number": ship.bill_of_lading_number,
        "airway_bill_number": ship.airway_bill_number,
        "vessel_or_flight": ship.vessel_or_flight,
        "port_of_loading": ship.port_of_loading,
        "port_of_discharge": ship.port_of_discharge,
        "shipping_mode": ship.shipping_mode,
        "clearing_agent": ship.clearing_agent,
        "customs_reference": ship.customs_reference,
        "etd": ship.etd,
        "eta": ship.eta,
        "actual_arrival_date": ship.actual_arrival_date,
        "cleared_date": ship.cleared_date,
        "freight_amount": float(ship.freight_amount),
        "insurance_amount": float(ship.insurance_amount),
        "shipment_value": float(ship.shipment_value),
        "shipment_value_base": float(ship.shipment_value_base),
        "total_quantity": float(ship.total_quantity),
        "total_items": ship.total_items,
        "remarks": ship.remarks,
    }


def _shipment_detail(db: Session, ship: m.ImportShipment) -> dict:
    order = db.get(m.PurchaseOrder, ship.purchase_order_id)
    data = _shipment_summary(
        ship, _names(db, [ship.supplier_id]), _warehouses(db, [ship.warehouse_id]),
        {ship.purchase_order_id: order.doc_number if order else None})
    data["lines"] = [
        {
            "id": str(line.id),
            "line_number": line.line_number,
            "purchase_order_line_id": (
                str(line.purchase_order_line_id) if line.purchase_order_line_id else None),
            "item_id": str(line.item_id) if line.item_id else None,
            "item_code": line.item_code,
            "description": line.description,
            "uom": line.uom,
            "hs_code": line.hs_code,
            "shipped_quantity": float(line.shipped_quantity),
            "received_quantity": float(line.received_quantity),
            "outstanding_quantity": float(max(
                ZERO, line.shipped_quantity - line.received_quantity)),
            "unit_price": float(line.unit_price),
            "line_value": float(line.line_value),
            "total_weight": float(line.total_weight) if line.total_weight else None,
            "total_volume": float(line.total_volume) if line.total_volume else None,
            "remarks": line.remarks,
        }
        for line in ship.lines
    ]
    return data


def _owned_shipment(db: Session, shipment_id: uuid.UUID) -> m.ImportShipment:
    ship = db.scalar(
        select(m.ImportShipment)
        .options(selectinload(m.ImportShipment.lines))
        .where(m.ImportShipment.id == shipment_id,
               m.ImportShipment.company_id == active_company_id(db))
    )
    if ship is None:
        raise HTTPException(404, "That shipment does not exist.")
    return ship


@router.get("/shipments")
def list_shipments(
    search: str | None = None,
    status_filter: list[str] = Query(default=[], alias="status"),
    transit_status: list[str] = Query(default=[]),
    purchase_order_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    in_transit_only: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = "doc_date",
    direction: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.shipments.view")),
):
    """Shipments; with `in_transit_only`, the goods-in-transit report —
    everything shipped and not yet received into a warehouse."""
    company_id = active_company_id(db)
    stmt = select(m.ImportShipment).where(m.ImportShipment.company_id == company_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            m.ImportShipment.doc_number.ilike(like),
            m.ImportShipment.container_number.ilike(like),
            m.ImportShipment.bill_of_lading_number.ilike(like),
            m.ImportShipment.airway_bill_number.ilike(like),
            m.ImportShipment.customs_reference.ilike(like),
            m.ImportShipment.lines.any(m.ImportShipmentLine.description.ilike(like)),
        ))
    if status_filter:
        stmt = stmt.where(m.ImportShipment.status.in_(status_filter))
    if transit_status:
        stmt = stmt.where(m.ImportShipment.transit_status.in_(transit_status))
    if in_transit_only:
        stmt = stmt.where(m.ImportShipment.transit_status.in_(service.IN_TRANSIT_STATES))
    if purchase_order_id:
        stmt = stmt.where(m.ImportShipment.purchase_order_id == purchase_order_id)
    if supplier_id:
        stmt = stmt.where(m.ImportShipment.supplier_id == supplier_id)
    if date_from:
        stmt = stmt.where(m.ImportShipment.doc_date >= date_from)
    if date_to:
        stmt = stmt.where(m.ImportShipment.doc_date <= date_to)

    total = db.scalar(stmt.with_only_columns(
        func.count(m.ImportShipment.id)).order_by(None)) or 0
    column = {
        "doc_number": m.ImportShipment.doc_number,
        "doc_date": m.ImportShipment.doc_date,
        "eta": m.ImportShipment.eta,
        "status": m.ImportShipment.status,
        "transit_status": m.ImportShipment.transit_status,
    }.get(sort, m.ImportShipment.doc_date)
    stmt = stmt.order_by(column.desc() if direction == "desc" else column.asc())

    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    orders = dict(db.execute(
        select(m.PurchaseOrder.id, m.PurchaseOrder.doc_number)
        .where(m.PurchaseOrder.id.in_([r.purchase_order_id for r in rows]))
    ).all()) if rows else {}
    suppliers = _names(db, [r.supplier_id for r in rows])
    warehouses = _warehouses(db, [r.warehouse_id for r in rows])
    return {
        "items": [_shipment_summary(r, suppliers, warehouses, orders) for r in rows],
        "total": total, "page": page, "page_size": page_size,
    }


@router.get("/shipments/{shipment_id}")
def get_shipment(
    shipment_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.shipments.view")),
):
    return _shipment_detail(db, _owned_shipment(db, shipment_id))


def _apply_shipment_lines(db: Session, ship: m.ImportShipment,
                          raw_lines, order: m.PurchaseOrder) -> None:
    """Rebuild the shipment lines and re-claim the shipped quantities.

    A shipment cannot carry more of a line than the order has left unshipped,
    which is checked here: over-shipping is nearly always a typo, and finding
    it now beats reconciling it at the port.
    """
    if not raw_lines:
        raise HTTPException(400, "A shipment needs at least one line.")

    po_lines = {line.id: line for line in order.lines}
    # Hand back what this shipment previously claimed, before re-counting.
    for line in ship.lines:
        if line.purchase_order_line_id in po_lines:
            po_line = po_lines[line.purchase_order_line_id]
            po_line.shipped_quantity = max(
                ZERO, service.qty(po_line.shipped_quantity - line.shipped_quantity))

    new_lines: list[m.ImportShipmentLine] = []
    value = ZERO
    quantity = ZERO
    for index, raw in enumerate(raw_lines, start=1):
        po_line_id = _uid(raw.purchase_order_line_id)
        po_line = po_lines.get(po_line_id) if po_line_id else None
        if po_line_id and po_line is None:
            raise HTTPException(400, f"Line {index}: that order line is not on this order.")

        shipped = service.qty(raw.shipped_quantity)
        if po_line is not None:
            unshipped = po_line.quantity - po_line.shipped_quantity
            if shipped > unshipped:
                raise HTTPException(
                    400,
                    f"{po_line.description[:40]}: {po_line.quantity} was ordered and "
                    f"{po_line.shipped_quantity} already shipped, so {shipped} more "
                    f"exceeds the order by {service.qty(shipped - unshipped)}.")
            po_line.shipped_quantity = service.qty(po_line.shipped_quantity + shipped)

        unit_price = Decimal(str(raw.unit_price or 0)) or (
            po_line.unit_price if po_line is not None else ZERO)
        line_value = money(shipped * unit_price)
        value += line_value
        quantity += shipped

        new_lines.append(m.ImportShipmentLine(
            id=_uid(raw.id) or uuid.uuid4(),
            line_number=index,
            purchase_order_line_id=po_line_id,
            item_id=_uid(raw.item_id) or (po_line.item_id if po_line else None),
            item_code=raw.item_code or (po_line.item_code if po_line else None),
            description=(raw.description or (po_line.description if po_line else "")).strip(),
            uom=raw.uom or (po_line.uom if po_line else None),
            hs_code=raw.hs_code or (po_line.hs_code if po_line else None),
            shipped_quantity=shipped,
            received_quantity=ZERO,
            unit_price=unit_price,
            line_value=line_value,
            total_weight=(Decimal(str(raw.total_weight)) if raw.total_weight is not None
                          else (po_line.unit_weight * shipped
                                if po_line is not None and po_line.unit_weight else None)),
            total_volume=(Decimal(str(raw.total_volume)) if raw.total_volume is not None
                          else (po_line.unit_volume * shipped
                                if po_line is not None and po_line.unit_volume else None)),
            remarks=raw.remarks,
        ))

    ship.lines = new_lines
    ship.total_items = len(new_lines)
    ship.total_quantity = service.qty(quantity)
    ship.shipment_value = money(value)
    ship.shipment_value_base = money(value * (ship.exchange_rate or Decimal("1")))


@router.post("/shipments", status_code=http.HTTP_201_CREATED)
def create_shipment(
    payload: s.ImportShipmentIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.shipments.create")),
):
    company_id = active_company_id(db)
    order = _owned_po(db, _uid(payload.purchase_order_id))
    if order.purchase_type != m.IMPORT:
        raise HTTPException(
            400,
            f"{order.doc_number} is a local purchase. Receive it against the order "
            "directly — shipments and landed costing are for imports.")
    if order.status in ("Draft", "Pending Approval"):
        raise HTTPException(
            400, f"{order.doc_number} is {order.status!r}. Approve it before shipping.")

    fiscal_year = _fiscal_year(db, company_id)
    ship = m.ImportShipment(
        company_id=company_id,
        doc_number=_number(db, company_id, "import_shipment", fiscal_year, "SHP-"),
        doc_date=payload.doc_date,
        fiscal_year=fiscal_year,
        purchase_order_id=order.id,
        supplier_id=order.supplier_id,
        warehouse_id=service.resolve_warehouse(
            db, company_id, _uid(payload.warehouse_id) or order.warehouse_id),
        status="Draft",
        transit_status=payload.transit_status,
        customs_status=payload.customs_status,
        clearance_status=payload.clearance_status,
        currency=payload.currency or order.currency,
        exchange_rate=payload.exchange_rate or order.exchange_rate or Decimal("1"),
        exchange_rate_date=payload.exchange_rate_date or payload.doc_date,
        container_number=payload.container_number or order.container_number,
        bill_of_lading_number=payload.bill_of_lading_number,
        airway_bill_number=payload.airway_bill_number,
        vessel_or_flight=payload.vessel_or_flight,
        port_of_loading=payload.port_of_loading or order.port_of_loading,
        port_of_discharge=payload.port_of_discharge or order.port_of_discharge,
        shipping_mode=payload.shipping_mode or order.shipping_mode,
        clearing_agent=payload.clearing_agent or order.clearing_agent,
        customs_reference=payload.customs_reference,
        etd=payload.etd,
        eta=payload.eta,
        actual_arrival_date=payload.actual_arrival_date,
        cleared_date=payload.cleared_date,
        freight_amount=payload.freight_amount,
        insurance_amount=payload.insurance_amount,
        remarks=payload.remarks,
        created_by=user.id,
    )
    db.add(ship)
    _apply_shipment_lines(db, ship, payload.lines, order)
    db.commit()
    db.refresh(ship)
    return _shipment_detail(db, ship)


@router.put("/shipments/{shipment_id}")
def update_shipment(
    shipment_id: uuid.UUID,
    payload: s.ImportShipmentIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.shipments.edit")),
):
    ship = _owned_shipment(db, shipment_id)
    if ship.status in ("Fully Received", "Closed", "Cancelled"):
        raise HTTPException(
            400, f"This shipment is {ship.status!r} and can no longer be edited.")
    if any(line.received_quantity > 0 for line in ship.lines):
        raise HTTPException(
            400,
            "Goods from this shipment have already been received, so its lines cannot "
            "be rewritten. Reverse the receipt first if it was wrong.")

    order = _owned_po(db, ship.purchase_order_id)
    ship.doc_date = payload.doc_date
    ship.warehouse_id = service.resolve_warehouse(
        db, ship.company_id, _uid(payload.warehouse_id))
    ship.customs_status = payload.customs_status
    ship.clearance_status = payload.clearance_status
    ship.currency = payload.currency
    ship.exchange_rate = payload.exchange_rate or Decimal("1")
    ship.exchange_rate_date = payload.exchange_rate_date or payload.doc_date
    for field in ("container_number", "bill_of_lading_number", "airway_bill_number",
                  "vessel_or_flight", "port_of_loading", "port_of_discharge",
                  "shipping_mode", "clearing_agent", "customs_reference",
                  "etd", "eta", "actual_arrival_date", "cleared_date",
                  "freight_amount", "insurance_amount", "remarks"):
        setattr(ship, field, getattr(payload, field))
    ship.updated_by = user.id
    _apply_shipment_lines(db, ship, payload.lines, order)
    db.commit()
    db.refresh(ship)
    return _shipment_detail(db, ship)


@router.post("/shipments/{shipment_id}/status")
def set_shipment_status(
    shipment_id: uuid.UUID,
    payload: s.StatusChangeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.shipments.edit")),
):
    """Move a shipment along, and keep where-the-goods-are in step with it.

    `transit_status` is derived from the document status rather than typed
    separately, so the two cannot disagree about whether the goods have
    landed (spec sections 20 and 41).
    """
    ship = _owned_shipment(db, shipment_id)
    service.check_transition(service.SHIPMENT_TRANSITIONS, ship.status,
                             payload.status, "shipment")

    transit = m.TRANSIT_FROM_STATUS.get(payload.status)
    if transit:
        ship.transit_status = transit
    if payload.status == "Arrived" and not ship.actual_arrival_date:
        ship.actual_arrival_date = date.today()
    if payload.status == "Customs Cleared":
        ship.customs_status = "Cleared"
        if not ship.cleared_date:
            ship.cleared_date = date.today()

    ship.status = payload.status
    ship.updated_by = user.id
    db.commit()
    return {"id": str(ship.id), "status": ship.status,
            "transit_status": ship.transit_status}


# ============================================================== charge types

@router.get("/charge-types")
def list_charge_types(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.landed_costs.view")),
):
    """The import costs this company meets.

    Seeded on first use with the charges a Pakistani importer normally faces,
    so the module is usable immediately without anybody typing two dozen
    rows; from then on they are ordinary editable master data.
    """
    company_id = active_company_id(db)
    stmt = select(m.LandedCostChargeType).where(
        m.LandedCostChargeType.company_id == company_id)
    if not include_inactive:
        stmt = stmt.where(m.LandedCostChargeType.is_active.is_(True))
    rows = db.scalars(stmt.order_by(m.LandedCostChargeType.sort_order,
                                    m.LandedCostChargeType.name)).all()

    if not rows and not include_inactive:
        db.add_all(service.default_charge_types(company_id))
        db.commit()
        rows = db.scalars(stmt.order_by(m.LandedCostChargeType.sort_order,
                                        m.LandedCostChargeType.name)).all()

    return {
        "items": [
            {
                "id": str(row.id),
                "name": row.name,
                "cost_group": row.cost_group,
                "default_allocation": row.default_allocation,
                "default_rate_percent": (float(row.default_rate_percent)
                                         if row.default_rate_percent else None),
                "account_code": row.account_code,
                "is_inventoriable": row.is_inventoriable,
                "is_active": row.is_active,
                "sort_order": row.sort_order,
            }
            for row in rows
        ],
        "cost_groups": list(m.COST_GROUPS),
        "allocation_methods": list(m.ALLOCATION_METHODS),
    }


@router.post("/charge-types", status_code=http.HTTP_201_CREATED)
def create_charge_type(
    payload: s.ChargeTypeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.landed_costs.edit")),
):
    company_id = active_company_id(db)
    if db.scalar(select(m.LandedCostChargeType).where(
        m.LandedCostChargeType.company_id == company_id,
        func.lower(m.LandedCostChargeType.name) == payload.name.strip().lower(),
    )):
        raise HTTPException(400, f"A charge called '{payload.name}' already exists.")
    row = m.LandedCostChargeType(
        company_id=company_id, created_by=user.id, **payload.model_dump())
    db.add(row)
    db.commit()
    return {"id": str(row.id), "name": row.name, "cost_group": row.cost_group}


@router.put("/charge-types/{charge_type_id}")
def update_charge_type(
    charge_type_id: uuid.UUID,
    payload: s.ChargeTypeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.landed_costs.edit")),
):
    row = db.get(m.LandedCostChargeType, charge_type_id)
    if row is None or row.company_id != active_company_id(db):
        raise HTTPException(404, "That charge type does not exist.")
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    row.updated_by = user.id
    db.commit()
    return {"id": str(row.id), "name": row.name}


# ============================================================= landed costing

def _landed_summary(voucher: m.LandedCost, suppliers: dict,
                    po_numbers: dict, ship_numbers: dict) -> dict:
    purchase = voucher.purchase_cost_base or ZERO
    return {
        "id": str(voucher.id),
        "doc_number": voucher.doc_number,
        "doc_date": voucher.doc_date,
        "purchase_order_id": (
            str(voucher.purchase_order_id) if voucher.purchase_order_id else None),
        "purchase_order": po_numbers.get(voucher.purchase_order_id),
        "shipment_id": str(voucher.shipment_id) if voucher.shipment_id else None,
        "shipment": ship_numbers.get(voucher.shipment_id),
        "supplier_id": str(voucher.supplier_id) if voucher.supplier_id else None,
        "supplier": suppliers.get(voucher.supplier_id),
        "status": voucher.status,
        "is_posted": voucher.is_posted,
        "currency": voucher.currency,
        "exchange_rate": float(voucher.exchange_rate),
        "allocation_method": voucher.allocation_method,
        "supplier_invoice_number": voucher.supplier_invoice_number,
        "supplier_invoice_date": voucher.supplier_invoice_date,
        "customs_reference": voucher.customs_reference,
        "purchase_cost_base": float(purchase),
        "additional_cost_base": float(voucher.additional_cost_base),
        "total_landed_cost": float(voucher.total_landed_cost),
        # What the import added on top of the goods, as a percentage — the
        # single number that says whether an import was expensive.
        "additional_cost_percent": (
            float(round(voucher.additional_cost_base / purchase * 100, 2))
            if purchase else None),
        "total_quantity": float(voucher.total_quantity),
        "total_items": voucher.total_items,
        "remarks": voucher.remarks,
    }


def _landed_detail(db: Session, voucher: m.LandedCost) -> dict:
    order = db.get(m.PurchaseOrder, voucher.purchase_order_id) \
        if voucher.purchase_order_id else None
    ship = db.get(m.ImportShipment, voucher.shipment_id) if voucher.shipment_id else None
    vendors = _names(db, [voucher.supplier_id] + [c.vendor_id for c in voucher.charges])

    data = _landed_summary(
        voucher, vendors,
        {voucher.purchase_order_id: order.doc_number if order else None},
        {voucher.shipment_id: ship.doc_number if ship else None})
    data["charges"] = [
        {
            "id": str(charge.id),
            "charge_type_id": str(charge.charge_type_id) if charge.charge_type_id else None,
            "name": charge.name,
            "cost_group": charge.cost_group,
            "vendor_id": str(charge.vendor_id) if charge.vendor_id else None,
            "vendor": vendors.get(charge.vendor_id),
            "reference": charge.reference,
            "currency": charge.currency,
            "exchange_rate": float(charge.exchange_rate),
            "amount": float(charge.amount),
            "amount_base": float(charge.amount_base),
            "allocation_method": charge.allocation_method,
            "is_inventoriable": charge.is_inventoriable,
            "remarks": charge.remarks,
        }
        for charge in sorted(voucher.charges, key=lambda c: (c.cost_group, c.name))
    ]
    data["items"] = [
        {
            "id": str(item.id),
            "line_number": item.line_number,
            "purchase_order_line_id": (
                str(item.purchase_order_line_id) if item.purchase_order_line_id else None),
            "shipment_line_id": (
                str(item.shipment_line_id) if item.shipment_line_id else None),
            "item_id": str(item.item_id) if item.item_id else None,
            "item_code": item.item_code,
            "description": item.description,
            "uom": item.uom,
            "hs_code": item.hs_code,
            "quantity": float(item.quantity),
            "total_weight": float(item.total_weight) if item.total_weight else None,
            "total_volume": float(item.total_volume) if item.total_volume else None,
            "manual_share_percent": (float(item.manual_share_percent)
                                     if item.manual_share_percent else None),
            "unit_price": float(item.unit_price),
            "purchase_cost": float(item.purchase_cost),
            "purchase_cost_base": float(item.purchase_cost_base),
            "freight_cost": float(item.freight_cost),
            "insurance_cost": float(item.insurance_cost),
            "customs_cost": float(item.customs_cost),
            "tax_cost": float(item.tax_cost),
            "port_cost": float(item.port_cost),
            "clearing_cost": float(item.clearing_cost),
            "bank_cost": float(item.bank_cost),
            "other_cost": float(item.other_cost),
            "additional_cost": float(item.additional_cost),
            "total_landed_cost": float(item.total_landed_cost),
            "unit_landed_cost": float(item.unit_landed_cost),
            "unit_purchase_cost": float(
                item.purchase_cost_base / item.quantity) if item.quantity else 0.0,
        }
        for item in voucher.items
    ]
    return data


def _owned_landed(db: Session, voucher_id: uuid.UUID) -> m.LandedCost:
    voucher = db.scalar(
        select(m.LandedCost)
        .options(selectinload(m.LandedCost.charges), selectinload(m.LandedCost.items))
        .where(m.LandedCost.id == voucher_id,
               m.LandedCost.company_id == active_company_id(db))
    )
    if voucher is None:
        raise HTTPException(404, "That landed costing does not exist.")
    return voucher


@router.get("/landed-costs")
def list_landed_costs(
    search: str | None = None,
    status_filter: list[str] = Query(default=[], alias="status"),
    purchase_order_id: uuid.UUID | None = None,
    shipment_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    posted_only: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = "doc_date",
    direction: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.landed_costs.view")),
):
    company_id = active_company_id(db)
    stmt = select(m.LandedCost).where(m.LandedCost.company_id == company_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            m.LandedCost.doc_number.ilike(like),
            m.LandedCost.supplier_invoice_number.ilike(like),
            m.LandedCost.customs_reference.ilike(like),
            m.LandedCost.remarks.ilike(like),
        ))
    if status_filter:
        stmt = stmt.where(m.LandedCost.status.in_(status_filter))
    if posted_only:
        stmt = stmt.where(m.LandedCost.is_posted.is_(True))
    if purchase_order_id:
        stmt = stmt.where(m.LandedCost.purchase_order_id == purchase_order_id)
    if shipment_id:
        stmt = stmt.where(m.LandedCost.shipment_id == shipment_id)
    if supplier_id:
        stmt = stmt.where(m.LandedCost.supplier_id == supplier_id)
    if date_from:
        stmt = stmt.where(m.LandedCost.doc_date >= date_from)
    if date_to:
        stmt = stmt.where(m.LandedCost.doc_date <= date_to)

    total = db.scalar(stmt.with_only_columns(
        func.count(m.LandedCost.id)).order_by(None)) or 0
    column = {
        "doc_number": m.LandedCost.doc_number,
        "doc_date": m.LandedCost.doc_date,
        "status": m.LandedCost.status,
        "total_landed_cost": m.LandedCost.total_landed_cost,
    }.get(sort, m.LandedCost.doc_date)
    stmt = stmt.order_by(column.desc() if direction == "desc" else column.asc())

    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    suppliers = _names(db, [r.supplier_id for r in rows])
    orders = dict(db.execute(
        select(m.PurchaseOrder.id, m.PurchaseOrder.doc_number)
        .where(m.PurchaseOrder.id.in_([r.purchase_order_id for r in rows if
                                       r.purchase_order_id]))
    ).all()) if rows else {}
    ships = dict(db.execute(
        select(m.ImportShipment.id, m.ImportShipment.doc_number)
        .where(m.ImportShipment.id.in_([r.shipment_id for r in rows if r.shipment_id]))
    ).all()) if rows else {}
    return {
        "items": [_landed_summary(r, suppliers, orders, ships) for r in rows],
        "total": total, "page": page, "page_size": page_size,
    }


@router.get("/landed-costs/{voucher_id}")
def get_landed_cost(
    voucher_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.landed_costs.view")),
):
    return _landed_detail(db, _owned_landed(db, voucher_id))


def _charge_rows(db: Session, company_id: uuid.UUID, voucher: m.LandedCost,
                 raw_charges) -> list[m.LandedCostCharge]:
    rows: list[m.LandedCostCharge] = []
    for raw in raw_charges:
        charge_type = None
        if raw.charge_type_id:
            charge_type = db.get(m.LandedCostChargeType, _uid(raw.charge_type_id))
            if charge_type is None or charge_type.company_id != company_id:
                raise HTTPException(400, "One of the charges names a type that does not exist.")

        name = (raw.name or (charge_type.name if charge_type else "")).strip()
        group = (raw.cost_group or (charge_type.cost_group if charge_type else "")).strip()
        if not name or group not in m.COST_GROUPS:
            raise HTTPException(
                400,
                "Every charge needs a name and a cost group from: "
                f"{', '.join(m.COST_GROUPS)}.")

        rows.append(m.LandedCostCharge(
            id=_uid(raw.id) or uuid.uuid4(),
            charge_type_id=charge_type.id if charge_type else None,
            name=name,
            cost_group=group,
            vendor_id=_uid(raw.vendor_id),
            reference=raw.reference,
            currency=raw.currency,
            exchange_rate=raw.exchange_rate or Decimal("1"),
            amount=Decimal(str(raw.amount or 0)),
            allocation_method=(
                raw.allocation_method
                or (charge_type.default_allocation if charge_type else None)
                or voucher.allocation_method),
            is_inventoriable=(
                raw.is_inventoriable if raw.is_inventoriable is not None
                else (charge_type.is_inventoriable if charge_type else True)),
            remarks=raw.remarks,
        ))
    return rows


def _item_rows(db: Session, raw_items) -> list[m.LandedCostItem]:
    rows: list[m.LandedCostItem] = []
    for index, raw in enumerate(raw_items, start=1):
        description = (raw.description or "").strip()
        if not description:
            raise HTTPException(400, f"Item {index}: a description is required.")
        rows.append(m.LandedCostItem(
            id=_uid(raw.id) or uuid.uuid4(),
            line_number=index,
            purchase_order_line_id=_uid(raw.purchase_order_line_id),
            shipment_line_id=_uid(raw.shipment_line_id),
            item_id=_uid(raw.item_id),
            item_code=raw.item_code,
            description=description,
            uom=raw.uom,
            hs_code=raw.hs_code,
            quantity=service.qty(raw.quantity),
            total_weight=(Decimal(str(raw.total_weight))
                          if raw.total_weight is not None else None),
            total_volume=(Decimal(str(raw.total_volume))
                          if raw.total_volume is not None else None),
            manual_share_percent=(Decimal(str(raw.manual_share_percent))
                                  if raw.manual_share_percent is not None else None),
            unit_price=Decimal(str(raw.unit_price or 0)),
        ))
    return rows


@router.post("/landed-costs", status_code=http.HTTP_201_CREATED)
def create_landed_cost(
    payload: s.LandedCostIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.landed_costs.create")),
):
    company_id = active_company_id(db)
    fiscal_year = _fiscal_year(db, company_id)
    voucher = m.LandedCost(
        company_id=company_id,
        doc_number=_number(db, company_id, "landed_cost", fiscal_year, "LC-"),
        doc_date=payload.doc_date,
        fiscal_year=fiscal_year,
        purchase_order_id=_uid(payload.purchase_order_id),
        shipment_id=_uid(payload.shipment_id),
        supplier_id=_uid(payload.supplier_id),
        status="Draft",
        currency=payload.currency,
        exchange_rate=payload.exchange_rate,
        exchange_rate_date=payload.exchange_rate_date or payload.doc_date,
        allocation_method=payload.allocation_method,
        supplier_invoice_number=payload.supplier_invoice_number,
        supplier_invoice_date=payload.supplier_invoice_date,
        customs_reference=payload.customs_reference,
        remarks=payload.remarks,
        created_by=user.id,
    )
    db.add(voucher)
    voucher.charges = _charge_rows(db, company_id, voucher, payload.charges)
    voucher.items = _item_rows(db, payload.items)
    if voucher.items:
        service.cost_landed(db, voucher)
    db.commit()
    db.refresh(voucher)
    return _landed_detail(db, voucher)


@router.post("/shipments/{shipment_id}/landed-cost", status_code=http.HTTP_201_CREATED)
def start_landed_cost_from_shipment(
    shipment_id: uuid.UUID,
    payload: s.LandedCostFromShipmentIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.landed_costs.create")),
):
    """Open a costing pre-filled from a shipment.

    Brings across the goods with their quantities, prices, weights and
    volumes, and — unless told otherwise — the freight and insurance already
    recorded on the shipment, so the person costing it starts from what is
    known rather than a blank form.
    """
    company_id = active_company_id(db)
    ship = _owned_shipment(db, shipment_id)
    order = _owned_po(db, ship.purchase_order_id)

    # Hold the shipment while checking, so a double click queues behind the first
    # request and then finds its costing (LC-2600006 / 07 were made 15ms apart).
    # The unique index uq_landed_cost_live_per_shipment backs this up.
    db.execute(select(m.ImportShipment.id).where(m.ImportShipment.id == ship.id).with_for_update())
    existing = db.scalar(
        select(m.LandedCost).where(m.LandedCost.shipment_id == ship.id,
                                   m.LandedCost.status != "Cancelled"))
    if existing is not None:
        raise HTTPException(
            400,
            f"{ship.doc_number} already has costing {existing.doc_number} "
            f"({existing.status}). Edit that one rather than starting a second.")

    fiscal_year = _fiscal_year(db, company_id)
    voucher = m.LandedCost(
        company_id=company_id,
        doc_number=_number(db, company_id, "landed_cost", fiscal_year, "LC-"),
        doc_date=payload.doc_date or date.today(),
        fiscal_year=fiscal_year,
        purchase_order_id=order.id,
        shipment_id=ship.id,
        supplier_id=ship.supplier_id,
        status="Cost Entry",
        currency=ship.currency,
        exchange_rate=payload.exchange_rate or ship.exchange_rate or Decimal("1"),
        exchange_rate_date=date.today(),
        allocation_method=payload.allocation_method,
        supplier_invoice_number=order.commercial_invoice_number,
        supplier_invoice_date=order.commercial_invoice_date,
        customs_reference=ship.customs_reference or order.customs_reference,
        remarks=f"Costing for shipment {ship.doc_number}",
        created_by=user.id,
    )
    db.add(voucher)

    voucher.items = [
        m.LandedCostItem(
            line_number=index,
            purchase_order_line_id=line.purchase_order_line_id,
            shipment_line_id=line.id,
            item_id=line.item_id,
            item_code=line.item_code,
            description=line.description,
            uom=line.uom,
            hs_code=line.hs_code,
            quantity=line.shipped_quantity,
            total_weight=line.total_weight,
            total_volume=line.total_volume,
            unit_price=line.unit_price,
        )
        for index, line in enumerate(ship.lines, start=1)
    ]

    if payload.include_shipment_charges:
        types = {row.name: row for row in db.scalars(
            select(m.LandedCostChargeType).where(
                m.LandedCostChargeType.company_id == company_id)).all()}
        for name, group, amount in (
            ("Ocean Freight", "Freight", ship.freight_amount),
            ("Marine Insurance", "Insurance", ship.insurance_amount),
        ):
            if not amount:
                continue
            charge_type = types.get(name)
            voucher.charges.append(m.LandedCostCharge(
                charge_type_id=charge_type.id if charge_type else None,
                name=name,
                cost_group=group,
                # The shipment holds these two in PKR (see ImportShipment),
                # so they come across at rate 1 — converting them again by
                # the goods' rate is how freight becomes 280 times too big.
                currency="PKR",
                exchange_rate=Decimal("1"),
                amount=amount,
                allocation_method=(charge_type.default_allocation
                                   if charge_type else voucher.allocation_method),
                is_inventoriable=True,
                remarks=f"From shipment {ship.doc_number}",
            ))

    if voucher.items:
        service.cost_landed(db, voucher)
    db.commit()
    db.refresh(voucher)
    return _landed_detail(db, voucher)


@router.put("/landed-costs/{voucher_id}")
def update_landed_cost(
    voucher_id: uuid.UUID,
    payload: s.LandedCostIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.landed_costs.create")),
):
    voucher = _owned_landed(db, voucher_id)
    if voucher.is_posted:
        raise HTTPException(
            400,
            f"{voucher.doc_number} is posted. Its unit costs are already in the stock "
            "ledger, so it cannot be edited — raise a correcting voucher instead.")
    if voucher.status == "Cancelled":
        raise HTTPException(400, "This costing is cancelled.")

    voucher.doc_date = payload.doc_date
    voucher.supplier_id = _uid(payload.supplier_id) or voucher.supplier_id
    voucher.currency = payload.currency
    voucher.exchange_rate = payload.exchange_rate
    voucher.exchange_rate_date = payload.exchange_rate_date or payload.doc_date
    voucher.allocation_method = payload.allocation_method
    voucher.supplier_invoice_number = payload.supplier_invoice_number
    voucher.supplier_invoice_date = payload.supplier_invoice_date
    voucher.customs_reference = payload.customs_reference
    voucher.remarks = payload.remarks
    voucher.updated_by = user.id

    voucher.charges = _charge_rows(db, voucher.company_id, voucher, payload.charges)
    if payload.items:
        voucher.items = _item_rows(db, payload.items)
    db.flush()
    service.cost_landed(db, voucher)
    db.commit()
    db.refresh(voucher)
    return _landed_detail(db, voucher)


@router.post("/landed-costs/{voucher_id}/status")
def set_landed_cost_status(
    voucher_id: uuid.UUID,
    payload: s.StatusChangeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.landed_costs.post")),
):
    """Move a costing along. Posting is what fixes the unit costs.

    Until a costing is posted the goods have no landed cost to come into
    stock at; after it, the figures are history and the voucher is read-only
    (spec section 42).
    """
    voucher = _owned_landed(db, voucher_id)
    service.check_transition(service.LANDED_COST_TRANSITIONS, voucher.status,
                             payload.status, "landed costing")

    if payload.status == "Approved":
        voucher.approved_at = date.today()
        voucher.approved_by = user.id
    if payload.status == "Posted":
        if not voucher.items:
            raise HTTPException(400, "There are no goods on this costing to cost.")
        if not voucher.charges:
            raise HTTPException(
                400,
                "There are no import costs on this costing, so it would post the "
                "supplier price as the landed cost. Add the charges first.")
        # Re-cost at the moment of posting: a charge edited after the last
        # calculation must not post stale unit costs into the ledger.
        service.cost_landed(db, voucher)
        voucher.is_posted = True
        voucher.posted_at = date.today()
        voucher.posted_by = user.id

    voucher.status = payload.status
    voucher.updated_by = user.id
    db.commit()
    return {
        "id": str(voucher.id),
        "status": voucher.status,
        "is_posted": voucher.is_posted,
        "total_landed_cost": float(voucher.total_landed_cost),
    }


# ============================================================ goods receipts

def _grn_summary(grn: m.MaterialReceivingNote, suppliers: dict,
                 warehouses: dict, po_numbers: dict) -> dict:
    return {
        "id": str(grn.id),
        "doc_number": grn.doc_number,
        "doc_date": grn.doc_date,
        "supplier_id": str(grn.supplier_id),
        "supplier": suppliers.get(grn.supplier_id),
        "purchase_order_id": (
            str(grn.purchase_order_id) if grn.purchase_order_id else None),
        "purchase_order": po_numbers.get(grn.purchase_order_id),
        "shipment_id": str(grn.shipment_id) if grn.shipment_id else None,
        "in_house_order_id": (
            str(grn.in_house_order_id) if grn.in_house_order_id else None),
        "landed_cost_id": str(grn.landed_cost_id) if grn.landed_cost_id else None,
        "warehouse": warehouses.get(grn.warehouse_id),
        "warehouse_id": str(grn.warehouse_id) if grn.warehouse_id else None,
        "supplier_invoice_number": grn.supplier_invoice_number,
        "supplier_invoice_date": grn.supplier_invoice_date,
        "vehicle_number": grn.vehicle_number,
        "received_by": grn.received_by,
        "delivery_note_number": grn.delivery_note_number,
        "delivery_date": grn.delivery_date,
        "transporter": grn.transporter,
        "gd_reference": grn.gd_reference,
        "inspection_notes": grn.inspection_notes,
        "discrepancy_notes": grn.discrepancy_notes,
        "checked_by": grn.checked_by,
        "bill_to_finance": grn.bill_to_finance,
        "status": grn.status,
        "is_posted": grn.is_posted,
        "posted_at": grn.posted_at,
        "currency": grn.currency,
        "excluding_tax_value": float(grn.excluding_tax_value),
        "sales_tax_value": float(grn.sales_tax_value),
        "gross_amount": float(grn.gross_amount),
        "net_payable": float(grn.net_payable),
        "total_items": grn.total_items,
        "remarks": grn.remarks,
    }


def _grn_detail(db: Session, grn: m.MaterialReceivingNote) -> dict:
    order = db.get(m.PurchaseOrder, grn.purchase_order_id) if grn.purchase_order_id else None
    data = _grn_summary(
        grn, _names(db, [grn.supplier_id]),
        _warehouses(db, [grn.warehouse_id] + [l.warehouse_id for l in grn.lines]),
        {grn.purchase_order_id: order.doc_number if order else None})
    data["lines"] = [
        {
            "id": str(line.id),
            "line_number": line.line_number,
            "purchase_order_line_id": (
                str(line.purchase_order_line_id) if line.purchase_order_line_id else None),
            "shipment_line_id": (
                str(line.shipment_line_id) if line.shipment_line_id else None),
            "item_id": str(line.item_id) if line.item_id else None,
            "item_code": line.item_code,
            "description": line.description,
            "uom": line.uom,
            "ordered_quantity": float(line.ordered_quantity),
            "received_quantity": float(line.received_quantity),
            "remaining_quantity": float(line.remaining_quantity),
            "rejected_quantity": float(line.rejected_quantity),
            "accepted_quantity": float(line.accepted_quantity),
            # Received less what was due on this receipt (still owed before it):
            # negative is a shortage, positive an excess.
            "short_excess_quantity": float(
                line.received_quantity - (line.remaining_quantity + line.accepted_quantity)),
            "condition": line.condition,
            "unit_price": float(line.unit_price),
            "unit_cost_base": float(line.unit_cost_base),
            "net_amount": float(line.net_amount),
            "warehouse_id": str(line.warehouse_id) if line.warehouse_id else None,
            "remarks": line.remarks,
        }
        for line in grn.lines
    ]
    return data


def _owned_grn(db: Session, grn_id: uuid.UUID) -> m.MaterialReceivingNote:
    grn = db.scalar(
        select(m.MaterialReceivingNote)
        .options(selectinload(m.MaterialReceivingNote.lines))
        .where(m.MaterialReceivingNote.id == grn_id,
               m.MaterialReceivingNote.company_id == active_company_id(db))
    )
    if grn is None:
        raise HTTPException(404, "That goods receipt does not exist.")
    return grn


@router.get("/goods-receipts")
def list_goods_receipts(
    search: str | None = None,
    status_filter: list[str] = Query(default=[], alias="status"),
    purchase_order_id: uuid.UUID | None = None,
    shipment_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    posted_only: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = "doc_date",
    direction: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.goods_receipts.view")),
):
    company_id = active_company_id(db)
    G = m.MaterialReceivingNote
    stmt = select(G).where(G.company_id == company_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            G.doc_number.ilike(like),
            G.supplier_invoice_number.ilike(like),
            G.vehicle_number.ilike(like),
            G.remarks.ilike(like),
            G.lines.any(m.MrnLine.description.ilike(like)),
        ))
    if status_filter:
        stmt = stmt.where(G.status.in_(status_filter))
    if posted_only:
        stmt = stmt.where(G.is_posted.is_(True))
    if purchase_order_id:
        stmt = stmt.where(G.purchase_order_id == purchase_order_id)
    if shipment_id:
        stmt = stmt.where(G.shipment_id == shipment_id)
    if supplier_id:
        stmt = stmt.where(G.supplier_id == supplier_id)
    if warehouse_id:
        stmt = stmt.where(G.warehouse_id == warehouse_id)
    if date_from:
        stmt = stmt.where(G.doc_date >= date_from)
    if date_to:
        stmt = stmt.where(G.doc_date <= date_to)

    total = db.scalar(stmt.with_only_columns(func.count(G.id)).order_by(None)) or 0
    column = {
        "doc_number": G.doc_number, "doc_date": G.doc_date,
        "status": G.status, "net_payable": G.net_payable,
    }.get(sort, G.doc_date)
    stmt = stmt.order_by(column.desc() if direction == "desc" else column.asc())

    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    orders = dict(db.execute(
        select(m.PurchaseOrder.id, m.PurchaseOrder.doc_number)
        .where(m.PurchaseOrder.id.in_([r.purchase_order_id for r in rows
                                       if r.purchase_order_id]))
    ).all()) if rows else {}
    return {
        "items": [_grn_summary(r, _names(db, [r.supplier_id for r in rows]),
                               _warehouses(db, [r.warehouse_id for r in rows]), orders)
                  for r in rows],
        "total": total, "page": page, "page_size": page_size,
    }


@router.get("/goods-receipts/{grn_id}")
def get_goods_receipt(
    grn_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.goods_receipts.view")),
):
    return _grn_detail(db, _owned_grn(db, grn_id))


@router.get("/receivable")
def receivable_lines(
    purchase_order_id: uuid.UUID | None = None,
    shipment_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.goods_receipts.create")),
):
    """What is still owed on an order or a shipment.

    The list a goods receipt is built from: ordered, already received, and
    what is left. Receiving against a shipment reads the shipped quantity
    instead of the ordered one, because a shipment is what is actually here.
    """
    if not purchase_order_id and not shipment_id:
        raise HTTPException(400, "Name a purchase order or a shipment to receive against.")

    if shipment_id:
        ship = _owned_shipment(db, shipment_id)
        order = db.get(m.PurchaseOrder, ship.purchase_order_id)
        posted = db.scalar(
            select(m.LandedCost).where(m.LandedCost.shipment_id == ship.id,
                                       m.LandedCost.is_posted.is_(True)))
        return {
            "source": "shipment",
            "shipment_id": str(ship.id),
            "shipment": ship.doc_number,
            "purchase_order_id": str(ship.purchase_order_id),
            "purchase_order": order.doc_number if order else None,
            "supplier_id": str(ship.supplier_id),
            "warehouse_id": str(ship.warehouse_id) if ship.warehouse_id else None,
            "currency": ship.currency,
            "exchange_rate": float(ship.exchange_rate),
            "transit_status": ship.transit_status,
            # Receiving an import without a posted costing brings the goods in
            # at the supplier price, understating stock by everything the
            # import cost. Surfaced here so the screen can say so.
            "landed_cost_id": str(posted.id) if posted else None,
            "landed_cost": posted.doc_number if posted else None,
            "landed_cost_ready": posted is not None,
            # A costing started but not yet posted: the screen names it, so the
            # next step (post it) is plain.
            "pending_costing": (lambda c: f"{c.doc_number} ({c.status})" if c else None)(
                None if posted else db.scalar(select(m.LandedCost).where(
                    m.LandedCost.shipment_id == ship.id, m.LandedCost.status != "Cancelled"))),
            "lines": [
                {
                    "shipment_line_id": str(line.id),
                    "purchase_order_line_id": (
                        str(line.purchase_order_line_id)
                        if line.purchase_order_line_id else None),
                    "item_id": str(line.item_id) if line.item_id else None,
                    "item_code": line.item_code,
                    "description": line.description,
                    "uom": line.uom,
                    "ordered_quantity": float(line.shipped_quantity),
                    "already_received": float(line.received_quantity),
                    "outstanding_quantity": float(max(
                        ZERO, line.shipped_quantity - line.received_quantity)),
                    "unit_price": float(line.unit_price),
                }
                for line in ship.lines
            ],
        }

    order = _owned_po(db, purchase_order_id)
    return {
        "source": "purchase_order",
        "purchase_order_id": str(order.id),
        "purchase_order": order.doc_number,
        "purchase_type": order.purchase_type,
        "supplier_id": str(order.supplier_id),
        "warehouse_id": str(order.warehouse_id) if order.warehouse_id else None,
        "currency": order.currency,
        "exchange_rate": float(order.exchange_rate),
        "in_house_order_id": (
            str(order.in_house_order_id) if order.in_house_order_id else None),
        "lines": [
            {
                "purchase_order_line_id": str(line.id),
                "item_id": str(line.item_id) if line.item_id else None,
                "item_code": line.item_code,
                "description": line.description,
                "uom": line.uom,
                "ordered_quantity": float(line.quantity),
                "already_received": float(line.received_quantity),
                "outstanding_quantity": float(max(
                    ZERO, line.quantity - line.received_quantity)),
                "unit_price": float(line.unit_price),
                "discount_percent": float(line.discount_percent),
                "tax_percent": float(line.tax_percent),
            }
            for line in order.lines
        ],
    }


CONDITIONS = ("Good", "Damaged", "Short", "Excess", "Under Inspection")


def _accepted(raw) -> Decimal:
    """What passed inspection on a line as entered: the accepted quantity
    when given, otherwise everything received less anything rejected."""
    if raw.accepted_quantity is not None:
        return Decimal(str(raw.accepted_quantity))
    return max(ZERO, Decimal(str(raw.received_quantity or 0)) - Decimal(str(raw.rejected_quantity or 0)))


def _bill_state(value: str | None) -> str:
    v = (value or "No").strip().title()
    return v if v in ("Yes", "No", "Hold") else "No"


def _apply_grn_lines(db: Session, grn: m.MaterialReceivingNote, raw_lines) -> None:
    # A receipt is priced on what was accepted into stock (GRN template: only
    # accepted quantities are posted), not on what was ordered or turned away.
    totals = calculate_document(
        [
            LineInput(
                quantity=_accepted(raw),
                unit_price=Decimal(str(raw.unit_price or 0)),
                discount_percent=Decimal(str(raw.discount_percent or 0)),
                tax_percent=Decimal(str(raw.tax_percent or 0)),
            )
            for raw in raw_lines
        ],
        freight_amount=ZERO,
        document_discount=ZERO,
    )

    new_lines: list[m.MrnLine] = []
    for index, (raw, computed) in enumerate(zip(raw_lines, totals.lines), start=1):
        po_line = (db.get(m.PurchaseOrderLine, _uid(raw.purchase_order_line_id))
                   if raw.purchase_order_line_id else None)
        ship_line = (db.get(m.ImportShipmentLine, _uid(raw.shipment_line_id))
                     if raw.shipment_line_id else None)

        ordered = Decimal(str(raw.ordered_quantity or 0))
        if not ordered:
            ordered = (ship_line.shipped_quantity if ship_line is not None
                       else (po_line.quantity if po_line is not None else ZERO))
        already = (ship_line.received_quantity if ship_line is not None
                   else (po_line.received_quantity if po_line is not None else ZERO))
        received = service.qty(raw.received_quantity)
        accepted = service.qty(_accepted(raw))
        if accepted > received:
            raise HTTPException(400, f"Line {index}: {accepted} accepted is more than the {received} received.")
        condition = (raw.condition or "Good").strip().title().replace("Under inspection", "Under Inspection")
        if condition not in CONDITIONS:
            raise HTTPException(400, f"Line {index}: condition must be one of {', '.join(CONDITIONS)}.")

        description = (raw.description or (po_line.description if po_line else None)
                       or (ship_line.description if ship_line else "")).strip()
        if not description:
            raise HTTPException(400, f"Line {index}: a description is required.")

        new_lines.append(m.MrnLine(
            id=_uid(raw.id) or uuid.uuid4(),
            line_number=index,
            purchase_order_line_id=po_line.id if po_line is not None else None,
            shipment_line_id=ship_line.id if ship_line is not None else None,
            item_id=(_uid(raw.item_id)
                     or (po_line.item_id if po_line else None)
                     or (ship_line.item_id if ship_line else None)),
            item_code=(raw.item_code or (po_line.item_code if po_line else None)
                       or (ship_line.item_code if ship_line else None)),
            description=description,
            uom=(raw.uom or (po_line.uom if po_line else None)
                 or (ship_line.uom if ship_line else None)),
            ordered_quantity=service.qty(ordered),
            received_quantity=received,
            remaining_quantity=max(ZERO, service.qty(ordered - already - accepted)),
            rejected_quantity=service.qty(received - accepted),
            accepted_quantity=accepted,
            condition=condition,
            unit_price=Decimal(str(raw.unit_price or 0)) or (
                po_line.unit_price if po_line is not None else
                (ship_line.unit_price if ship_line is not None else ZERO)),
            discount_percent=Decimal(str(raw.discount_percent or 0)),
            tax_percent=Decimal(str(raw.tax_percent or 0)),
            gross_amount=computed.gross_amount,
            discount_amount=computed.discount_amount,
            taxable_amount=computed.taxable_amount,
            tax_amount=computed.tax_amount,
            net_amount=computed.net_amount,
            warehouse_id=_uid(raw.warehouse_id) or grn.warehouse_id,
            remarks=raw.remarks,
        ))

    grn.lines = new_lines
    grn.excluding_tax_value = totals.excluding_tax_value
    grn.sales_tax_value = totals.sales_tax_value
    grn.gross_amount = totals.gross_amount
    grn.discount_amount = totals.discount_total
    grn.net_payable = totals.net_receivable
    grn.total_items = len(new_lines)


@router.post("/goods-receipts", status_code=http.HTTP_201_CREATED)
def create_goods_receipt(
    payload: s.GrnIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.goods_receipts.create")),
):
    """Record what arrived. Saving does not move stock — posting does."""
    company_id = active_company_id(db)
    supplier = service.require_supplier(db, company_id, payload.supplier_id)
    if not payload.lines:
        raise HTTPException(400, "A goods receipt needs at least one line.")

    order = _owned_po(db, _uid(payload.purchase_order_id)) \
        if payload.purchase_order_id else None
    ship = _owned_shipment(db, _uid(payload.shipment_id)) if payload.shipment_id else None
    if order is not None and order.status in ("Draft", "Pending Approval", "Cancelled"):
        raise HTTPException(
            400,
            f"{order.doc_number} is {order.status!r}. Goods cannot be received against "
            "an order that has not been approved.")

    fiscal_year = _fiscal_year(db, company_id)
    grn = m.MaterialReceivingNote(
        company_id=company_id,
        branch_id=_uid(payload.branch_id),
        doc_number=_number(db, company_id, "goods_receipt", fiscal_year, "GRN-"),
        doc_date=payload.doc_date,
        fiscal_year=fiscal_year,
        supplier_id=supplier.id,
        purchase_order_id=order.id if order else (
            ship.purchase_order_id if ship else None),
        shipment_id=ship.id if ship else None,
        # Carried down from the order — including when the receipt names only
        # a shipment, which is the usual way an import arrives. Without this
        # the trace back to the requirement breaks on exactly the documents
        # that have the longest chain.
        in_house_order_id=(
            order.in_house_order_id if order
            else (parent.in_house_order_id if ship and (
                parent := db.get(m.PurchaseOrder, ship.purchase_order_id)) else None)),
        landed_cost_id=_uid(payload.landed_cost_id),
        warehouse_id=service.resolve_warehouse(
            db, company_id,
            _uid(payload.warehouse_id)
            or (ship.warehouse_id if ship else None)
            or (order.warehouse_id if order else None)),
        supplier_invoice_number=payload.supplier_invoice_number,
        supplier_invoice_date=payload.supplier_invoice_date,
        vehicle_number=payload.vehicle_number,
        received_by=payload.received_by or (user.full_name or user.username),
        remarks=payload.remarks,
        delivery_note_number=payload.delivery_note_number,
        delivery_date=payload.delivery_date,
        transporter=payload.transporter,
        gd_reference=payload.gd_reference,
        inspection_notes=payload.inspection_notes,
        discrepancy_notes=payload.discrepancy_notes,
        checked_by=payload.checked_by,
        bill_to_finance=_bill_state(payload.bill_to_finance),
        status="Draft",
        currency=payload.currency or (order.currency if order else "PKR"),
        exchange_rate=payload.exchange_rate or (
            ship.exchange_rate if ship else (order.exchange_rate if order else Decimal("1"))),
        created_by=user.id,
    )
    db.add(grn)
    _apply_grn_lines(db, grn, payload.lines)
    db.flush()
    service.check_receipt(db, grn)
    db.commit()
    db.refresh(grn)
    return _grn_detail(db, grn)


@router.put("/goods-receipts/{grn_id}")
def update_goods_receipt(
    grn_id: uuid.UUID,
    payload: s.GrnIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.goods_receipts.create")),
):
    grn = _owned_grn(db, grn_id)
    if grn.is_posted:
        raise HTTPException(
            400,
            f"{grn.doc_number} is posted and its stock movements are in the ledger. "
            "Reverse it if it was wrong — a posted receipt is not edited.")

    grn.doc_date = payload.doc_date
    grn.supplier_invoice_number = payload.supplier_invoice_number
    grn.supplier_invoice_date = payload.supplier_invoice_date
    grn.vehicle_number = payload.vehicle_number
    grn.received_by = payload.received_by
    grn.remarks = payload.remarks
    grn.delivery_note_number = payload.delivery_note_number
    grn.delivery_date = payload.delivery_date
    grn.transporter = payload.transporter
    grn.gd_reference = payload.gd_reference
    grn.inspection_notes = payload.inspection_notes
    grn.discrepancy_notes = payload.discrepancy_notes
    grn.checked_by = payload.checked_by
    grn.bill_to_finance = _bill_state(payload.bill_to_finance)
    grn.landed_cost_id = _uid(payload.landed_cost_id)
    grn.warehouse_id = service.resolve_warehouse(
        db, grn.company_id, _uid(payload.warehouse_id))
    grn.updated_by = user.id
    _apply_grn_lines(db, grn, payload.lines)
    db.flush()
    service.check_receipt(db, grn)
    db.commit()
    db.refresh(grn)
    return _grn_detail(db, grn)


@router.post("/goods-receipts/{grn_id}/status")
def set_goods_receipt_status(
    grn_id: uuid.UUID,
    payload: s.StatusChangeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.goods_receipts.post")),
):
    """Post a receipt into stock, or reverse one that was wrong.

    Posting is the single point in the whole module where inventory
    increases: it writes the ledger, rolls the received quantities up to the
    shipment, the order and the requirement, and moves each of their statuses
    on. All of it in one transaction, so stock and paperwork cannot disagree.
    """
    grn = _owned_grn(db, grn_id)
    service.check_transition(service.GRN_TRANSITIONS, grn.status,
                             payload.status, "goods receipt")

    if payload.status == "Posted":
        written = service.post_receipt(db, grn, user.id)
        db.commit()
        return {"id": str(grn.id), "status": grn.status, "is_posted": True,
                "movements_written": written}

    if payload.status == "Cancelled" and grn.is_posted:
        written = service.reverse_receipt(db, grn, user.id)
        db.commit()
        return {"id": str(grn.id), "status": grn.status, "is_posted": False,
                "movements_reversed": written}

    grn.status = payload.status
    grn.updated_by = user.id
    db.commit()
    return {"id": str(grn.id), "status": grn.status, "is_posted": grn.is_posted}


# ============================================================ traceability

@router.get("/trace/{grn_id}")
def trace_receipt(
    grn_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("procurement.goods_receipts.view")),
):
    """The whole chain behind one receipt (spec sections 37, 38 and 55).

    Answers, in one call: why did we buy this, who asked for it, what did we
    order, from whom, which shipment brought it, what did it really cost,
    which warehouse took it in, and which ledger entries resulted.
    """
    from app.inventory.stock import StockLedgerEntry

    grn = _owned_grn(db, grn_id)
    order = db.get(m.PurchaseOrder, grn.purchase_order_id) if grn.purchase_order_id else None
    ship = db.get(m.ImportShipment, grn.shipment_id) if grn.shipment_id else None
    iho = db.get(m.InHouseOrder, grn.in_house_order_id) if grn.in_house_order_id else None
    voucher = db.get(m.LandedCost, grn.landed_cost_id) if grn.landed_cost_id else None
    supplier = db.get(BusinessPartner, grn.supplier_id)

    movements = db.execute(
        select(StockLedgerEntry.entry_date, StockLedgerEntry.direction,
               StockLedgerEntry.quantity, StockLedgerEntry.unit_cost,
               StockLedgerEntry.source_type, ItemLocation.location)
        .outerjoin(ItemLocation, ItemLocation.id == StockLedgerEntry.location_id)
        .where(StockLedgerEntry.source_id == grn.id)
        .order_by(StockLedgerEntry.entry_date)
    ).all()

    return {
        "requirement": {
            "id": str(iho.id), "doc_number": iho.doc_number, "doc_date": iho.doc_date,
            "source": iho.source, "requested_by": iho.requested_by,
            "purpose": iho.purpose, "status": iho.status,
        } if iho else None,
        "purchase_order": {
            "id": str(order.id), "doc_number": order.doc_number,
            "doc_date": order.doc_date, "purchase_type": order.purchase_type,
            "currency": order.currency, "exchange_rate": float(order.exchange_rate),
            "net_payable": float(order.net_payable),
            "net_payable_base": float(order.net_payable_base),
            "status": order.status,
        } if order else None,
        "supplier": {
            "id": str(supplier.id), "name": supplier.name, "code": supplier.code,
            "country": supplier.country, "is_international": supplier.is_international,
        } if supplier else None,
        "shipment": {
            "id": str(ship.id), "doc_number": ship.doc_number,
            "container_number": ship.container_number,
            "bill_of_lading_number": ship.bill_of_lading_number,
            "etd": ship.etd, "eta": ship.eta,
            "actual_arrival_date": ship.actual_arrival_date,
            "transit_status": ship.transit_status, "status": ship.status,
        } if ship else None,
        "landed_cost": {
            "id": str(voucher.id), "doc_number": voucher.doc_number,
            "status": voucher.status, "is_posted": voucher.is_posted,
            "purchase_cost_base": float(voucher.purchase_cost_base),
            "additional_cost_base": float(voucher.additional_cost_base),
            "total_landed_cost": float(voucher.total_landed_cost),
        } if voucher else None,
        "goods_receipt": _grn_detail(db, grn),
        "stock_movements": [
            {
                "entry_date": row[0], "direction": row[1],
                "quantity": float(row[2]),
                "unit_cost": float(row[3]) if row[3] is not None else None,
                "source_type": row[4], "warehouse": row[5],
            }
            for row in movements
        ],
    }
