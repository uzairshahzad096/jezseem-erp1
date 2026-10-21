"""
One download endpoint for every listing.

    GET /api/v1/exports/{dataset}?format=csv|xlsx|pdf&search=...

Rather than a download route bolted onto each module, a dataset declares its
permission, its columns and how to fetch its rows, and the same three writers
serve all of them. Adding a module later means adding one entry here.

The export is the whole filtered set, not the page on screen: someone asking
for "all product orders" wants all 1,348, not the 25 they can see.
"""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.exports import procurement_rows as pr
from app.exports.writers import FORMATS
from app.inventory import models as m
from app.inventory.router import active_company_id
from app.partners.models import BusinessPartner
from app.gatepass.models import GatePass, GatePassLine
from app.sales.models import QUOTATION, SALES_ORDER, SalesDocument, SalesDocumentLine
from app.users.models import User

router = APIRouter(prefix="/exports", tags=["exports"])

# A hard ceiling so a mistyped filter cannot try to render a PDF of the whole
# database. Well above any real listing here.
MAX_ROWS = 20_000

# Shared by the three purchase-order registers, which differ only in filter.
PURCHASE_ORDER_COLUMNS = [
    ("doc_number", "PO No"), ("doc_date", "Date"), ("purchase_type", "Type"),
    ("supplier", "Supplier"), ("supplier_country", "Supplier Country"),
    ("country_of_origin", "Country of Origin"), ("warehouse", "Warehouse"),
    ("status", "Status"), ("currency", "Currency"), ("exchange_rate", "Exchange Rate"),
    ("incoterm", "Incoterm"), ("lc_number", "LC No"),
    ("expected_delivery_date", "Expected Date"), ("priority", "Priority"),
    ("expected_arrival_date", "Expected Arrival"),
    ("item_code", "Item Code"), ("description", "Item"), ("uom", "Uom"),
    ("hs_code", "HS Code"), ("quantity", "Ordered"), ("shipped_quantity", "Shipped"),
    ("received_quantity", "Received"), ("outstanding_quantity", "Outstanding"),
    ("unit_price", "Unit Price"), ("net_amount", "Line Net"),
    ("net_payable", "PO Net"), ("net_payable_base", "PO Net (PKR)"),
]

SHIPMENT_COLUMNS = [
    ("doc_number", "Shipment No"), ("doc_date", "Date"),
    ("purchase_order", "PO No"), ("supplier", "Supplier"),
    ("status", "Status"), ("transit_status", "Where"),
    ("customs_status", "Customs"), ("container_number", "Container"),
    ("bill_of_lading_number", "BL No"), ("vessel_or_flight", "Vessel / Flight"),
    ("port_of_loading", "Loading"), ("port_of_discharge", "Discharge"),
    ("etd", "ETD"), ("eta", "ETA"), ("actual_arrival_date", "Arrived"),
    ("clearing_agent", "Clearing Agent"), ("warehouse", "Warehouse"),
    ("item_code", "Item Code"), ("description", "Item"), ("uom", "Uom"),
    ("shipped_quantity", "Shipped"), ("received_quantity", "Received"),
    ("outstanding_quantity", "Outstanding"), ("currency", "Currency"),
    ("exchange_rate", "Rate"), ("line_value", "Line Value"),
]


def _line_text(db: Session, doc_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not doc_ids:
        return {}
    rows = db.execute(
        select(SalesDocumentLine.document_id, SalesDocumentLine.description)
        .where(SalesDocumentLine.document_id.in_(doc_ids))
        .order_by(SalesDocumentLine.document_id, SalesDocumentLine.line_number)
    ).all()
    grouped: dict[uuid.UUID, list[str]] = {}
    for doc_id, description in rows:
        if description:
            grouped.setdefault(doc_id, []).append(description)
    return {doc_id: " , ".join(v) for doc_id, v in grouped.items()}


def _sales_rows(db: Session, company_id: uuid.UUID, doc_type: str, search: str | None,
                statuses: list[str]) -> list[dict]:
    stmt: Select = select(SalesDocument).where(
        SalesDocument.company_id == company_id, SalesDocument.doc_type == doc_type
    )
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            SalesDocument.doc_number.ilike(like),
            SalesDocument.remarks.ilike(like),
            SalesDocument.demand_number.ilike(like),
            SalesDocument.customer_po_number.ilike(like),
            SalesDocument.lines.any(SalesDocumentLine.description.ilike(like)),
        ))
    if statuses:
        stmt = stmt.where(SalesDocument.status.in_(statuses))

    docs = list(db.scalars(stmt.order_by(SalesDocument.doc_date.desc()).limit(MAX_ROWS)).all())
    parties = {p.id: p for p in db.scalars(
        select(BusinessPartner).where(
            BusinessPartner.id.in_([d.customer_id for d in docs])
        )).all()} if docs else {}
    source_ids = [d.source_document_id for d in docs if d.source_document_id]
    sources = dict(db.execute(
        select(SalesDocument.id, SalesDocument.doc_number)
        .where(SalesDocument.id.in_(source_ids))
    ).all()) if source_ids else {}
    details = _line_text(db, [d.id for d in docs])

    out = []
    for d in docs:
        party = parties.get(d.customer_id)
        out.append({
            "doc_number": d.doc_number,
            "doc_date": d.doc_date,
            "customer_po_number": d.customer_po_number,
            "source_doc_number": sources.get(d.source_document_id) or d.quotation_number,
            "customer_name": party.name if party else None,
            "remarks": d.remarks,
            "dc_number": d.dc_number,
            "delivery_person": d.delivery_person,
            "vehicle_number": d.vehicle_number,
            "gst": "Service" if d.is_service else "With Sale Tax" if d.with_sales_tax else "Without Sale Tax",
            "status": d.status,
            "payment_status": d.payment_status,
            "excluding_tax_value": float(d.excluding_tax_value),
            "sales_tax_value": float(d.sales_tax_value),
            "gross_amount": float(d.gross_amount),
            "discount_amount": float(d.discount_amount),
            "freight_amount": float(d.freight_amount),
            "net_receivable": float(d.net_receivable),
            "customer_stn": party.stn if party else None,
            "customer_ntn": party.ntn if party else None,
            "total_items": d.total_items,
            "detail_items": details.get(d.id),
        })
    return out


SALES_COLUMNS = [
    ("doc_number", "Sale NO."), ("doc_date", "Sale Date"),
    ("customer_po_number", "PO NO#"), ("source_doc_number", "Quotation No#"),
    ("customer_name", "Customer"), ("remarks", "Remarks"), ("dc_number", "Dc No"),
    ("delivery_person", "Delivery Person"), ("vehicle_number", "Vehicle No"),
    ("gst", "Gst or Non Gst"), ("status", "Status"), ("payment_status", "Payment Status"),
    ("excluding_tax_value", "Excluding Stax Value"), ("sales_tax_value", "Sale Tax Value"),
    ("gross_amount", "Gross Amount"), ("discount_amount", "Discount"),
    ("freight_amount", "Freight"), ("net_receivable", "Net Receivable"),
    ("customer_stn", "GST #"), ("customer_ntn", "NTN #"),
    ("total_items", "Total Items"), ("detail_items", "Detail Items"),
]

QUOTATION_COLUMNS = [
    ("doc_number", "Quotation No."), ("doc_date", "Quotation Date"),
    ("customer_name", "Customer"), ("customer_po_number", "PO NO#"),
    ("status", "Status"), ("remarks", "Remarks"),
    ("gst", "Gst or Non Gst"),
    ("excluding_tax_value", "Excluding Stax Value"), ("sales_tax_value", "Sale Tax Value"),
    ("gross_amount", "Gross Amount"), ("discount_amount", "Discount"),
    ("freight_amount", "Freight"), ("net_receivable", "Net Receivable"),
    ("customer_stn", "GST #"), ("customer_ntn", "NTN #"),
    ("total_items", "Total Items"), ("detail_items", "Detail Items"),
]


def _items_rows(db: Session, company_id: uuid.UUID, search: str | None,
                statuses: list[str]) -> list[dict]:
    stmt = select(m.InventoryItem).where(m.InventoryItem.company_id == company_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            m.InventoryItem.description.ilike(like), m.InventoryItem.item_code.ilike(like),
            m.InventoryItem.sku.ilike(like), m.InventoryItem.barcode.ilike(like),
        ))
    if statuses:
        stmt = stmt.where(m.InventoryItem.item_status.in_(statuses))
    rows = list(db.scalars(stmt.order_by(m.InventoryItem.item_code).limit(MAX_ROWS)).all())

    mp = dict(db.execute(select(m.MainProduct.id, m.MainProduct.description)).all())
    sc = dict(db.execute(select(m.InventorySubCategory.id, m.InventorySubCategory.description)).all())
    sd = dict(db.execute(select(
        m.InventorySubDetailCategory.id, m.InventorySubDetailCategory.description)).all())
    rk = dict(db.execute(select(m.ItemRack.id, m.ItemRack.rack_name)).all())

    return [{
        "item_code": r.item_code, "description": r.description, "sku": r.sku,
        "barcode": r.barcode, "uom": r.uom,
        "main_product": mp.get(r.main_product_id), "sub_category": sc.get(r.sub_category_id),
        "sub_detail_category": sd.get(r.sub_detail_category_id), "rack": rk.get(r.rack_id),
        "item_status": r.item_status,
        "opening_stock": float(r.opening_stock) if r.opening_stock is not None else 0,
        "price": float(r.price) if r.price is not None else None,
        "currency": r.currency,
    } for r in rows]


def _partner_rows(db: Session, company_id: uuid.UUID, search: str | None,
                  statuses: list[str]) -> list[dict]:
    stmt = select(BusinessPartner).where(
        BusinessPartner.company_id == company_id, BusinessPartner.is_customer.is_(True))
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(BusinessPartner.name.ilike(like), BusinessPartner.code.ilike(like)))
    rows = list(db.scalars(stmt.order_by(BusinessPartner.name).limit(MAX_ROWS)).all())
    return [{
        "code": r.code, "name": r.name, "address": r.address, "city": r.city,
        "ntn": r.ntn, "stn": r.stn, "phone": r.phone, "cell": r.cell, "email": r.email,
        "is_active": r.is_active,
    } for r in rows]


def _simple_rows(model, columns):
    def fetch(db: Session, company_id: uuid.UUID, search: str | None, statuses: list[str]):
        stmt = select(model).where(model.company_id == company_id)
        rows = list(db.scalars(stmt.limit(MAX_ROWS)).all())
        return [{key: getattr(r, key, None) for key, _ in columns} for r in rows]
    return fetch


RACK_COLUMNS = [("rack_name", "Rack Name"), ("is_active", "Active")]
LOCATION_COLUMNS = [("location", "Location"), ("is_active", "Active")]
MAIN_PRODUCT_COLUMNS = [("description", "Main Product"), ("remarks", "Remarks"),
                        ("is_active", "Active")]
SUB_CATEGORY_COLUMNS = [("sub_code", "Sub Code"), ("description", "Sub Category"),
                        ("remarks", "Remarks"), ("is_active", "Active")]
SUB_DETAIL_COLUMNS = [("description", "Sub Detail Category"), ("remarks", "Remarks"),
                      ("is_active", "Active")]

def _stock_rows(db: Session, company_id: uuid.UUID, search: str | None,
                statuses: list[str], extra: dict | None = None) -> list[dict]:
    """The Product Stock report with its movement analysis, from the same
    function the screen uses, so the file always agrees with it. Uses the
    default settings (financial year to date, 3+ orders, restock at 40% of stock added);
    the screen's Analysis workbook download follows whatever is set there."""
    from app.reports.router import stock_analysis

    extra = extra or {}
    _cfg, rows, _totals = stock_analysis(db, company_id, search=search, location_id=extra.get("location_id"))
    if statuses:
        rows = [r for r in rows if r["item_status"] in statuses]
    rows.sort(key=lambda r: r["item_code"])
    return [dict(r, restock="Yes" if r["restock"] else "") for r in rows[:MAX_ROWS]]


def _product_sales_rows(db: Session, company_id: uuid.UUID, search: str | None,
                        statuses: list[str], extra: dict | None = None) -> list[dict]:
    """The Product Sales report: one row per sold line.

    Honours the report screen's own filters — customer and date range — so the
    downloaded file covers the same rows the user is looking at.
    """
    extra = extra or {}
    stmt = (
        select(SalesDocument, SalesDocumentLine)
        .join(SalesDocumentLine, SalesDocumentLine.document_id == SalesDocument.id)
        .where(SalesDocument.company_id == company_id,
               SalesDocument.doc_type == SALES_ORDER)
    )
    if extra.get("customer_id"):
        stmt = stmt.where(SalesDocument.customer_id == extra["customer_id"])
    if extra.get("date_from"):
        stmt = stmt.where(SalesDocument.doc_date >= extra["date_from"])
    if extra.get("date_to"):
        stmt = stmt.where(SalesDocument.doc_date <= extra["date_to"])
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            SalesDocument.doc_number.ilike(like), SalesDocumentLine.description.ilike(like)))
    if statuses:
        stmt = stmt.where(SalesDocument.status.in_(statuses))

    rows = db.execute(
        stmt.order_by(SalesDocument.doc_date.desc(), SalesDocument.doc_number.desc(),
                      SalesDocumentLine.line_number.asc()).limit(MAX_ROWS)
    ).all()
    parties = {r[0]: r for r in db.execute(
        select(BusinessPartner.id, BusinessPartner.name, BusinessPartner.ntn)).all()}

    return [{
        "doc_number": d.doc_number, "doc_date": d.doc_date,
        "customer": (parties.get(d.customer_id) or (None, None, None))[1],
        "customer_ntn": (parties.get(d.customer_id) or (None, None, None))[2],
        "item_code": l.item_code, "description": l.description, "uom": l.uom,
        "quantity": float(l.quantity), "unit_price": float(l.unit_price),
        "gross_amount": float(l.gross_amount), "discount_amount": float(l.discount_amount),
        "taxable_amount": float(l.taxable_amount),
        "tax_amount": float(l.tax_amount), "net_amount": float(l.net_amount),
        "status": d.status,
    } for d, l in rows]


def _gate_pass_rows(pass_type: str):
    def fetch(db: Session, company_id: uuid.UUID, search: str | None,
              statuses: list[str], extra: dict | None = None) -> list[dict]:
        stmt = select(GatePass).where(
            GatePass.company_id == company_id,
            func.lower(GatePass.pass_type) == pass_type)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(
                GatePass.doc_number.ilike(like), GatePass.remarks.ilike(like),
                GatePass.vehicle_number.ilike(like),
                GatePass.lines.any(GatePassLine.description.ilike(like))))
        if statuses:
            stmt = stmt.where(GatePass.status.in_(statuses))

        rows = list(db.scalars(
            stmt.order_by(GatePass.doc_date.desc()).limit(MAX_ROWS)).all())
        parties = {p.id: p for p in db.scalars(
            select(BusinessPartner).where(
                BusinessPartner.id.in_([r.party_id for r in rows if r.party_id])
            )).all()} if rows else {}

        texts: dict = {}
        if rows:
            for pid, desc in db.execute(
                select(GatePassLine.gate_pass_id, GatePassLine.description)
                .where(GatePassLine.gate_pass_id.in_([r.id for r in rows]))
                .order_by(GatePassLine.gate_pass_id, GatePassLine.line_number)
            ).all():
                if desc:
                    texts.setdefault(pid, []).append(desc)

        reference_ids = [r.reference_gate_pass_id for r in rows if r.reference_gate_pass_id]
        references = dict(db.execute(
            select(GatePass.id, GatePass.doc_number).where(GatePass.id.in_(reference_ids))
        ).all()) if reference_ids else {}

        out = []
        for r in rows:
            party = parties.get(r.party_id)
            out.append({
                "doc_number": r.doc_number, "doc_date": r.doc_date,
                "party_name": party.name if party else r.issue_to,
                "vehicle_number": r.vehicle_number, "driver": r.driver,
                "issue_type": r.issue_type, "status": r.status,
                "location": r.location, "dc_number": r.dc_number,
                "challan_number": r.challan_number,
                "container_number": r.container_number,
                "po_number": r.po_number, "reference_number": r.reference_number,
                "reference_gate_pass": references.get(r.reference_gate_pass_id),
                "ntn": r.ntn or (party.ntn if party else None),
                "gst_number": r.gst_number or (party.stn if party else None),
                "currency": r.currency,
                "excluding_tax_value": float(r.excluding_tax_value),
                "sales_tax_value": float(r.sales_tax_value),
                "gross_amount": float(r.gross_amount),
                "discount_amount": float(r.discount_amount),
                "freight_amount": float(r.freight_amount),
                "total_amount": float(r.total_amount),
                "payment_status": r.payment_status,
                "payment_reference": r.payment_reference,
                "total_items": r.total_items,
                "item_description": " , ".join(texts.get(r.id, [])) or None,
                "remarks": r.remarks, "is_approved": r.is_approved,
            })
        return out
    return fetch


# The OGP/IGP column mapping, in its order. The inward sheet adds the outward
# pass it settles.
GATE_PASS_COLUMNS = [
    ("doc_number", "GP No"), ("doc_date", "Date"), ("party_name", "Party"),
    ("vehicle_number", "Vehicle No"), ("driver", "Driver"), ("issue_type", "Type"),
    ("remarks", "Remarks"), ("status", "Status"), ("location", "Location"),
    ("dc_number", "DC No"), ("challan_number", "Challan No"),
    ("ntn", "NTN"), ("gst_number", "GST No"), ("container_number", "Container No"),
    ("total_items", "Total Items"), ("item_description", "Total Items Desc"),
    ("currency", "Currency"), ("excluding_tax_value", "Excluding Tax Value"),
    ("sales_tax_value", "Sale Tax Value"), ("gross_amount", "Gross Amount"),
    ("discount_amount", "Discount"), ("freight_amount", "Freight"),
    ("total_amount", "Net Receivable"), ("payment_status", "Payment Status"),
    ("payment_reference", "Payment Reference"), ("po_number", "PO No"),
    ("reference_number", "Reference No"), ("is_approved", "Is Approved"),
]

INWARD_COLUMNS = (
    GATE_PASS_COLUMNS[:3]
    + [("reference_gate_pass", "OGP No")]
    + GATE_PASS_COLUMNS[3:]
)


DATASETS: dict[str, dict] = {
    "sales-orders": {
        "title": "Product Sale Orders", "permission": "sales.orders.export",
        "columns": SALES_COLUMNS,
        "rows": lambda db, cid, s, st: _sales_rows(db, cid, SALES_ORDER, s, st),
    },
    "quotations": {
        "title": "Product Quotations", "permission": "sales.quotations.export",
        "columns": QUOTATION_COLUMNS,
        "rows": lambda db, cid, s, st: _sales_rows(db, cid, QUOTATION, s, st),
    },
    "items": {
        "title": "Product Details", "permission": "inventory.items.export",
        "columns": [
            ("item_code", "Item Code"), ("description", "Description"), ("sku", "SKU"),
            ("barcode", "Barcode"), ("uom", "UOM"), ("main_product", "Main Category"),
            ("sub_category", "Sub Category"), ("sub_detail_category", "Sub Dtl Category"),
            ("rack", "Rack"), ("item_status", "Status"), ("opening_stock", "Stock"),
            ("price", "Price"), ("currency", "Currency"),
        ],
        "rows": _items_rows,
    },
    "customers": {
        "title": "Customers", "permission": "partners.customers.export",
        "columns": [
            ("code", "Code"), ("name", "Name"), ("address", "Address"), ("city", "City"),
            ("ntn", "NTN #"), ("stn", "STN #"), ("phone", "Phone"), ("cell", "Cell"),
            ("email", "Email"), ("is_active", "Active"),
        ],
        "rows": _partner_rows,
    },
    "product-stock": {
        "title": "Product Stock Report", "permission": "inventory.reports.export",
        "columns": [
            ("item_code", "Item Code"), ("description", "Description"),
            ("main_product", "Category"), ("sub_category", "Sub Category"),
            ("uom", "UOM"), ("location", "Location"),
            ("assigned_location", "Assigned Location"),
            ("added_level", "Stock Added"), ("quantity", "Quantity"), ("remaining_pct", "% Left"),
            ("movement_label", "Movement"),
            ("orders_in_period", "Orders (FY)"), ("qty_sold_in_period", "Qty Sold (FY)"),
            ("last_sold", "Last Sold"), ("days_since_sale", "Days Since Sale"),
            ("restock", "Restock"), ("restock_priority", "Priority"), ("restock_reason", "Why"),
            ("suggested_restock_qty", "Suggested Order Qty"),
            ("min_level", "Min Level"), ("re_order_qty", "Re-order"), ("item_status", "Status"),
        ],
        "rows": _stock_rows,
    },
    "product-sales": {
        "title": "Product Sales Report", "permission": "inventory.reports.export",
        # Named as the report prints them, and in its order, so the file and
        # the screen can be read side by side.
        "columns": [
            ("doc_number", "Doc Id"), ("doc_date", "Doc Date"),
            ("description", "Item Name"), ("quantity", "Sale Quantity"),
            ("taxable_amount", "Excluding Tax Amount"),
            ("tax_amount", "Sales Tax Amount"), ("net_amount", "Net Amount"),
            ("customer", "Customer"), ("customer_ntn", "Ntn"),
            ("item_code", "Item Code"), ("uom", "UOM"),
            ("unit_price", "Unit Price"), ("gross_amount", "Gross"),
            ("discount_amount", "Discount"), ("status", "Status"),
        ],
        "rows": _product_sales_rows,
    },
    # ---- procurement (spec section 45)
    "in-house-orders": {
        "title": "In-House Order Register", "permission": "procurement.in_house_orders.export",
        "columns": [
            ("doc_number", "IHO No"), ("doc_date", "Date"), ("warehouse", "Warehouse"),
            ("department", "Department"), ("requested_by", "Requested By"),
            ("priority", "Priority"), ("source", "Source"), ("status", "Status"),
            ("required_date", "Required"), ("item_code", "Item Code"),
            ("description", "Item"), ("uom", "Uom"),
            ("available_stock", "Available"), ("requested_quantity", "Requested"),
            ("approved_quantity", "Approved"), ("ordered_quantity", "Ordered"),
            ("received_quantity", "Received"), ("outstanding_quantity", "Outstanding"),
            ("fulfilment_source", "Fulfilment"), ("purpose", "Purpose"),
        ],
        "rows": pr.in_house_order_rows,
    },
    "purchase-orders": {
        "title": "Purchase Order Register", "permission": "procurement.purchase_orders.export",
        "columns": PURCHASE_ORDER_COLUMNS, "rows": pr.purchase_order_rows(),
    },
    "local-purchase-orders": {
        "title": "Local Purchase Orders", "permission": "procurement.purchase_orders.export",
        "columns": PURCHASE_ORDER_COLUMNS, "rows": pr.purchase_order_rows("Local"),
    },
    "import-purchase-orders": {
        "title": "Import Purchase Orders", "permission": "procurement.purchase_orders.export",
        "columns": PURCHASE_ORDER_COLUMNS, "rows": pr.purchase_order_rows("Import"),
    },
    "import-shipments": {
        "title": "Import Shipment Register", "permission": "procurement.shipments.export",
        "columns": SHIPMENT_COLUMNS, "rows": pr.shipment_rows(),
    },
    "goods-in-transit": {
        "title": "Goods in Transit", "permission": "procurement.shipments.export",
        "columns": SHIPMENT_COLUMNS, "rows": pr.shipment_rows(in_transit_only=True),
    },
    "goods-receipts": {
        "title": "Goods Receipt Register", "permission": "procurement.goods_receipts.export",
        "columns": [
            ("doc_number", "GRN No"), ("doc_date", "Date"), ("supplier", "Supplier"),
            ("purchase_order", "PO No"), ("warehouse", "Warehouse"),
            ("status", "Status"), ("is_posted", "Posted"),
            ("supplier_invoice_number", "Supplier Invoice"),
            ("supplier_invoice_date", "Invoice Date"), ("vehicle_number", "Vehicle"),
            ("received_by", "Received By"), ("item_code", "Item Code"),
            ("description", "Item"), ("uom", "Uom"),
            ("ordered_quantity", "Ordered"), ("received_quantity", "Received"),
            ("remaining_quantity", "Remaining"), ("rejected_quantity", "Rejected"),
            ("unit_price", "Unit Price"), ("unit_cost_base", "Unit Cost"),
            ("net_amount", "Net Amount"),
        ],
        "rows": pr.goods_receipt_rows,
    },
    "import-landed-costing": {
        "title": "Import Landed Costing", "permission": "procurement.landed_costs.export",
        "columns": [
            ("po_number", "PO No."), ("shipment_number", "Shipment No."),
            ("landed_cost_number", "Landed Cost No."), ("doc_date", "Date"),
            ("supplier", "Supplier"), ("country", "Country"),
            ("invoice_number", "Invoice No."), ("currency", "Currency"),
            ("exchange_rate", "Exchange Rate"), ("item_code", "Item Code"),
            ("item", "Item"), ("hs_code", "HS Code"), ("uom", "Uom"),
            ("quantity", "Quantity"), ("purchase_cost", "Purchase Cost"),
            ("freight", "Freight"), ("insurance", "Insurance"),
            ("customs", "Customs"), ("taxes", "Taxes"), ("clearing", "Clearing"),
            ("port", "Port"), ("bank", "Bank"), ("other", "Other"),
            ("additional_cost", "Additional Cost"),
            ("total_landed_cost", "Total Landed Cost"),
            ("unit_landed_cost", "Unit Landed Cost"),
            ("additional_cost_percent", "Import Cost %"),
        ],
        "rows": pr.landed_costing_rows,
    },
    "outward-gate-passes": {
        "title": "Outward Gate Passes", "permission": "inventory.gate_passes.export",
        "columns": GATE_PASS_COLUMNS, "rows": _gate_pass_rows("outward"),
    },
    "inward-gate-passes": {
        "title": "Inward Gate Passes", "permission": "inventory.gate_passes.export",
        "columns": INWARD_COLUMNS, "rows": _gate_pass_rows("inward"),
    },
    "racks": {
        "title": "Item Racks", "permission": "inventory.racks.export",
        "columns": RACK_COLUMNS, "rows": _simple_rows(m.ItemRack, RACK_COLUMNS),
    },
    "locations": {
        "title": "Item Locations", "permission": "inventory.locations.export",
        "columns": LOCATION_COLUMNS, "rows": _simple_rows(m.ItemLocation, LOCATION_COLUMNS),
    },
    "main-products": {
        "title": "Main Products", "permission": "inventory.main_products.export",
        "columns": MAIN_PRODUCT_COLUMNS,
        "rows": _simple_rows(m.MainProduct, MAIN_PRODUCT_COLUMNS),
    },
    "sub-categories": {
        "title": "Inventory Sub Categories", "permission": "inventory.sub_categories.export",
        "columns": SUB_CATEGORY_COLUMNS,
        "rows": _simple_rows(m.InventorySubCategory, SUB_CATEGORY_COLUMNS),
    },
    "sub-detail-categories": {
        "title": "Inventory Sub Detail Categories",
        "permission": "inventory.sub_detail_categories.export",
        "columns": SUB_DETAIL_COLUMNS,
        "rows": _simple_rows(m.InventorySubDetailCategory, SUB_DETAIL_COLUMNS),
    },
}


@router.get("/datasets")
def list_datasets():
    """What can be exported, for the UI to offer."""
    return {
        "datasets": [
            {"name": name, "title": spec["title"],
             "columns": [{"key": k, "label": l} for k, l in spec["columns"]]}
            for name, spec in DATASETS.items()
        ],
        "formats": list(FORMATS),
    }


@router.get("/{dataset}")
def export_dataset(
    dataset: str,
    request_format: str = Query("csv", alias="format", pattern="^(csv|xlsx|pdf)$"),
    search: str | None = None,
    status_filter: list[str] = Query(default=[], alias="status"),
    customer_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("dashboard.module.view")),
):
    spec = DATASETS.get(dataset)
    if spec is None:
        raise HTTPException(404, f"Nothing called '{dataset}' can be exported.")

    # The blanket dependency above only proves the caller is signed in; the
    # dataset's own permission is what actually decides.
    require_permission(spec["permission"])(user=user)

    company_id = active_company_id(db)
    extra = {"customer_id": customer_id, "date_from": date_from,
             "date_to": date_to, "location_id": location_id}
    # Only the datasets that understand the extra filters accept them, so a
    # simple listing keeps its two-argument signature.
    try:
        rows = spec["rows"](db, company_id, search, status_filter, extra)
    except TypeError:
        rows = spec["rows"](db, company_id, search, status_filter)

    media_type, extension, writer = FORMATS[request_format]
    columns = spec["columns"]
    payload = (
        writer(columns, rows) if request_format == "csv"
        else writer(columns, rows, spec["title"])
    )

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    filename = f"{dataset}-{stamp}.{extension}"
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
