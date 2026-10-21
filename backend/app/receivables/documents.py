"""
Sales invoices, credit notes and debit notes.

These are doc types on the existing `sales_documents` table, so they share
its lines, its calculation engine and its print renderer with quotations and
orders. The lifecycle is DRAFT → CONFIRMED → POSTED, with CANCELLED from any
of them. Payment state is never stored: it is read from the AR subledger.

Posting builds a PostingRequest and hands it to the Phase 1 engine. Nothing
in this module writes a journal line itself.

What the invoice deliberately does not do:
- move stock. The stock issue already happened when the sales order was
  posted (or the gate pass approved), so moving it again would issue twice;
- post COGS. There is no cost basis until inventory valuation (Phase 4),
  which will post COGS at the stock issue. See docs/finance/02-phase2-plan.md.
"""

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.audit.service import record
from app.common import currency as currency_codes
from app.common.calculations import LineInput, calculate_document
from app.companies.models import FinancialYear
from app.finance import numbering, periods, posting
from app.finance.context import FinanceContext
from app.finance.errors import FinanceError, db_guard
from app.finance.models import Account, JournalEntry
from app.finance.posting import PostingRequest, money
from app.gatepass.models import GatePass, GatePassLine
from app.inventory.models import InventoryItem
from app.partners.models import BusinessPartner
from app.receivables import subledger
from app.receivables.models import (
    CREDIT_NOTE as ITEM_CREDIT, DEBIT_NOTE as ITEM_DEBIT, INVOICE as ITEM_INVOICE, KIND_AR,
    ARSettings, PaymentTerm, TaxCode,
)
from app.sales.models import (
    CREDIT_NOTE, DEBIT_NOTE, QUOTATION, SALES_INVOICE, SALES_ORDER, SalesDocument, SalesDocumentLine,
)

ZERO = Decimal("0")
DRAFT, CONFIRMED, POSTED, CANCELLED = "DRAFT", "CONFIRMED", "POSTED", "CANCELLED"

SERIES = {SALES_INVOICE: "SI", CREDIT_NOTE: "CN", DEBIT_NOTE: "DN"}
LABEL = {SALES_INVOICE: "Invoice", CREDIT_NOTE: "Credit note", DEBIT_NOTE: "Debit note"}
EVENT = {SALES_INVOICE: "SALES_INVOICE_POSTED", CREDIT_NOTE: "SALES_CREDIT_NOTE_POSTED",
         DEBIT_NOTE: "SALES_DEBIT_NOTE_POSTED"}
JOURNAL_DOC = {SALES_INVOICE: "SALES_INVOICE", CREDIT_NOTE: "SALES_CREDIT_NOTE",
               DEBIT_NOTE: "SALES_DEBIT_NOTE"}
ITEM_TYPE = {SALES_INVOICE: ITEM_INVOICE, CREDIT_NOTE: ITEM_CREDIT, DEBIT_NOTE: ITEM_DEBIT}
#: Sales orders that have issued their goods and may be invoiced.
INVOICEABLE_ORDER_STATUSES = ("Posted", "Delivered")
CREDIT_REASONS = ["SALES_RETURN", "PRICE_CORRECTION", "DISCOUNT", "TAX_CORRECTION", "CANCELLATION", "OTHER"]


# ------------------------------------------------------------ lookups

def settings(db: Session, company_id: uuid.UUID) -> ARSettings:
    row = db.scalar(select(ARSettings).where(ARSettings.company_id == company_id))
    if row is None:
        raise FinanceError("Receivables are not set up for this company. Run Finance → Chart of Accounts → "
                           "install defaults.")
    return row


def load(db: Session, ctx: FinanceContext, doc_id: uuid.UUID, doc_type: str | None = None) -> SalesDocument:
    doc = db.scalar(select(SalesDocument).options(selectinload(SalesDocument.lines))
                    .where(SalesDocument.id == doc_id))
    if (doc is None or doc.company_id != ctx.company_id
            or (doc_type and doc.doc_type != doc_type) or doc.doc_type not in SERIES):
        raise FinanceError(f"That {LABEL.get(doc_type, 'document').lower()} does not exist.", 404)
    if ctx.branch_ids is not None and doc.branch_id not in ctx.branch_ids:
        raise FinanceError(f"That {LABEL[doc.doc_type].lower()} does not exist.", 404)
    return doc


def require_customer(db: Session, company_id: uuid.UUID, customer_id) -> BusinessPartner:
    customer = db.get(BusinessPartner, customer_id)
    if customer is None or customer.company_id != company_id:
        raise FinanceError("Choose a customer that exists in this company.")
    if not customer.is_customer:
        raise FinanceError(f"{customer.name} is not marked as a customer.")
    if not customer.is_active:
        raise FinanceError(f"{customer.name} is inactive and cannot be invoiced.")
    if not (customer.name or "").strip():
        raise FinanceError("The customer has no name on record.")
    return customer


def _term(db: Session, company_id: uuid.UUID, term_id) -> PaymentTerm | None:
    if not term_id:
        return None
    term = db.get(PaymentTerm, term_id)
    if term is None or term.company_id != company_id or not term.is_active:
        raise FinanceError("Choose an active payment term.")
    return term


def _tax_code(db: Session, company_id: uuid.UUID, code_id, on: date) -> TaxCode | None:
    if not code_id:
        return None
    code = db.get(TaxCode, code_id)
    if code is None or code.company_id != company_id or not code.is_active:
        raise FinanceError("A line uses a tax code that does not exist or is inactive.")
    if (code.effective_from and on < code.effective_from) or (code.effective_to and on > code.effective_to):
        raise FinanceError(f"Tax code {code.code} is not in effect on {on:%d-%b-%Y}.")
    return code


def code_for_rate(db: Session, company_id: uuid.UUID, rate, on: date) -> uuid.UUID | None:
    """The active tax code carrying the rate a source line was written at,
    so an invoice drafted from an order or gate pass names its tax code.
    None for untaxed lines, or when no single code matches (the user then
    chooses one)."""
    rate = Decimal(str(rate or 0))
    if rate == 0:
        return None
    matches = [c for c in db.scalars(select(TaxCode).where(
        TaxCode.company_id == company_id, TaxCode.is_active.is_(True), TaxCode.rate == rate))
        if not ((c.effective_from and on < c.effective_from) or (c.effective_to and on > c.effective_to))]
    return matches[0].id if len(matches) == 1 else None


# ------------------------------------------------------------ quantities

def _sum_lines(db: Session, column, ids, doc_type: str, exclude_doc: uuid.UUID | None) -> dict:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    stmt = (select(column, func.sum(SalesDocumentLine.quantity))
            .join(SalesDocument, SalesDocument.id == SalesDocumentLine.document_id)
            .where(column.in_(ids), SalesDocument.doc_type == doc_type, SalesDocument.status != CANCELLED)
            .group_by(column))
    if exclude_doc:
        stmt = stmt.where(SalesDocument.id != exclude_doc)
    return {k: Decimal(v or 0) for k, v in db.execute(stmt).all()}


def invoiced_quantities(db: Session, order_line_ids, exclude_doc=None) -> dict:
    """Quantity already on invoices (any status but cancelled) per order line.
    Drafts count, so two drafts cannot both claim the same units."""
    return _sum_lines(db, SalesDocumentLine.source_line_id, order_line_ids, SALES_INVOICE, exclude_doc)


def credited_quantities(db: Session, invoice_line_ids, exclude_doc=None) -> dict:
    return _sum_lines(db, SalesDocumentLine.source_line_id, invoice_line_ids, CREDIT_NOTE, exclude_doc)


def gate_pass_invoiced(db: Session, pass_line_ids, exclude_doc=None) -> dict:
    return _sum_lines(db, SalesDocumentLine.gate_pass_line_id, pass_line_ids, SALES_INVOICE, exclude_doc)


def order_progress(db: Session, order: SalesDocument) -> list[dict]:
    """Ordered, delivered, invoiced and remaining quantity per order line."""
    invoiced = invoiced_quantities(db, [l.id for l in order.lines])
    return [{
        "line_id": str(l.id), "line_number": l.line_number, "item_id": str(l.item_id) if l.item_id else None,
        "item_code": l.item_code, "description": l.description, "uom": l.uom,
        "ordered": l.quantity, "delivered": l.delivered_quantity,
        "invoiced": invoiced.get(l.id, ZERO),
        "remaining": max(l.quantity - invoiced.get(l.id, ZERO), ZERO),
        "unit_price": l.unit_price, "discount_percent": l.discount_percent, "tax_percent": l.tax_percent,
    } for l in order.lines]


# ------------------------------------------------------------ sources

def _load_order(db: Session, ctx: FinanceContext, order_id, *, lock: bool = False) -> SalesDocument:
    stmt = select(SalesDocument).options(selectinload(SalesDocument.lines)).where(SalesDocument.id == order_id)
    if lock:
        stmt = stmt.with_for_update(of=SalesDocument)
    order = db.scalar(stmt)
    if order is None or order.company_id != ctx.company_id or order.doc_type != SALES_ORDER:
        raise FinanceError("That sales order does not exist.", 404)
    return order


def check_order_invoiceable(db: Session, order: SalesDocument) -> None:
    if order.status not in INVOICEABLE_ORDER_STATUSES:
        raise FinanceError(f"Sales order {order.doc_number} is {order.status}; only a posted (delivered) "
                           "order can be invoiced.")
    if order.journal_entry_id:
        raise FinanceError(f"Sales order {order.doc_number} came from the previous ERP and is already in the "
                           "ledger as its own invoice; invoicing it again would count the sale twice.")
    cutoff = settings(db, order.company_id).sales_order_cutoff_date
    if cutoff and order.doc_date < cutoff:
        raise FinanceError(f"Sales order {order.doc_number} is dated {order.doc_date:%d-%b-%Y}, before "
                           f"invoicing started ({cutoff:%d-%b-%Y}). Balances from before that date "
                           "enter through Opening Balances, not new invoices.")


def draft_from_order(db: Session, ctx: FinanceContext, order_id) -> dict:
    """A ready-to-save invoice payload from a sales order: its customer and
    every line with quantity still to invoice."""
    order = _load_order(db, ctx, order_id)
    check_order_invoiceable(db, order)
    progress = order_progress(db, order)
    lines = [p for p in progress if p["remaining"] > 0]
    if not lines:
        raise FinanceError(f"Sales order {order.doc_number} is fully invoiced.")
    by_id = {str(l.id): l for l in order.lines}
    customer = db.get(BusinessPartner, order.customer_id)
    return {
        "customer_id": str(order.customer_id), "customer_label": f"{customer.code} {customer.name}",
        "source_document_id": str(order.id),
        "quotation_id": str(order.source_document_id) if order.source_document_id else None,
        "currency": order.currency, "exchange_rate": order.exchange_rate or 1,
        "location": order.location, "customer_po_number": order.customer_po_number,
        "freight_amount": ZERO, "remarks": order.remarks,
        "order_number": order.doc_number, "progress": progress,
        "lines": [{
            "source_line_id": p["line_id"], "item_id": p["item_id"], "item_code": p["item_code"],
            "description": p["description"], "uom": p["uom"], "quantity": p["remaining"],
            "unit_price": p["unit_price"], "discount_percent": p["discount_percent"],
            "tax_percent": p["tax_percent"], "lot_number": by_id[p["line_id"]].lot_number,
            "tax_code_id": code_for_rate(db, ctx.company_id, p["tax_percent"], date.today()),
            "max_quantity": p["remaining"],
        } for p in lines],
    }


def draft_from_gate_pass(db: Session, ctx: FinanceContext, pass_id) -> dict:
    gate_pass = db.scalar(select(GatePass).options(selectinload(GatePass.lines)).where(GatePass.id == pass_id))
    if gate_pass is None or gate_pass.company_id != ctx.company_id or gate_pass.pass_type.lower() != "outward":
        raise FinanceError("That outward gate pass does not exist.", 404)
    if gate_pass.status != "Approved":
        raise FinanceError(f"Gate pass {gate_pass.doc_number} is {gate_pass.status}; only an approved "
                           "(dispatched) pass can be invoiced.")
    if not gate_pass.party_id:
        raise FinanceError(f"Gate pass {gate_pass.doc_number} names no customer.")
    invoiced = gate_pass_invoiced(db, [l.id for l in gate_pass.lines])
    lines = []
    for l in gate_pass.lines:
        remaining = l.quantity - l.returned_quantity - invoiced.get(l.id, ZERO)
        if remaining > 0:
            lines.append({"gate_pass_line_id": str(l.id), "item_id": str(l.item_id) if l.item_id else None,
                          "item_code": l.item_code, "description": l.description, "uom": l.uom,
                          "quantity": remaining, "unit_price": l.unit_price,
                          "discount_percent": l.discount_percent, "tax_percent": l.tax_percent,
                          "tax_code_id": code_for_rate(db, ctx.company_id, l.tax_percent, date.today()),
                          "max_quantity": remaining})
    if not lines:
        raise FinanceError(f"Gate pass {gate_pass.doc_number} is fully invoiced.")
    party = db.get(BusinessPartner, gate_pass.party_id)
    return {"customer_id": str(gate_pass.party_id), "customer_label": f"{party.code} {party.name}",
            "gate_pass_id": str(gate_pass.id),
            "source_document_id": str(gate_pass.sales_document_id) if gate_pass.sales_document_id else None,
            "currency": gate_pass.currency, "exchange_rate": 1, "location": gate_pass.location,
            "customer_po_number": gate_pass.po_number, "pass_number": gate_pass.doc_number, "lines": lines}


def draft_from_invoice(db: Session, ctx: FinanceContext, invoice_id, doc_type: str) -> dict:
    """A credit note (or debit note) pre-filled from a posted invoice."""
    invoice = load(db, ctx, invoice_id, SALES_INVOICE)
    if invoice.status != POSTED:
        raise FinanceError(f"Invoice {invoice.doc_number} is {invoice.status}; notes are raised against posted invoices.")
    credited = credited_quantities(db, [l.id for l in invoice.lines]) if doc_type == CREDIT_NOTE else {}
    customer = db.get(BusinessPartner, invoice.customer_id)
    return {"customer_id": str(invoice.customer_id), "customer_label": f"{customer.code} {customer.name}",
            "source_document_id": str(invoice.id),
            "currency": invoice.currency, "exchange_rate": invoice.exchange_rate or 1,
            "tax_inclusive": invoice.tax_inclusive, "invoice_number": invoice.doc_number,
            "lines": [{
                "source_line_id": str(l.id), "item_id": str(l.item_id) if l.item_id else None,
                "item_code": l.item_code, "description": l.description, "uom": l.uom,
                "quantity": l.quantity - credited.get(l.id, ZERO), "unit_price": l.unit_price,
                "discount_percent": l.discount_percent,
                "tax_code_id": str(l.tax_code_id) if l.tax_code_id else None, "tax_percent": l.tax_percent,
                "max_quantity": l.quantity - credited.get(l.id, ZERO),
            } for l in invoice.lines if doc_type == DEBIT_NOTE or l.quantity - credited.get(l.id, ZERO) > 0]}


# ------------------------------------------------------------ validation of a draft

def _validate_sources(db: Session, ctx: FinanceContext, doc_type: str, data: dict, customer_id,
                      lines: list[dict], exclude_doc) -> dict:
    """Check the document against what it was raised from and return the
    resolved references. Quantities are checked here and again at posting."""
    refs = {"source_document_id": None, "quotation_id": data.get("quotation_id"), "gate_pass_id": None}
    source_id = data.get("source_document_id")

    if doc_type == SALES_INVOICE:
        if source_id:
            order = _load_order(db, ctx, source_id)
            check_order_invoiceable(db, order)
            if order.customer_id != customer_id:
                raise FinanceError(f"Sales order {order.doc_number} belongs to another customer.")
            order_lines = {l.id: l for l in order.lines}
            invoiced = invoiced_quantities(db, list(order_lines), exclude_doc)
            wanted: dict = defaultdict(lambda: ZERO)
            for n, line in enumerate(lines, start=1):
                if not line.get("source_line_id"):
                    continue
                source_line = order_lines.get(uuid.UUID(str(line["source_line_id"])))
                if source_line is None:
                    raise FinanceError(f"Line {n} refers to a line of another sales order.")
                wanted[source_line.id] += Decimal(str(line["quantity"]))
            for line_id, qty in wanted.items():
                source_line = order_lines[line_id]
                remaining = source_line.quantity - invoiced.get(line_id, ZERO)
                if qty > remaining:
                    raise FinanceError(
                        f"{source_line.description[:40]}: ordered {source_line.quantity:,.2f}, already invoiced "
                        f"{invoiced.get(line_id, ZERO):,.2f}, so at most {max(remaining, ZERO):,.2f} can be "
                        f"invoiced — not {qty:,.2f}.")
            refs["source_document_id"] = order.id
            refs["quotation_id"] = order.source_document_id
        elif data.get("quotation_id"):
            if not settings(db, ctx.company_id).allow_quotation_invoice:
                raise FinanceError("Invoicing straight from a quotation is switched off; raise a sales order "
                                   "first, or allow it under Receivables settings.")
            quotation = db.get(SalesDocument, data["quotation_id"])
            if (quotation is None or quotation.company_id != ctx.company_id or quotation.doc_type != QUOTATION
                    or quotation.status != "Approved"):
                raise FinanceError("Only an approved quotation of this company can be invoiced.")
            if quotation.customer_id != customer_id:
                raise FinanceError("The quotation belongs to another customer.")
            refs["quotation_id"] = quotation.id
        if data.get("gate_pass_id"):
            gate_pass = db.scalar(select(GatePass).options(selectinload(GatePass.lines))
                                  .where(GatePass.id == data["gate_pass_id"]))
            if gate_pass is None or gate_pass.company_id != ctx.company_id:
                raise FinanceError("That gate pass does not exist.")
            if gate_pass.status != "Approved" or gate_pass.pass_type.lower() != "outward":
                raise FinanceError("Only an approved outward gate pass can be invoiced.")
            if gate_pass.party_id != customer_id:
                raise FinanceError(f"Gate pass {gate_pass.doc_number} belongs to another party.")
            pass_lines = {l.id: l for l in gate_pass.lines}
            invoiced = gate_pass_invoiced(db, list(pass_lines), exclude_doc)
            wanted = defaultdict(lambda: ZERO)
            for n, line in enumerate(lines, start=1):
                if line.get("gate_pass_line_id"):
                    pass_line = pass_lines.get(uuid.UUID(str(line["gate_pass_line_id"])))
                    if pass_line is None:
                        raise FinanceError(f"Line {n} refers to a line of another gate pass.")
                    wanted[pass_line.id] += Decimal(str(line["quantity"]))
            for line_id, qty in wanted.items():
                pass_line = pass_lines[line_id]
                remaining = pass_line.quantity - pass_line.returned_quantity - invoiced.get(line_id, ZERO)
                if qty > remaining:
                    raise FinanceError(f"{pass_line.description[:40]}: only {max(remaining, ZERO):,.2f} of the "
                                       f"dispatched quantity is left to invoice, not {qty:,.2f}.")
            refs["gate_pass_id"] = gate_pass.id

    else:  # credit / debit note
        if source_id:
            invoice = db.scalar(select(SalesDocument).options(selectinload(SalesDocument.lines))
                                .where(SalesDocument.id == source_id))
            if invoice is None or invoice.company_id != ctx.company_id or invoice.doc_type != SALES_INVOICE:
                raise FinanceError("The original invoice does not exist.")
            if invoice.status != POSTED:
                raise FinanceError(f"Invoice {invoice.doc_number} is {invoice.status}; notes are raised "
                                   "against posted invoices.")
            if invoice.customer_id != customer_id:
                raise FinanceError(f"Invoice {invoice.doc_number} belongs to another customer.")
            if doc_type == CREDIT_NOTE:
                invoice_lines = {l.id: l for l in invoice.lines}
                credited = credited_quantities(db, list(invoice_lines), exclude_doc)
                for n, line in enumerate(lines, start=1):
                    if not line.get("source_line_id"):
                        continue
                    invoice_line = invoice_lines.get(uuid.UUID(str(line["source_line_id"])))
                    if invoice_line is None:
                        raise FinanceError(f"Line {n} refers to a line of another invoice.")
                    left = invoice_line.quantity - credited.get(invoice_line.id, ZERO)
                    if Decimal(str(line["quantity"])) > left:
                        raise FinanceError(f"{invoice_line.description[:40]}: invoiced {invoice_line.quantity:,.2f}, "
                                           f"already credited {credited.get(invoice_line.id, ZERO):,.2f}; at most "
                                           f"{max(left, ZERO):,.2f} can be credited.")
            refs["source_document_id"] = invoice.id
        elif doc_type == CREDIT_NOTE and not data.get("reason"):
            raise FinanceError("A credit note without an original invoice needs a reason.")
    return refs


def _apply_lines(db: Session, ctx: FinanceContext, doc: SalesDocument, lines: list[dict],
                 freight, document_discount) -> None:
    if not lines:
        raise FinanceError("Add at least one line.")
    if doc.doc_type != SALES_INVOICE and money(document_discount) != 0:
        raise FinanceError("A credit or debit note cannot carry a document discount; adjust the lines.")
    if doc.doc_type == DEBIT_NOTE and money(freight) != 0:
        raise FinanceError("Put freight on a debit note as a line of its own.")

    resolved = []
    for n, raw in enumerate(lines, start=1):
        quantity = Decimal(str(raw.get("quantity") or 0))
        price = Decimal(str(raw.get("unit_price") or 0))
        discount = Decimal(str(raw.get("discount_percent") or 0))
        if quantity <= 0:
            raise FinanceError(f"Line {n}: quantity must be greater than zero.")
        if price < 0:
            raise FinanceError(f"Line {n}: the price cannot be negative.")
        if not 0 <= discount <= 100:
            raise FinanceError(f"Line {n}: the discount must be between 0 and 100%.")
        item = None
        if raw.get("item_id"):
            item = db.get(InventoryItem, uuid.UUID(str(raw["item_id"])))
            if item is None or item.company_id != ctx.company_id:
                raise FinanceError(f"Line {n}: the product does not exist.")
        code = _tax_code(db, ctx.company_id, raw.get("tax_code_id"), doc.doc_date)
        # The rate comes from the tax code, never from the browser.
        rate = code.rate if code else Decimal(str(raw.get("tax_percent") or 0))
        if code is None and rate != 0:
            raise FinanceError(f"Line {n}: choose a tax code for a taxed line.")
        description = (raw.get("description") or (item.description if item else "")).strip()
        if not description:
            raise FinanceError(f"Line {n}: a description is required.")
        resolved.append((raw, item, code, quantity, price, discount, rate, description))

    totals = calculate_document(
        [LineInput(quantity=q, unit_price=p, discount_percent=d, tax_percent=r)
         for _, _, _, q, p, d, r, _ in resolved],
        freight_amount=money(freight), document_discount=money(document_discount),
        tax_inclusive=doc.tax_inclusive)
    if totals.net_receivable <= 0:
        raise FinanceError(f"The {LABEL[doc.doc_type].lower()} total must be greater than zero.")

    doc.lines = [SalesDocumentLine(
        line_number=n, item_id=item.id if item else None,
        item_code=raw.get("item_code") or (item.item_code if item else None),
        description=description, uom=raw.get("uom") or (item.uom if item else None),
        hs_code=raw.get("hs_code"), lot_number=raw.get("lot_number"), rack_name=raw.get("rack_name"),
        quantity=q, unit_price=p, currency=doc.currency, discount_percent=d, tax_percent=r,
        tax_code_id=code.id if code else None,
        source_line_id=uuid.UUID(str(raw["source_line_id"])) if raw.get("source_line_id") else None,
        gate_pass_line_id=uuid.UUID(str(raw["gate_pass_line_id"])) if raw.get("gate_pass_line_id") else None,
        gross_amount=c.gross_amount, discount_amount=c.discount_amount, taxable_amount=c.taxable_amount,
        tax_amount=c.tax_amount, net_amount=c.net_amount,
    ) for n, ((raw, item, code, q, p, d, r, description), c) in enumerate(zip(resolved, totals.lines), start=1)]
    doc.excluding_tax_value = totals.excluding_tax_value
    doc.sales_tax_value = totals.sales_tax_value
    doc.gross_amount = totals.gross_amount
    doc.discount_amount = totals.discount_total
    doc.freight_amount = totals.freight_amount
    doc.net_receivable = totals.net_receivable
    doc.total_items = len(resolved)
    doc.with_sales_tax = totals.sales_tax_value > 0


def _fill(db: Session, ctx: FinanceContext, doc: SalesDocument, data: dict, exclude_doc) -> None:
    """Validate and copy everything a draft carries."""
    customer = require_customer(db, ctx.company_id, data["customer_id"])
    doc_date: date = data["doc_date"]
    fy = periods.year_for_date(db, ctx.company_id, doc_date)
    if doc.financial_year_id and doc.financial_year_id != fy.id:
        raise FinanceError("The new date is in another financial year, where this number does not belong. "
                           "Cancel this document and raise it in that year.")
    periods.period_for_date(db, ctx.company_id, doc_date)

    code = currency_codes.normalise(data.get("currency"))
    rate = Decimal(str(data.get("exchange_rate") or 1))
    if rate <= 0:
        raise FinanceError("The exchange rate must be greater than zero.")
    if code == "PKR" and rate != 1:
        raise FinanceError("A PKR document has an exchange rate of 1.")

    lines = [dict(l) for l in data["lines"]]
    refs = _validate_sources(db, ctx, doc.doc_type, data, customer.id, lines, exclude_doc)

    term = _term(db, ctx.company_id, data.get("payment_term_id")
                 or (customer.default_payment_term_id if doc.doc_type != CREDIT_NOTE else None)
                 or settings(db, ctx.company_id).default_payment_term_id)
    if data.get("due_date"):
        due = data["due_date"]
        if due < doc_date:
            raise FinanceError("The due date cannot be before the document date.")
        overridden = term is None or due != doc_date + timedelta(days=term.days)
    else:
        due, overridden = doc_date + timedelta(days=term.days if term else 0), False

    cash_account = None
    if data.get("is_cash_sale"):
        if doc.doc_type != SALES_INVOICE:
            raise FinanceError("Only an invoice can be a cash sale.")
        cash_account = db.get(Account, data.get("cash_account_id")) if data.get("cash_account_id") else None
        if (cash_account is None or cash_account.company_id != ctx.company_id
                or cash_account.control_type not in ("CASH", "BANK")):
            raise FinanceError("A cash sale needs the cash or bank account the money went into.")

    doc.customer_id = customer.id
    doc.doc_date = doc_date
    doc.financial_year_id = fy.id
    doc.fiscal_year = fy.name
    doc.branch_id = ctx.default_branch(data.get("branch_id"))
    doc.currency = code
    doc.exchange_rate = rate
    doc.tax_inclusive = bool(data.get("tax_inclusive"))
    doc.payment_term_id = term.id if term else None
    doc.payment_terms = term.name if term else None
    doc.due_date = due
    doc.due_date_overridden = overridden
    doc.billing_address = data.get("billing_address") or customer.address
    doc.shipping_address = data.get("shipping_address")
    doc.customer_po_number = data.get("customer_po_number")
    doc.location = data.get("location")
    doc.remarks = data.get("remarks")
    doc.is_cash_sale = bool(data.get("is_cash_sale"))
    doc.cash_account_id = cash_account.id if cash_account else None
    doc.reason_code = data.get("reason_code")
    doc.reason = data.get("reason")
    doc.source_document_id = refs["source_document_id"]
    doc.quotation_id = refs["quotation_id"]
    doc.gate_pass_id = refs["gate_pass_id"]
    _apply_lines(db, ctx, doc, lines, data.get("freight_amount"), data.get("document_discount"))


# ------------------------------------------------------------ lifecycle

def create(db: Session, ctx: FinanceContext, doc_type: str, data: dict) -> SalesDocument:
    fy = periods.year_for_date(db, ctx.company_id, data["doc_date"])
    doc = SalesDocument(id=uuid.uuid4(), company_id=ctx.company_id, doc_type=doc_type, status=DRAFT,
                        created_by=ctx.user_id, customer_id=data["customer_id"], doc_date=data["doc_date"])
    _fill(db, ctx, doc, data, exclude_doc=None)
    doc.doc_number = numbering.allocate(db, ctx.company_id, SERIES[doc_type], fy, doc.branch_id)
    db.add(doc)
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="create", module="receivables", entity="sales_documents",
           entity_id=doc.id, company_id=ctx.company_id,
           new_values={"doc_type": doc_type, "number": doc.doc_number, "customer_id": doc.customer_id,
                       "total": doc.net_receivable, "source": doc.source_document_id})
    return doc


def update(db: Session, ctx: FinanceContext, doc_id, data: dict) -> SalesDocument:
    doc = load(db, ctx, doc_id)
    if doc.status != DRAFT:
        raise FinanceError(f"{LABEL[doc.doc_type]} {doc.doc_number} is {doc.status}; only a draft can be edited.")
    before = {"total": doc.net_receivable, "date": doc.doc_date, "customer_id": doc.customer_id,
              "lines": len(doc.lines), "due_date": doc.due_date}
    _fill(db, ctx, doc, data, exclude_doc=doc.id)
    doc.updated_by = ctx.user_id
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="update", module="receivables", entity="sales_documents",
           entity_id=doc.id, company_id=ctx.company_id, old_values=before,
           new_values={"total": doc.net_receivable, "date": doc.doc_date, "customer_id": doc.customer_id,
                       "lines": len(doc.lines), "due_date": doc.due_date})
    return doc


def _revalidate(db: Session, ctx: FinanceContext, doc: SalesDocument) -> None:
    """Re-run the draft checks against current data (customer still active,
    tax codes still in force, quantities still available)."""
    require_customer(db, ctx.company_id, doc.customer_id)
    for line in doc.lines:
        _tax_code(db, ctx.company_id, line.tax_code_id, doc.doc_date)
    lines = [{"source_line_id": l.source_line_id, "gate_pass_line_id": l.gate_pass_line_id,
              "quantity": l.quantity} for l in doc.lines]
    _validate_sources(db, ctx, doc.doc_type, {
        "source_document_id": doc.source_document_id, "quotation_id": doc.quotation_id,
        "gate_pass_id": doc.gate_pass_id, "reason": doc.reason}, doc.customer_id, lines, doc.id)


def credit_check(db: Session, ctx: FinanceContext, doc: SalesDocument) -> dict:
    customer = db.get(BusinessPartner, doc.customer_id)
    policy = settings(db, ctx.company_id).credit_limit_policy
    current = subledger.exposure(db, ctx.company_id, doc.customer_id)
    new_total = money(doc.net_receivable * (doc.exchange_rate or 1))
    limit = customer.credit_limit
    result = {"policy": policy, "credit_limit": limit, "current_outstanding": current,
              "document_total": new_total, "after_posting": current + new_total,
              "available_before": (limit - current) if limit is not None else None,
              "exceeded": limit is not None and current + new_total > limit}
    return result


def confirm(db: Session, ctx: FinanceContext, doc_id) -> tuple[SalesDocument, dict | None]:
    doc = load(db, ctx, doc_id)
    if doc.status != DRAFT:
        raise FinanceError(f"{LABEL[doc.doc_type]} {doc.doc_number} is {doc.status}; only a draft can be confirmed.")
    _revalidate(db, ctx, doc)
    check = None
    doc.credit_check_status = "OK"
    if doc.doc_type != CREDIT_NOTE and not doc.is_cash_sale:
        check = credit_check(db, ctx, doc)
        if check["exceeded"] and check["policy"] != "NONE":
            message = (f"{db.get(BusinessPartner, doc.customer_id).name} would owe "
                       f"{check['after_posting']:,.2f} against a credit limit of {check['credit_limit']:,.2f}.")
            if check["policy"] == "BLOCK":
                raise FinanceError(message + " The credit policy blocks this invoice.")
            doc.credit_check_status = "APPROVAL_REQUIRED" if check["policy"] == "APPROVAL" else "WARNING"
            check["message"] = message
    doc.status = CONFIRMED
    doc.confirmed_by = ctx.user_id
    doc.confirmed_at = datetime.now(timezone.utc)
    doc.updated_by = ctx.user_id
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="confirm", module="receivables", entity="sales_documents",
           entity_id=doc.id, company_id=ctx.company_id, old_values={"status": DRAFT},
           new_values={"status": CONFIRMED, "credit_check": doc.credit_check_status})
    return doc, check


def reopen(db: Session, ctx: FinanceContext, doc_id) -> SalesDocument:
    doc = load(db, ctx, doc_id)
    if doc.status != CONFIRMED:
        raise FinanceError("Only a confirmed document can go back to draft.")
    doc.status = DRAFT
    doc.credit_check_status = None
    doc.credit_approved_by = doc.credit_approved_at = None
    doc.updated_by = ctx.user_id
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="reopen", module="receivables", entity="sales_documents",
           entity_id=doc.id, company_id=ctx.company_id, old_values={"status": CONFIRMED},
           new_values={"status": DRAFT})
    return doc


def approve_credit(db: Session, ctx: FinanceContext, doc_id, reason: str) -> SalesDocument:
    doc = load(db, ctx, doc_id, SALES_INVOICE)
    if doc.status != CONFIRMED or doc.credit_check_status != "APPROVAL_REQUIRED":
        raise FinanceError("This invoice is not waiting for credit approval.")
    doc.credit_check_status = "APPROVED"
    doc.credit_approved_by = ctx.user_id
    doc.credit_approved_at = datetime.now(timezone.utc)
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="approve", module="receivables", entity="sales_documents",
           entity_id=doc.id, company_id=ctx.company_id, new_values={"credit_check": "APPROVED"},
           reason=reason or "Credit limit override")
    return doc


def _posting_request(db: Session, doc: SalesDocument) -> PostingRequest:
    line_discount = sum((l.discount_amount for l in doc.lines), ZERO)
    doc_discount = money(doc.discount_amount - line_discount)
    codes = {c.id: c for c in db.scalars(select(TaxCode).where(
        TaxCode.id.in_({l.tax_code_id for l in doc.lines if l.tax_code_id})))} if doc.lines else {}

    revenue_key = {SALES_INVOICE: "revenue", CREDIT_NOTE: "returns", DEBIT_NOTE: "revenue"}[doc.doc_type]
    revenue_splits = [{
        "amount": l.taxable_amount, "inventory_item_id": l.item_id, "quantity": l.quantity,
        "customer_id": doc.customer_id, "description": f"{doc.doc_number}: {l.description[:120]}",
    } for l in doc.lines if l.taxable_amount != 0]

    tax_by_code: dict = defaultdict(lambda: ZERO)
    for l in doc.lines:
        if l.tax_amount:
            tax_by_code[l.tax_code_id] += l.tax_amount
    tax_splits = [{
        "amount": amount, "customer_id": doc.customer_id,
        "account_id": codes[code_id].output_account_id if code_id in codes else None,
        "description": f"Output tax {codes[code_id].code if code_id in codes else ''} {doc.doc_number}".strip(),
    } for code_id, amount in tax_by_code.items()]

    amounts = {"receivable": doc.net_receivable, revenue_key: doc.excluding_tax_value}
    if doc.sales_tax_value:
        amounts["output_tax"] = doc.sales_tax_value
    if doc.freight_amount and doc.doc_type != DEBIT_NOTE:
        amounts["freight"] = doc.freight_amount
    if doc_discount and doc.doc_type == SALES_INVOICE:
        amounts["discount"] = doc_discount

    customer = db.get(BusinessPartner, doc.customer_id)
    return PostingRequest(
        event_code=EVENT[doc.doc_type], company_id=doc.company_id, journal_date=doc.doc_date,
        branch_id=doc.branch_id,
        description=f"{LABEL[doc.doc_type]} {doc.doc_number} — {customer.name}",
        reference=doc.customer_po_number, document_type=JOURNAL_DOC[doc.doc_type], document_id=doc.id,
        source_module="sales", source_reference=doc.doc_number,
        amounts=amounts, customer_id=doc.customer_id,
        account_overrides={"receivable": doc.cash_account_id} if doc.is_cash_sale else {},
        splits={revenue_key: revenue_splits, **({"output_tax": tax_splits} if tax_splits else {})},
        currency=doc.currency, exchange_rate=Decimal(doc.exchange_rate or 1),
    )


def _receivable_base(db: Session, journal: JournalEntry) -> Decimal:
    """The signed company-currency amount the journal put on the receivable
    account: the subledger item must equal it exactly, rounding included."""
    receivable = {a.id for a in db.scalars(select(Account).where(
        Account.company_id == journal.company_id, Account.control_type == "RECEIVABLE"))}
    return sum((l.base_debit - l.base_credit for l in journal.lines if l.account_id in receivable), ZERO)


def post(db: Session, ctx: FinanceContext, doc_id) -> SalesDocument:
    doc = load(db, ctx, doc_id)
    if doc.status != CONFIRMED:
        raise FinanceError(f"{LABEL[doc.doc_type]} {doc.doc_number} is {doc.status}; it must be confirmed "
                           "before it is posted.")
    if doc.credit_check_status == "APPROVAL_REQUIRED":
        raise FinanceError("This invoice exceeds the customer's credit limit and needs credit approval first.")
    # Lock the order so two invoices posting at once cannot both take its last units.
    if doc.doc_type == SALES_INVOICE and doc.source_document_id:
        _load_order(db, ctx, doc.source_document_id, lock=True)
    _revalidate(db, ctx, doc)
    if doc.doc_type == SALES_INVOICE and not doc.is_cash_sale and settings(db, ctx.company_id).credit_limit_policy == "BLOCK":
        check = credit_check(db, ctx, doc)
        if check["exceeded"]:
            raise FinanceError("The customer's credit limit would be exceeded; the credit policy blocks posting.")

    journal = posting.post(db, _posting_request(db, doc), ctx.audit)

    item = None
    if not doc.is_cash_sale:
        sign = Decimal("-1") if doc.doc_type == CREDIT_NOTE else Decimal("1")
        item = subledger.record_item(
            db, company_id=doc.company_id, branch_id=doc.branch_id, customer_id=doc.customer_id,
            item_type=ITEM_TYPE[doc.doc_type], kind=KIND_AR, number=doc.doc_number,
            document_date=doc.doc_date, due_date=doc.due_date if doc.doc_type != CREDIT_NOTE else doc.doc_date,
            currency=doc.currency, exchange_rate=Decimal(doc.exchange_rate or 1),
            amount=sign * doc.net_receivable, amount_base=_receivable_base(db, journal),
            sales_document_id=doc.id, journal_entry_id=journal.id, user_id=ctx.user_id)
        with db_guard(db):
            db.flush()

    doc.status = POSTED
    doc.journal_entry_id = journal.id
    doc.posted_by = ctx.user_id
    doc.posted_at = datetime.now(timezone.utc)
    doc.updated_by = ctx.user_id
    with db_guard(db):
        db.flush()

    # A credit note settles its own invoice first, as far as it is still open.
    if doc.doc_type == CREDIT_NOTE and item is not None and doc.source_document_id:
        target = subledger.item_for_document(db, doc.source_document_id)
        if target is not None and target.status == "OPEN":
            outstanding = subledger.open_amounts(db, [target])[target.id]
            amount = min(outstanding, doc.net_receivable)
            if amount > 0:
                subledger.allocate(db, ctx.audit, ctx.company_id, item.id, target.id, amount, doc.doc_date,
                                   note="Credit note applied to its invoice")

    record(db, ctx.audit, action="post", module="receivables", entity="sales_documents",
           entity_id=doc.id, company_id=ctx.company_id, old_values={"status": CONFIRMED},
           new_values={"status": POSTED, "journal": journal.journal_number, "total": doc.net_receivable})
    return doc


def cancel(db: Session, ctx: FinanceContext, doc_id, reason: str) -> SalesDocument:
    """Drafts and confirmed documents are simply cancelled. A posted one is
    reversed: its journal gets a mirror-image entry, its receivable item is
    closed, and the document stays on file marked CANCELLED."""
    doc = load(db, ctx, doc_id)
    if doc.status == CANCELLED:
        raise FinanceError(f"{LABEL[doc.doc_type]} {doc.doc_number} is already cancelled.")
    if not reason or len(reason.strip()) < 3:
        raise FinanceError("Give a reason for the cancellation; it is kept in the audit trail.")
    previous = doc.status
    if doc.status == POSTED:
        item = subledger.item_for_document(db, doc.id)
        if item is not None:
            if doc.doc_type == CREDIT_NOTE:
                for allocation in subledger.active_allocations(db, item.id, side="from"):
                    subledger.unallocate(db, ctx.audit, ctx.company_id, allocation.id,
                                         f"Credit note {doc.doc_number} cancelled")
            else:
                paid = subledger.active_allocations(db, item.id, side="to")
                if paid:
                    raise FinanceError(f"{LABEL[doc.doc_type]} {doc.doc_number} has receipts or credits "
                                       "allocated to it. Unallocate them first, or raise a credit note instead.")
        journal = db.get(JournalEntry, doc.journal_entry_id)
        reversal = posting.reverse(db, journal, max(date.today(), journal.journal_date),
                                   f"{LABEL[doc.doc_type]} {doc.doc_number} cancelled: {reason.strip()}",
                                   ctx.audit, allow_document=True)
        if item is not None:
            subledger.cancel_item(db, item)
        doc.cancel_journal_id = reversal.id
    doc.status = CANCELLED
    doc.cancelled_by = ctx.user_id
    doc.cancelled_at = datetime.now(timezone.utc)
    doc.cancel_reason = reason.strip()
    doc.updated_by = ctx.user_id
    with db_guard(db):
        db.flush()
    record(db, ctx.audit, action="cancel", module="receivables", entity="sales_documents",
           entity_id=doc.id, company_id=ctx.company_id, old_values={"status": previous},
           new_values={"status": CANCELLED, "reversal": doc.cancel_journal_id}, reason=reason.strip())
    return doc


def payment_state(db: Session, doc: SalesDocument) -> dict:
    """OPEN / PARTIALLY_PAID / PAID / OVERDUE, from the subledger."""
    if doc.status != POSTED:
        return {"payment_status": None, "paid": ZERO, "outstanding": ZERO if doc.status == CANCELLED
                else doc.net_receivable, "overdue": False}
    if doc.is_cash_sale:
        return {"payment_status": "PAID", "paid": doc.net_receivable, "outstanding": ZERO, "overdue": False}
    item = subledger.item_for_document(db, doc.id)
    if item is None:
        return {"payment_status": None, "paid": ZERO, "outstanding": ZERO, "overdue": False}
    open_ = subledger.open_amounts(db, [item])[item.id]
    total = abs(item.amount)
    if doc.doc_type == CREDIT_NOTE:
        return {"payment_status": "APPLIED" if open_ == 0 else ("PARTLY_APPLIED" if open_ < total else "UNAPPLIED"),
                "paid": total - open_, "outstanding": open_, "overdue": False}
    overdue = open_ > 0 and doc.due_date is not None and doc.due_date < date.today()
    status = "PAID" if open_ == 0 else ("PARTIALLY_PAID" if open_ < total else "OPEN")
    return {"payment_status": status, "paid": total - open_, "outstanding": open_, "overdue": overdue}
