"""
Sales document business logic.

Kept out of the router so the rules can be unit-tested without HTTP and so
the same logic serves the API, the PDF renderer and any future import.
"""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status as http
from sqlalchemy import BigInteger, func, select
from sqlalchemy.orm import Session

from app.common.calculations import LineInput, calculate_document
from app.common.numbering import next_dated_number, next_number
from app.inventory import stock
from app.inventory.models import InventoryItem, ItemLocation
from app.partners.models import BusinessPartner
from app.sales.models import (
    QUOTATION, SALES_ORDER, SalesDocument, SalesDocumentLine,
)

# Only transitions the requirements document states explicitly are enforced.
# Anything else is rejected rather than guessed at.
QUOTATION_TRANSITIONS = {
    "Draft": {"Sent", "Approved", "Rejected"},
    "Sent": {"Approved", "Rejected", "Closed"},
    "Approved": {"Closed", "Rejected"},
    "Rejected": {"Draft"},
    # A closed quotation can be reopened by changing its status. Reopening
    # does not let it become a second sales order: conversion still refuses
    # any quotation that already has one (check_convertible).
    "Closed": {"Draft", "Sent", "Approved", "Rejected"},
}
SALES_ORDER_TRANSITIONS = {
    "Draft": {"Posted", "Cancelled"},
    "Posted": {"Delivered", "Cancelled"},
    "Delivered": set(),
    "Cancelled": set(),
}


def _line_inputs(lines) -> list[LineInput]:
    return [
        LineInput(
            quantity=Decimal(str(line.get("quantity") or 0)),
            unit_price=Decimal(str(line.get("unit_price") or 0)),
            discount_percent=Decimal(str(line.get("discount_percent") or 0)),
            tax_percent=Decimal(str(line.get("tax_percent") or 0)),
        )
        for line in lines
    ]


def apply_lines_and_totals(
    db: Session, document: SalesDocument, lines: list[dict], freight, document_discount
) -> None:
    """Replace the document's lines and recompute every money figure.

    The client's own totals are ignored entirely — see app.common.calculations.
    """
    if not lines:
        raise HTTPException(http.HTTP_400_BAD_REQUEST, "Add at least one product line.")

    totals = calculate_document(
        _line_inputs(lines),
        freight_amount=Decimal(str(freight or 0)),
        document_discount=Decimal(str(document_discount or 0)),
    )

    new_lines: list[SalesDocumentLine] = []
    for index, (raw, computed) in enumerate(zip(lines, totals.lines), start=1):
        item = None
        if raw.get("item_id"):
            item = db.get(InventoryItem, uuid.UUID(raw["item_id"]))
            if item is None:
                raise HTTPException(http.HTTP_400_BAD_REQUEST,
                                    f"Line {index}: the selected product no longer exists.")

        description = (raw.get("description") or (item.description if item else "")).strip()
        if not description:
            raise HTTPException(http.HTTP_400_BAD_REQUEST, f"Line {index}: description is required.")
        if Decimal(str(raw.get("quantity") or 0)) <= 0:
            raise HTTPException(http.HTTP_400_BAD_REQUEST,
                                f"Line {index}: quantity must be greater than zero.")

        new_lines.append(SalesDocumentLine(
            line_number=index,
            item_id=item.id if item else None,
            item_code=raw.get("item_code") or (item.item_code if item else None),
            description=description,
            uom=raw.get("uom") or (item.uom if item else None),
            hs_code=raw.get("hs_code"),
            lot_number=raw.get("lot_number"),
            quantity=Decimal(str(raw.get("quantity") or 0)),
            unit_price=Decimal(str(raw.get("unit_price") or 0)),
            currency=raw.get("currency") or document.currency,
            discount_percent=Decimal(str(raw.get("discount_percent") or 0)),
            tax_percent=Decimal(str(raw.get("tax_percent") or 0)),
            gross_amount=computed.gross_amount,
            discount_amount=computed.discount_amount,
            taxable_amount=computed.taxable_amount,
            tax_amount=computed.tax_amount,
            net_amount=computed.net_amount,
        ))

    document.lines = new_lines
    document.excluding_tax_value = totals.excluding_tax_value
    document.sales_tax_value = totals.sales_tax_value
    document.gross_amount = totals.gross_amount
    document.discount_amount = totals.discount_total
    document.freight_amount = totals.freight_amount
    document.net_receivable = totals.net_receivable
    document.total_items = len(new_lines)


def highest_existing_number(db: Session, company_id: uuid.UUID, doc_type: str) -> int:
    """The largest purely numeric reference already used by this document type.

    Quotations came across from the old ERP as a plain series running up to
    1579, so a new one has to continue from there rather than restart at 1 and
    collide with a quotation that already exists. Non-numeric references are
    ignored — they cannot be counted from.
    """
    highest = db.scalar(
        select(func.max(func.cast(SalesDocument.doc_number, BigInteger))).where(
            SalesDocument.company_id == company_id,
            SalesDocument.doc_type == doc_type,
            SalesDocument.doc_number.op("~")("^[0-9]+$"),
        )
    )
    return int(highest or 0)


def highest_on_date(db: Session, company_id: uuid.UUID, doc_type: str, on_date: date) -> int:
    """The largest counter already used on a dated reference for that day.

    Imported orders already occupy 202609221, 202609222 and so on, so a fresh
    counter has to start above them rather than re-issue a number that is
    already on a printed delivery note.
    """
    scope = on_date.strftime("%Y%m%d")
    highest = db.scalar(
        select(func.max(
            func.cast(func.substr(SalesDocument.doc_number, len(scope) + 1), BigInteger)
        )).where(
            SalesDocument.company_id == company_id,
            SalesDocument.doc_type == doc_type,
            SalesDocument.doc_number.op("~")(f"^{scope}[0-9]+$"),
        )
    )
    return int(highest or 0)


def allocate_number(db: Session, company_id: uuid.UUID, doc_type: str,
                    fiscal_year: str, on_date: date | None = None) -> str:
    """The next reference for a document.

    The two document types are numbered differently, matching the old ERP:
    quotations run as one plain series continuing from the imported 1579,
    while sales orders restart each day behind the date — 202609221.
    """
    if doc_type == QUOTATION:
        return next_number(
            db, company_id, doc_type, fiscal_year, prefix="",
            continue_from=highest_existing_number(db, company_id, doc_type),
        )

    when = on_date or date.today()
    return next_dated_number(
        db, company_id, doc_type, when,
        continue_from=highest_on_date(db, company_id, doc_type, when),
    )


def check_transition(doc_type: str, current: str, target: str) -> None:
    if current == target:
        return
    table = QUOTATION_TRANSITIONS if doc_type == QUOTATION else SALES_ORDER_TRANSITIONS
    allowed = table.get(current, set())
    if target not in allowed:
        allowed_text = ", ".join(sorted(allowed)) or "nothing — this document is final"
        raise HTTPException(
            http.HTTP_400_BAD_REQUEST,
            f"A {doc_type.replace('_', ' ')} with status '{current}' cannot move to "
            f"'{target}'. Allowed: {allowed_text}.",
        )


def check_convertible(db: Session, company_id: uuid.UUID, source_id: str) -> SalesDocument:
    """The quotation a new sales order may be built from, or an explanation.

    Used when the order is assembled in the form from a quotation rather than
    converted in one step, so the same three rules apply either way: it must
    be a quotation, it must be approved, and it must not already have become
    an order.
    """
    quotation = db.get(SalesDocument, uuid.UUID(str(source_id)))
    if quotation is None or quotation.company_id != company_id:
        raise HTTPException(http.HTTP_404_NOT_FOUND, "That quotation no longer exists.")
    if quotation.doc_type != QUOTATION:
        raise HTTPException(http.HTTP_400_BAD_REQUEST, "Only quotations can be converted.")
    if quotation.status != "Approved":
        raise HTTPException(
            http.HTTP_400_BAD_REQUEST,
            f"Only approved quotations can be converted. {quotation.doc_number} "
            f"is '{quotation.status}'.",
        )

    existing = db.scalar(
        select(SalesDocument).where(
            SalesDocument.source_document_id == quotation.id,
            SalesDocument.doc_type == SALES_ORDER,
        )
    )
    if existing:
        raise HTTPException(
            http.HTTP_409_CONFLICT,
            f"Quotation {quotation.doc_number} was already converted into sales order "
            f"{existing.doc_number}.",
        )
    return quotation


def convert_quotation_to_sales_order(
    db: Session, quotation: SalesDocument, user_id: uuid.UUID, overrides: dict | None = None
) -> SalesDocument:
    """Create a sales order from an approved quotation.

    Requirements doc 1.2: only approved quotations convert, the customer,
    products, quantities and prices carry forward, and the user must not
    re-enter anything. A quotation converts once — the second attempt is
    refused and points at the order that already exists.
    """
    if quotation.doc_type != QUOTATION:
        raise HTTPException(http.HTTP_400_BAD_REQUEST, "Only quotations can be converted.")
    if quotation.status != "Approved":
        raise HTTPException(
            http.HTTP_400_BAD_REQUEST,
            f"Only approved quotations can be converted. This one is '{quotation.status}'.",
        )

    existing = db.scalar(
        select(SalesDocument).where(
            SalesDocument.source_document_id == quotation.id,
            SalesDocument.doc_type == SALES_ORDER,
        )
    )
    if existing:
        raise HTTPException(
            http.HTTP_409_CONFLICT,
            f"This quotation was already converted into sales order {existing.doc_number}.",
        )

    overrides = overrides or {}
    order = SalesDocument(
        company_id=quotation.company_id,
        branch_id=quotation.branch_id,
        doc_type=SALES_ORDER,
        doc_number=allocate_number(db, quotation.company_id, SALES_ORDER,
                                   quotation.fiscal_year or "",
                                   overrides.get("doc_date") or date.today()),
        doc_date=overrides.get("doc_date") or date.today(),
        fiscal_year=quotation.fiscal_year,
        customer_id=quotation.customer_id,
        source_document_id=quotation.id,
        status="Draft",
        payment_status="PENDING",
        with_sales_tax=quotation.with_sales_tax,
        is_service=quotation.is_service,
        currency=quotation.currency,
        exchange_rate=quotation.exchange_rate,
        payment_terms=quotation.payment_terms,
        remarks=quotation.remarks,
        customer_po_number=overrides.get("customer_po_number"),
        delivery_person=overrides.get("delivery_person"),
        vehicle_number=overrides.get("vehicle_number"),
        location=overrides.get("location"),
        created_by=user_id,
        # Totals copied as computed on the quotation; recalculated below.
        excluding_tax_value=quotation.excluding_tax_value,
        sales_tax_value=quotation.sales_tax_value,
        gross_amount=quotation.gross_amount,
        discount_amount=quotation.discount_amount,
        freight_amount=quotation.freight_amount,
        net_receivable=quotation.net_receivable,
        total_items=quotation.total_items,
    )

    order.lines = [
        SalesDocumentLine(
            line_number=line.line_number,
            item_id=line.item_id,
            item_code=line.item_code,
            description=line.description,
            uom=line.uom,
            hs_code=line.hs_code,
            lot_number=line.lot_number,
            quantity=line.quantity,
            unit_price=line.unit_price,
            currency=line.currency,
            discount_percent=line.discount_percent,
            tax_percent=line.tax_percent,
            gross_amount=line.gross_amount,
            discount_amount=line.discount_amount,
            taxable_amount=line.taxable_amount,
            tax_amount=line.tax_amount,
            net_amount=line.net_amount,
        )
        for line in quotation.lines
    ]

    db.add(order)
    quotation.status = "Closed"
    quotation.updated_by = user_id
    return order


def resolve_location(db: Session, company_id: uuid.UUID, name: str | None) -> uuid.UUID | None:
    """The Item Location matching a document's location text, if there is one.

    The document stores the location as text, so the match is by name. A name
    that is not on the list returns None: the movement is still recorded, just
    not attributed to a location, rather than blocking the posting of a real
    sale over a spelling.
    """
    if not name or not name.strip():
        return None
    return db.scalar(
        select(ItemLocation.id).where(
            ItemLocation.company_id == company_id,
            func.lower(func.trim(ItemLocation.location)) == name.strip().lower(),
        )
    )


def post_sales_order_stock(db: Session, order: SalesDocument, user_id: uuid.UUID) -> int:
    """Write the outward stock movements for a posted sales order.

    The stock comes off the location the order ships from, so a sale at
    Jezseem FSD reduces Jezseem FSD rather than an undifferentiated pool.

    Called inside the router's transaction so the status change and the
    ledger entries commit together (spec section 21 rule 11).
    """
    location_id = resolve_location(db, order.company_id, order.location)

    written = 0
    for line in order.lines:
        if line.item_id is None:
            continue
        stock.post_movement(
            db,
            company_id=order.company_id,
            item_id=line.item_id,
            direction=stock.OUT,
            quantity=line.quantity,
            source_type="sales_order",
            source_id=order.id,
            source_number=order.doc_number,
            entry_date=order.doc_date,
            unit_cost=line.unit_price,
            user_id=user_id,
            location_id=location_id,
        )
        line.delivered_quantity = line.quantity
        written += 1
    return written


def require_customer(db: Session, company_id: uuid.UUID, customer_id: str) -> BusinessPartner:
    partner = db.get(BusinessPartner, uuid.UUID(customer_id))
    if partner is None or partner.company_id != company_id:
        raise HTTPException(http.HTTP_400_BAD_REQUEST, "Select a valid customer.")
    if not partner.is_customer:
        raise HTTPException(http.HTTP_400_BAD_REQUEST,
                            f"'{partner.name}' is not marked as a customer.")
    return partner
