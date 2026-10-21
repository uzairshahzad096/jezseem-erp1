"""Product Quotation and Product Sales Order endpoints."""

import uuid
from decimal import Decimal
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status as http
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.inventory.models import InventoryItem, ItemRack
from app.inventory.router import active_company_id
from app.finance import sales_orders as order_ledger
from app.partners.models import BusinessPartner
from app.sales import service
from app.sales.models import QUOTATION, SALES_ORDER, SalesDocument, SalesDocumentLine
from app.sales.schemas import ConvertIn, SalesDocumentIn, StatusChangeIn
from app.users.models import User

router = APIRouter(prefix="/sales", tags=["sales"])


def _current_fiscal_year(db: Session, company_id: uuid.UUID) -> str:
    from app.companies.models import FinancialYear
    fy = db.scalar(
        select(FinancialYear).where(
            FinancialYear.company_id == company_id, FinancialYear.is_current.is_(True)
        )
    )
    return fy.name if fy else str(date.today().year)


def _join_descriptions(descriptions) -> str | None:
    """The old ERP's grid shows every line's description in one Detail Items
    cell, so a user can see what a quotation is for without opening it."""
    text = " , ".join(d for d in descriptions if d)
    return text or None


def _detail_items(db: Session, doc_ids: list[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    """Detail Items text for the documents on this page — one query for the
    whole page rather than one per row."""
    if not doc_ids:
        return {}
    rows = db.execute(
        select(SalesDocumentLine.document_id, SalesDocumentLine.description)
        .where(SalesDocumentLine.document_id.in_(doc_ids))
        .order_by(SalesDocumentLine.document_id, SalesDocumentLine.line_number)
    ).all()

    grouped: dict[uuid.UUID, list[str]] = {}
    for doc_id, description in rows:
        grouped.setdefault(doc_id, []).append(description)
    return {doc_id: _join_descriptions(v) for doc_id, v in grouped.items()}


def _summary(doc: SalesDocument, customers: dict, detail_items: str | None = None,
             source_number: str | None = None) -> dict:
    party = customers.get(doc.customer_id)
    return {
        "detail_items": detail_items,
        # The quotation this document came from, by its number rather than id,
        # so the listing can show it without a second lookup per row. Imported
        # orders whose quotation could not be linked fall back to the number
        # the old ERP recorded.
        "source_doc_number": source_number or doc.quotation_number,
        "dc_number": doc.dc_number,
        "customer_ntn": party.ntn if party else None,
        "customer_stn": party.stn if party else None,
        "id": str(doc.id),
        "doc_number": doc.doc_number,
        "doc_date": doc.doc_date,
        "customer_id": str(doc.customer_id),
        "customer_name": party.name if party else None,
        "status": doc.status,
        "payment_status": doc.payment_status,
        "demand_number": doc.demand_number,
        "customer_po_number": doc.customer_po_number,
        "delivery_person": doc.delivery_person,
        "vehicle_number": doc.vehicle_number,
        "location": doc.location,
        "payment_terms": doc.payment_terms,
        "with_sales_tax": doc.with_sales_tax,
        "is_service": doc.is_service,
        "currency": doc.currency,
        "remarks": doc.remarks,
        "excluding_tax_value": float(doc.excluding_tax_value),
        "sales_tax_value": float(doc.sales_tax_value),
        "gross_amount": float(doc.gross_amount),
        "discount_amount": float(doc.discount_amount),
        "freight_amount": float(doc.freight_amount),
        "net_receivable": float(doc.net_receivable),
        "total_items": doc.total_items,
        "source_document_id": str(doc.source_document_id) if doc.source_document_id else None,
    }


def _line_item_facts(db: Session, doc: SalesDocument) -> dict[uuid.UUID, tuple]:
    """Rack, stock and sale rate for the products on this document, so
    reopening it shows the same reference columns the create form does. One
    query for the whole document."""
    item_ids = [line.item_id for line in doc.lines if line.item_id]
    if not item_ids:
        return {}
    rows = db.execute(
        select(InventoryItem.id, ItemRack.rack_name, InventoryItem.opening_stock,
               InventoryItem.price)
        .outerjoin(ItemRack, ItemRack.id == InventoryItem.rack_id)
        .where(InventoryItem.id.in_(item_ids))
    ).all()
    return {row[0]: (row[1], row[2], row[3]) for row in rows}


def _detail(doc: SalesDocument, customer: BusinessPartner | None,
            db: Session | None = None) -> dict:
    data = _summary(
        doc,
        {doc.customer_id: customer} if customer else {},
        _join_descriptions(line.description for line in doc.lines),
    )
    facts = _line_item_facts(db, doc) if db is not None else {}
    data["lines"] = [
        {
            "id": str(line.id),
            "line_number": line.line_number,
            "item_id": str(line.item_id) if line.item_id else None,
            "item_code": line.item_code,
            "description": line.description,
            "uom": line.uom,
            "hs_code": line.hs_code,
            "lot_number": line.lot_number,
            "quantity": float(line.quantity),
            "delivered_quantity": float(line.delivered_quantity),
            "unit_price": float(line.unit_price),
            "currency": line.currency or doc.currency,
            "discount_percent": float(line.discount_percent),
            "tax_percent": float(line.tax_percent),
            "gross_amount": float(line.gross_amount),
            "discount_amount": float(line.discount_amount),
            "taxable_amount": float(line.taxable_amount),
            "tax_amount": float(line.tax_amount),
            "net_amount": float(line.net_amount),
            "rack_name": facts.get(line.item_id, (None, None, None))[0],
            "stock": (
                float(facts[line.item_id][1])
                if line.item_id in facts and facts[line.item_id][1] is not None
                else None
            ),
            # The product's own selling price, for the Sale Rate column —
            # what the item master says it goes for, beside what this
            # document actually charges.
            "sale_rate": (
                float(facts[line.item_id][2])
                if line.item_id in facts and facts[line.item_id][2] is not None
                else None
            ),
        }
        for line in doc.lines
    ]
    return data


def _list(doc_type: str, permission: str):
    def handler(
        search: str | None = None,
        status_filter: list[str] = Query(default=[], alias="status"),
        customer_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        sort: str = "doc_date",
        direction: str = "desc",
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=5000),
        db: Session = Depends(get_db),
        user: User = Depends(require_permission(permission)),
    ):
        company_id = active_company_id(db)
        stmt = select(SalesDocument).where(
            SalesDocument.company_id == company_id, SalesDocument.doc_type == doc_type
        )
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(
                SalesDocument.doc_number.ilike(like),
                SalesDocument.remarks.ilike(like),
                SalesDocument.demand_number.ilike(like),
                SalesDocument.customer_po_number.ilike(like),
                # Search the Detail Items text too, so "INK CARTRIDGE" finds
                # the quotations that quote it rather than nothing.
                SalesDocument.lines.any(SalesDocumentLine.description.ilike(like)),
            ))
        if status_filter:
            stmt = stmt.where(SalesDocument.status.in_(status_filter))
        if customer_id:
            stmt = stmt.where(SalesDocument.customer_id == customer_id)
        if date_from:
            stmt = stmt.where(SalesDocument.doc_date >= date_from)
        if date_to:
            stmt = stmt.where(SalesDocument.doc_date <= date_to)

        sortable = {
            "doc_date": SalesDocument.doc_date,
            "doc_number": SalesDocument.doc_number,
            "status": SalesDocument.status,
            "net_receivable": SalesDocument.net_receivable,
        }
        column = sortable.get(sort, SalesDocument.doc_date)
        # Tie-breakers: many documents share a date or a status, and without a
        # total order PostgreSQL may return them in a different order on each
        # query, so paging would repeat some rows and skip others.
        stmt = stmt.order_by(column.desc() if direction == "desc" else column.asc(),
                             SalesDocument.doc_number.desc(), SalesDocument.id)

        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()

        parties = {
            p.id: p for p in db.scalars(
                select(BusinessPartner).where(
                    BusinessPartner.id.in_([d.customer_id for d in rows])
                )
            ).all()
        } if rows else {}
        details = _detail_items(db, [d.id for d in rows])

        # Source quotation numbers for the page, in one query.
        source_ids = [d.source_document_id for d in rows if d.source_document_id]
        sources = dict(db.execute(
            select(SalesDocument.id, SalesDocument.doc_number)
            .where(SalesDocument.id.in_(source_ids))
        ).all()) if source_ids else {}

        return {
            "items": [
                _summary(d, parties, details.get(d.id), sources.get(d.source_document_id))
                for d in rows
            ],
            "total": total, "page": page, "page_size": page_size,
        }

    return handler


def _get_one(doc_type: str, permission: str):
    def handler(
        doc_id: uuid.UUID,
        db: Session = Depends(get_db),
        user: User = Depends(require_permission(permission)),
    ):
        doc = db.scalar(
            select(SalesDocument)
            .options(selectinload(SalesDocument.lines))
            .where(SalesDocument.id == doc_id, SalesDocument.doc_type == doc_type)
        )
        if doc is None:
            raise HTTPException(404, "Document not found.")
        return _detail(doc, db.get(BusinessPartner, doc.customer_id), db)

    return handler


def _create(doc_type: str, permission: str):
    def handler(
        payload: SalesDocumentIn,
        db: Session = Depends(get_db),
        user: User = Depends(require_permission(permission)),
    ):
        company_id = active_company_id(db)
        service.require_customer(db, company_id, payload.customer_id)
        fiscal_year = _current_fiscal_year(db, company_id)

        # Raised from a quotation: the same rules as a one-click conversion
        # apply, checked before anything is written.
        source = None
        if payload.source_document_id and doc_type == SALES_ORDER:
            source = service.check_convertible(db, company_id, payload.source_document_id)

        # Neither a quotation nor a sales order is held back by stock: an order
        # may be invoiced before the goods are in (owner, 19-Oct-2026).

        doc = SalesDocument(
            company_id=company_id,
            source_document_id=source.id if source else None,
            doc_type=doc_type,
            doc_number=service.allocate_number(db, company_id, doc_type, fiscal_year,
                                               payload.doc_date),
            doc_date=payload.doc_date,
            fiscal_year=fiscal_year,
            customer_id=uuid.UUID(payload.customer_id),
            status=payload.status,
            payment_status=payload.payment_status or ("PENDING" if doc_type == SALES_ORDER else None),
            demand_number=payload.demand_number,
            customer_po_number=payload.customer_po_number,
            dc_number=payload.dc_number,
            delivery_person=payload.delivery_person,
            vehicle_number=payload.vehicle_number,
            location=payload.location,
            with_sales_tax=payload.with_sales_tax,
            is_service=payload.is_service,
            currency=payload.currency,
            exchange_rate=payload.exchange_rate,
            payment_terms=payload.payment_terms,
            payment_reference=payload.payment_reference,
            remarks=payload.remarks,
            created_by=user.id,
        )
        service.apply_lines_and_totals(
            db, doc, [l.model_dump() for l in payload.lines],
            payload.freight_amount, payload.document_discount,
        )
        db.add(doc)
        if doc_type == SALES_ORDER and doc.status in order_ledger.IN_LEDGER:
            # Saved straight as Posted: it bills the customer, as a later posting would.
            db.flush()
            order_ledger.sync(db, doc, user)
        if source is not None:
            # Closed in the same transaction as the order it produced, so the
            # quotation can never be converted twice.
            source.status = "Closed"
            source.updated_by = user.id
        db.commit()
        db.refresh(doc)
        return _detail(doc, db.get(BusinessPartner, doc.customer_id), db)

    return handler


def _update(doc_type: str, permission: str):
    def handler(
        doc_id: uuid.UUID,
        payload: SalesDocumentIn,
        db: Session = Depends(get_db),
        user: User = Depends(require_permission(permission)),
    ):
        doc = db.scalar(
            select(SalesDocument)
            .options(selectinload(SalesDocument.lines))
            .where(SalesDocument.id == doc_id, SalesDocument.doc_type == doc_type)
        )
        if doc is None:
            raise HTTPException(404, "Document not found.")
        # A closed quotation is reopened by saving it with another status; any
        # other save on a finished document is refused.
        reopening = doc_type == QUOTATION and doc.status == "Closed" and payload.status != "Closed"
        if doc.status in ("Closed", "Cancelled", "Delivered") and not reopening:
            raise HTTPException(
                400, f"This document is '{doc.status}' and can no longer be edited. "
                     + ("Change its status to reopen it." if doc_type == QUOTATION and doc.status == "Closed" else ""))

        service.require_customer(db, doc.company_id, payload.customer_id)

        # The form carries Status, so saving it has to apply it — this handler
        # wrote every other field and silently dropped the status, which made
        # the picker look broken. Checked here, before anything is written, so
        # an illegal move refuses the whole save rather than half of it.
        new_status = payload.status if payload.status != doc.status else None
        if new_status:
            service.check_transition(doc_type, doc.status, new_status)


        in_ledger = doc_type == SALES_ORDER and order_ledger.live_journal(db, doc) is not None
        was = order_ledger.figures(doc) if in_ledger else None

        doc.doc_date = payload.doc_date
        doc.customer_id = uuid.UUID(payload.customer_id)
        doc.remarks = payload.remarks
        doc.demand_number = payload.demand_number
        doc.customer_po_number = payload.customer_po_number
        doc.dc_number = payload.dc_number
        doc.delivery_person = payload.delivery_person
        doc.vehicle_number = payload.vehicle_number
        doc.location = payload.location
        doc.with_sales_tax = payload.with_sales_tax
        doc.is_service = payload.is_service
        doc.currency = payload.currency
        doc.exchange_rate = payload.exchange_rate
        doc.payment_terms = payload.payment_terms
        doc.payment_status = payload.payment_status
        doc.payment_reference = payload.payment_reference
        doc.updated_by = user.id

        service.apply_lines_and_totals(
            db, doc, [l.model_dump() for l in payload.lines],
            payload.freight_amount, payload.document_discount,
        )

        # The order is in the ledger as an invoice: its customer, date and
        # amounts stay as posted. Cancel it and enter it again to change them.
        if in_ledger and order_ledger.figures(doc) != was:
            db.rollback()   # nothing of this save is kept
            raise HTTPException(
                400, f"Sales order {doc.doc_number} is posted to the customer's ledger, so its customer, "
                     "date and amounts cannot change. Cancel it (which reverses the ledger entry) and "
                     "create a new order.")

        # After the lines, never before: posting moves stock for what the
        # document says now, not for the lines it had when it was opened.
        if new_status:
            if doc_type == SALES_ORDER and new_status == "Posted":
                service.post_sales_order_stock(db, doc, user.id)
            doc.status = new_status
        if doc_type == SALES_ORDER:
            order_ledger.sync(db, doc, user)

        db.commit()
        db.refresh(doc)
        return _detail(doc, db.get(BusinessPartner, doc.customer_id), db)

    return handler


def _delete(doc_type: str, permission: str):
    def handler(
        doc_id: uuid.UUID,
        db: Session = Depends(get_db),
        user: User = Depends(require_permission(permission)),
    ):
        doc = db.scalar(
            select(SalesDocument).where(
                SalesDocument.id == doc_id,
                SalesDocument.doc_type == doc_type,
                SalesDocument.company_id == active_company_id(db),
            )
        )
        if doc is None:
            raise HTTPException(404, "Document not found.")

        # A document another one was built from cannot simply vanish, or the
        # sales order it produced would point at nothing.
        derived = db.scalar(
            select(SalesDocument).where(SalesDocument.source_document_id == doc.id)
        )
        if derived:
            raise HTTPException(
                http.HTTP_409_CONFLICT,
                f"This was converted into {derived.doc_type.replace('_', ' ')} "
                f"{derived.doc_number}. Delete that first if it really should go.",
            )

        # Posting writes stock movements; deleting the paperwork afterwards
        # would leave the ledger describing a document that no longer exists.
        if doc.status in ("Posted", "Delivered"):
            raise HTTPException(
                400,
                f"A {doc.status.lower()} document cannot be deleted. Cancel it instead, "
                "which reverses its stock movements and keeps the history.",
            )

        db.delete(doc)
        db.commit()

    return handler


def _set_status(doc_type: str, permission: str):
    def handler(
        doc_id: uuid.UUID,
        payload: StatusChangeIn,
        db: Session = Depends(get_db),
        user: User = Depends(require_permission(permission)),
    ):
        doc = db.scalar(
            select(SalesDocument)
            .options(selectinload(SalesDocument.lines))
            .where(SalesDocument.id == doc_id, SalesDocument.doc_type == doc_type)
        )
        if doc is None:
            raise HTTPException(404, "Document not found.")

        service.check_transition(doc_type, doc.status, payload.status)

        # Posting a sales order is what moves stock, and it happens in the
        # same transaction as the status change.
        if doc_type == SALES_ORDER and payload.status == "Posted" and doc.status != "Posted":

            service.post_sales_order_stock(db, doc, user.id)

        doc.status = payload.status
        doc.updated_by = user.id
        if doc_type == SALES_ORDER:
            order_ledger.sync(db, doc, user)
        db.commit()
        return {"id": str(doc.id), "status": doc.status}

    return handler


# ---------------- Quotations ----------------
router.add_api_route("/quotations", _list(QUOTATION, "sales.quotations.view"), methods=["GET"])
router.add_api_route("/quotations/{doc_id}", _get_one(QUOTATION, "sales.quotations.view"), methods=["GET"])
router.add_api_route("/quotations", _create(QUOTATION, "sales.quotations.create"),
                     methods=["POST"], status_code=http.HTTP_201_CREATED)
router.add_api_route("/quotations/{doc_id}", _update(QUOTATION, "sales.quotations.edit"), methods=["PUT"])
router.add_api_route("/quotations/{doc_id}/status", _set_status(QUOTATION, "sales.quotations.approve"),
                     methods=["POST"])
router.add_api_route("/quotations/{doc_id}", _delete(QUOTATION, "sales.quotations.delete"),
                     methods=["DELETE"], status_code=http.HTTP_204_NO_CONTENT)

# ---------------- Sales Orders ----------------
router.add_api_route("/orders", _list(SALES_ORDER, "sales.orders.view"), methods=["GET"])
router.add_api_route("/orders/{doc_id}", _get_one(SALES_ORDER, "sales.orders.view"), methods=["GET"])
router.add_api_route("/orders", _create(SALES_ORDER, "sales.orders.create"),
                     methods=["POST"], status_code=http.HTTP_201_CREATED)
router.add_api_route("/orders/{doc_id}", _update(SALES_ORDER, "sales.orders.edit"), methods=["PUT"])
router.add_api_route("/orders/{doc_id}/status", _set_status(SALES_ORDER, "sales.orders.post"),
                     methods=["POST"])
router.add_api_route("/orders/{doc_id}", _delete(SALES_ORDER, "sales.orders.delete"),
                     methods=["DELETE"], status_code=http.HTTP_204_NO_CONTENT)


@router.get("/items/{item_id}/last-rate")
def item_last_rate(
    item_id: uuid.UUID,
    customer_id: uuid.UUID | None = None,
    currency: str = "PKR",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("sales.quotations.view")),
):
    """What to price this item at for this customer, and why.

    - `last_rate`: the unit price on this customer's most recent quotation
      for the item (with no customer given: the most recent quotation to
      anyone, as before).
    - `suggested_rate`: that price; or, the first time the item is quoted to
      this customer, the price most other customers were quoted. Each other
      customer counts once, at their most recent price, so one customer who
      was quoted the item many times does not outweigh the rest. A tie goes
      to the price quoted most recently. Token prices under a tenth of the
      median are left out.
    - `basis`: "customer_last", "most_common_other_customers" or null.

    Only quotations count, in the requested currency, and zero-priced lines
    are skipped: they are the legacy rows that carry no price.
    """
    company_id = active_company_id(db)
    line_currency = func.coalesce(SalesDocumentLine.currency, SalesDocument.currency)
    base = (
        select(SalesDocumentLine.unit_price, line_currency.label("currency"), SalesDocument.doc_number,
               SalesDocument.doc_date, SalesDocument.doc_type)
        .join(SalesDocument, SalesDocument.id == SalesDocumentLine.document_id)
        .where(SalesDocumentLine.item_id == item_id, SalesDocument.company_id == company_id,
               SalesDocument.doc_type == QUOTATION, SalesDocumentLine.unit_price > 0,
               line_currency == currency)
    )
    latest = base.order_by(SalesDocument.doc_date.desc(), SalesDocument.created_at.desc()).limit(1)
    if customer_id:
        # This customer's own previous price counts from a quotation or a sales
        # order, whichever is more recent (owner, 15-Oct-2026).
        own = (select(SalesDocumentLine.unit_price, line_currency.label("currency"), SalesDocument.doc_number,
                      SalesDocument.doc_date, SalesDocument.doc_type)
               .join(SalesDocument, SalesDocument.id == SalesDocumentLine.document_id)
               .where(SalesDocumentLine.item_id == item_id, SalesDocument.company_id == company_id,
                      SalesDocument.doc_type.in_([QUOTATION, SALES_ORDER]), SalesDocumentLine.unit_price > 0,
                      line_currency == currency, SalesDocument.customer_id == customer_id)
               .order_by(SalesDocument.doc_date.desc(), SalesDocument.created_at.desc()).limit(1))
        last = db.execute(own).first()
    else:
        last = db.execute(latest).first()

    # Every other customer's most recent price for the item, one per customer.
    others = (base.add_columns(SalesDocument.customer_id)
              .order_by(SalesDocument.customer_id, SalesDocument.doc_date.desc(), SalesDocument.created_at.desc())
              .distinct(SalesDocument.customer_id))
    if customer_id:
        others = others.where(SalesDocument.customer_id != customer_id)
    other = [(Decimal(r.unit_price), r.doc_date) for r in db.execute(others).all()]
    if other:
        # Token prices (a line quoted at 1.00) are not real prices: skip
        # anything under a tenth of the median.
        median = sorted(p for p, _ in other)[len(other) // 2]
        other = [(p, d) for p, d in other if p >= median / 10]
    # The price most customers were last quoted; on a tie, the one quoted
    # most recently.
    votes: dict[Decimal, list] = {}
    for price, on in other:
        count, latest_on = votes.get(price, [0, on])
        votes[price] = [count + 1, max(latest_on, on)]
    common = max(votes.items(), key=lambda kv: (kv[1][0], kv[1][1]))[0] if votes else None

    if customer_id and last is not None:
        basis, suggested = "customer_last", float(last.unit_price)
    elif common is not None:
        basis, suggested = "most_common_other_customers", float(common)
    else:
        basis, suggested = None, None
    explained = basis == "most_common_other_customers"

    return {
        "last_rate": float(last.unit_price) if last else None,
        "currency": currency,
        "doc_number": last.doc_number if last else None,
        "doc_date": last.doc_date if last else None,
        "doc_type": last.doc_type if last else None,
        "suggested_rate": suggested,
        "basis": basis,
        # How the price was chosen, for the tooltip on the form.
        "customers_at_price": votes[common][0] if explained else None,
        "customers_compared": len(other) if explained else None,
        "price_range": [float(min(p for p, _ in other)), float(max(p for p, _ in other))] if explained else None,
    }


@router.post("/quotations/{quotation_id}/convert", status_code=http.HTTP_201_CREATED)
def convert_to_sales_order(
    quotation_id: uuid.UUID,
    payload: ConvertIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("sales.orders.create")),
):
    """Turn an approved quotation into a sales order, carrying everything
    forward so nothing is retyped (requirements doc 1.2)."""
    quotation = db.scalar(
        select(SalesDocument)
        .options(selectinload(SalesDocument.lines))
        .where(SalesDocument.id == quotation_id, SalesDocument.doc_type == QUOTATION)
    )
    if quotation is None:
        raise HTTPException(404, "Quotation not found.")

    order = service.convert_quotation_to_sales_order(
        db, quotation, user.id, payload.model_dump(exclude_none=True)
    )
    db.commit()
    db.refresh(order)
    return _detail(order, db.get(BusinessPartner, order.customer_id), db)
