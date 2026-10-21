"""
Document printing endpoints.

Every print icon in the listings maps to a doc_kind here. The renderer reads
persisted columns only, so a PDF can never disagree with the record.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import require_permission
from app.common.references import printed_reference
from app.core.database import get_db
from app.documents.gatepass_pdf import render_gate_pass
from app.documents.pdf import DOCUMENT_PROFILES, render_document
from app.gatepass.models import GatePass
from app.partners.models import BusinessPartner
from app.sales.models import QUOTATION, SALES_ORDER, SalesDocument
from app.users.models import User

router = APIRouter(prefix="/documents", tags=["documents"])

# Which document kinds each record type may be printed as. Matches the print
# icons described in the requirements: quotations get service invoice /
# quotation / proforma; sales orders add the tax invoice and delivery note.
ALLOWED_FOR_QUOTATION = {"service_invoice", "quotation", "proforma_invoice"}
ALLOWED_FOR_SALES_ORDER = {
    "sales_tax_invoice", "sales_invoice", "delivery_note",
    "proforma_invoice", "service_invoice",
}
# Finance Phase 2 documents. A draft prints only as a proforma, so nothing
# that has not been posted can go out looking like a tax invoice.
ALLOWED_FOR_TYPE = {
    "sales_invoice": {"sales_tax_invoice", "sales_invoice", "service_invoice", "delivery_note", "proforma_invoice"},
    "credit_note": {"credit_note"},
    "debit_note": {"debit_note"},
}


@router.get("/sales/{doc_id}/{doc_kind}.pdf")
def print_sales_document(
    doc_id: uuid.UUID,
    doc_kind: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("sales.documents.print")),
):
    if doc_kind not in DOCUMENT_PROFILES:
        raise HTTPException(404, f"Unknown document type '{doc_kind}'.")

    doc = db.scalar(
        select(SalesDocument)
        .options(selectinload(SalesDocument.lines))
        .where(SalesDocument.id == doc_id)
    )
    if doc is None:
        raise HTTPException(404, "Document not found.")

    allowed = (ALLOWED_FOR_TYPE.get(doc.doc_type)
               or (ALLOWED_FOR_QUOTATION if doc.doc_type == QUOTATION else ALLOWED_FOR_SALES_ORDER))
    if doc.doc_type in ALLOWED_FOR_TYPE and doc.status in ("DRAFT", "CANCELLED") and doc_kind != "proforma_invoice":
        raise HTTPException(400, f"This document is {doc.status.lower()}; post it before printing "
                                 f"(a draft invoice can be printed as a proforma).")
    if doc_kind not in allowed:
        raise HTTPException(
            400,
            f"A {doc.doc_type.replace('_', ' ')} cannot be printed as a "
            f"{doc_kind.replace('_', ' ')}.",
        )

    # A sales tax invoice only makes sense when the order carries sales tax;
    # the yellow (sales invoice) icon covers the other case.
    if doc_kind == "sales_tax_invoice" and not doc.with_sales_tax:
        raise HTTPException(
            400, "This sales order is marked 'Without Sale Tax'. Print a Sales Invoice instead.")

    customer = db.get(BusinessPartner, doc.customer_id)

    pdf_bytes = render_document(
        doc_kind=doc_kind,
        header={
            # Without sales tax there is nothing that makes it a "sales tax"
            # document, so the sales invoice is headed plain INVOICE and its
            # Sale column shows a bare "@".
            "title": "INVOICE" if doc_kind == "sales_invoice" and not doc.with_sales_tax else None,
            "without_sales_tax": not doc.with_sales_tax,
            # Printed the way the old ERP prints it: 1538 of 2026 → 20261538.
            "doc_number": printed_reference(doc.doc_number, doc.doc_date),
            "doc_date": doc.doc_date.strftime("%B %d, %Y"),
            "demand_number": doc.demand_number,
            # A quotation is referred to by the customer's demand; everything after it by their PO.
            "reference_is_po": doc.doc_type != QUOTATION,
            # The delivery note prints these instead of the payment wording.
            "customer_po_number": doc.customer_po_number,
            "delivery_person": doc.delivery_person,
            "payment_terms": doc.payment_terms,
            "remarks": doc.remarks,
            "currency": doc.currency,
        },
        customer={
            "name": customer.name if customer else "",
            "address": customer.address if customer else None,
            # Landline if the ledger has one, mobile otherwise — most of these
            # accounts carry only a cell number.
            "phone": (customer.phone or customer.cell) if customer else None,
            "ntn": customer.ntn if customer else None,
            "stn": customer.stn if customer else None,
        },
        lines=[
            {
                "description": line.description,
                "item_code": line.item_code,
                "uom": line.uom,
                "quantity": line.quantity,
                "delivered_quantity": line.delivered_quantity,
                "unit_price": line.unit_price,
                "tax_percent": line.tax_percent,
                "taxable_amount": line.taxable_amount,
                "tax_amount": line.tax_amount,
                "net_amount": line.net_amount,
            }
            for line in doc.lines
        ],
        totals={
            "excluding_tax_value": doc.excluding_tax_value,
            "sales_tax_value": doc.sales_tax_value,
            "gross_amount": doc.gross_amount,
            "discount_amount": doc.discount_amount,
            "freight_amount": doc.freight_amount,
            "net_total": doc.net_receivable,
        },
    )

    filename = f"{doc_kind}-{printed_reference(doc.doc_number, doc.doc_date)}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/gate-passes/{pass_id}.pdf")
def print_gate_pass(
    pass_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.gate_passes.print")),
):
    """The note that travels with the goods, in the format used at the gate."""
    gp = db.scalar(
        select(GatePass)
        .options(selectinload(GatePass.lines))
        .where(GatePass.id == pass_id)
    )
    if gp is None:
        raise HTTPException(404, "Gate pass not found.")

    party = db.get(BusinessPartner, gp.party_id) if gp.party_id else None

    pdf_bytes = render_gate_pass(
        pass_type=gp.pass_type,
        header={
            "doc_number": printed_reference(gp.doc_number, gp.doc_date),
            # The reference prints the short numeric form (4/14/2026). Built
            # by hand rather than with %-m, which is not portable to Windows.
            "doc_date": f"{gp.doc_date.month}/{gp.doc_date.day}/{gp.doc_date.year}",
            "vehicle_number": gp.vehicle_number,
            "driver": gp.driver,
            "issue_type": gp.issue_type,
            "status": gp.status,
            "remarks": gp.remarks,
            "location": gp.location,
        },
        party={
            "name": party.name if party else (gp.issue_to or ""),
            "address": party.address if party else None,
        },
        lines=[
            {"description": line.description, "uom": line.uom, "quantity": line.quantity}
            for line in gp.lines
        ],
    )

    filename = f"{gp.pass_type}-gate-pass-{printed_reference(gp.doc_number, gp.doc_date)}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


def _supplier(db: Session, partner_id) -> dict:
    p = db.get(BusinessPartner, partner_id) if partner_id else None
    return {"name": p.name if p else "", "address": p.address if p else None,
            "ntn": p.ntn if p else None, "stn": p.stn if p else None}


def _pdf(content: bytes, name: str) -> Response:
    return Response(content=content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


@router.get("/purchase-orders/{order_id}.pdf")
def print_purchase_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.purchase_orders.view")),
):
    """The purchase order as sent to the supplier, with every import detail on an import order."""
    from app.documents.purchase_order_pdf import render_purchase_order
    from app.inventory.models import ItemLocation
    from app.procurement.models import PurchaseOrder
    o = db.scalar(select(PurchaseOrder).options(selectinload(PurchaseOrder.lines)).where(PurchaseOrder.id == order_id))
    if o is None:
        raise HTTPException(404, "Purchase order not found.")
    day = lambda d: d.strftime("%d-%b-%Y") if d else None   # noqa: E731
    who = lambda uid: (lambda u: (u.full_name or u.username) if u else None)(db.get(User, uid) if uid else None)  # noqa: E731
    p = db.get(BusinessPartner, o.supplier_id)
    warehouse = db.get(ItemLocation, o.warehouse_id) if o.warehouse_id else None
    expected = o.expected_arrival_date if o.purchase_type == "Import" else o.expected_delivery_date
    pdf = render_purchase_order({
        "doc_number": o.doc_number, "doc_date": day(o.doc_date), "purchase_type": o.purchase_type,
        "priority": o.priority, "status": o.status, "currency": o.currency, "exchange_rate": o.exchange_rate,
        "purchaser": o.purchaser, "warehouse": warehouse.location if warehouse else None, "remarks": o.remarks,
        "supplier": {"name": p.name if p else "", "address": p.address if p else None,
                     "country": (p.country if p else None) or o.supplier_country,
                     "ntn": p.ntn if p else None, "phone": (p.phone or p.cell) if p else None,
                     "email": p.email if p else None},
        "details": [
            ("Expected Date", day(expected)), ("Payment Terms", o.payment_terms),
            ("Delivery Terms", o.delivery_terms), ("Shipping Terms", o.shipping_terms),
            ("Credit Days", str(o.credit_days) if o.credit_days is not None else None),
            ("Supplier Quotation", " · ".join(x for x in (o.supplier_quotation_number, day(o.supplier_quotation_date)) if x)),
            ("Indent No.", o.indent_number), ("Currency", o.currency),
            ("Buyer", o.purchaser), ("Buyer Email", o.purchaser_email), ("Contact No.", o.contact_number),
            ("PO Expiry", day(o.expiry_date)),
        ],
        "import_details": [
            ("Supplier Country", o.supplier_country), ("Country of Origin", o.country_of_origin),
            ("Incoterm", o.incoterm), ("Shipping Mode", o.shipping_mode),
            ("Port of Loading", o.port_of_loading), ("Port of Discharge", o.port_of_discharge),
            ("Expected Shipment", day(o.expected_shipment_date)), ("Expected Arrival", day(o.expected_arrival_date)),
            ("Commercial Invoice No.", o.commercial_invoice_number), ("Commercial Invoice Date", day(o.commercial_invoice_date)),
            ("Packing List No.", o.packing_list_number), ("Bill of Lading No.", o.bill_of_lading_number),
            ("Airway Bill No.", o.airway_bill_number), ("Container No.", o.container_number),
            ("LC No.", o.lc_number), ("LC Date", day(o.lc_date)),
            ("Bank", o.bank_name), ("Freight Forwarder", o.freight_forwarder),
            ("Clearing Agent", o.clearing_agent), ("Insurance Provider", o.insurance_provider),
            ("Customs / GD Reference", o.customs_reference), ("Import Reference", o.import_reference),
            ("Exchange Rate", f"1 {o.currency} = {o.exchange_rate:,.4f} PKR"),
            ("Exchange Rate Date", day(o.exchange_rate_date)),
        ],
        "totals": {"excluding_tax_value": o.excluding_tax_value, "sales_tax_value": o.sales_tax_value,
                   "gross_amount": o.gross_amount, "freight_amount": o.freight_amount,
                   "discount_amount": o.discount_amount, "net_payable": o.net_payable,
                   "net_payable_base": o.net_payable_base},
        "prepared_by": who(o.created_by), "approved_by": who(o.approved_by),
    }, [{"item_code": l.item_code, "description": l.description, "hs_code": l.hs_code, "uom": l.uom,
         "quantity": l.quantity, "free_quantity": l.free_quantity, "unit_price": l.unit_price,
         "discount_percent": l.discount_percent, "tax_percent": l.tax_percent, "net_amount": l.net_amount}
        for l in o.lines])
    return _pdf(pdf, f"purchase-order-{o.doc_number}")

@router.get("/goods-receipts/{receipt_id}.pdf")
def print_goods_receipt(
    receipt_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement.goods_receipts.view")),
):
    """The goods receipt note, on the company's GRN template."""
    from app.documents.grn_pdf import render_grn
    from app.inventory.models import ItemLocation
    from app.procurement.models import ImportShipment, MaterialReceivingNote, MrnLine, PurchaseOrder
    grn = db.get(MaterialReceivingNote, receipt_id)
    if grn is None:
        raise HTTPException(404, "Goods receipt not found.")
    lines = db.scalars(select(MrnLine).where(MrnLine.mrn_id == grn.id).order_by(MrnLine.line_number)).all()
    order = db.get(PurchaseOrder, grn.purchase_order_id) if grn.purchase_order_id else None
    ship = db.get(ImportShipment, grn.shipment_id) if grn.shipment_id else None
    supplier = db.get(BusinessPartner, grn.supplier_id)
    warehouse = db.get(ItemLocation, grn.warehouse_id) if grn.warehouse_id else None
    who = lambda uid: (lambda u: (u.full_name or u.username) if u else None)(db.get(User, uid) if uid else None)  # noqa: E731
    day = lambda d: d.strftime("%d-%b-%Y") if d else None   # noqa: E731
    pdf = render_grn({
        "doc_number": grn.doc_number, "doc_date": day(grn.doc_date),
        "supplier": supplier.name if supplier else "",
        "supplier_invoice": " · ".join(x for x in (grn.supplier_invoice_number, day(grn.supplier_invoice_date)) if x),
        "purchase_order": order.doc_number if order else None, "po_date": day(order.doc_date) if order else None,
        "delivery_note": grn.delivery_note_number, "delivery_date": day(grn.delivery_date),
        "received_at": warehouse.location if warehouse else "Main Office / Warehouse",
        "received_by": grn.received_by,
        "vehicle": " / ".join(x for x in (grn.vehicle_number, grn.transporter) if x),
        "gd_reference": grn.gd_reference or (ship.customs_reference if ship else None),
        "inspection_notes": grn.inspection_notes, "discrepancy_notes": grn.discrepancy_notes,
        "stock_entry": (f"{grn.doc_number} — accepted quantities posted to stock on {day(grn.posted_at)}"
                        if grn.is_posted else "Not yet posted to stock"),
        "bill_to_finance": grn.bill_to_finance,
        "prepared_by": who(grn.created_by), "checked_by": grn.checked_by,
        "approved_by": who(grn.posted_by) if grn.is_posted else None,
    }, [{"item_code": l.item_code, "description": l.description, "uom": l.uom,
         "ordered_quantity": l.ordered_quantity, "received_quantity": l.received_quantity,
         "accepted_quantity": l.accepted_quantity, "due_quantity": l.remaining_quantity + l.accepted_quantity,
         "condition": l.condition, "remarks": l.remarks} for l in lines])
    return _pdf(pdf, f"goods-receipt-{grn.doc_number}")
