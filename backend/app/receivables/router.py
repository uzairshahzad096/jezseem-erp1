"""
Sales invoices, credit/debit notes, customer receipts and AR reports.

    /api/v1/sales/invoices, /sales/credit-notes, /sales/debit-notes
    /api/v1/ar/receipts, /ar/allocations, /ar/... reports and setup

Every endpoint takes a FinanceContext (permission, company, branches, audit
details). Services raise FinanceError; this module commits and shapes the
responses.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.audit.service import changed, record, snapshot
from app.companies.models import Branch, Company
from app.core.database import get_db
from app.exports.writers import FORMATS
from app.finance.context import FinanceContext, finance_context
from app.finance.errors import FinanceError, db_guard
from app.finance.models import Account, JournalEntry
from app.gatepass.models import GatePass
from app.partners.models import BusinessPartner
from app.receivables import documents, receipts, reports, subledger
from app.receivables.models import (
    ARAllocation, ARItem, ARSettings, CustomerReceipt, PaymentMethod, PaymentTerm, TaxCode,
)
from app.receivables.schemas import (
    AllocateIn, ARSettingsIn, CreditAllocateIn, CustomerCreditIn, DocumentIn, PaymentMethodIn,
    PaymentTermIn, ReasonIn, ReceiptIn, TaxCodeIn,
)
from app.sales.models import CREDIT_NOTE, DEBIT_NOTE, SALES_INVOICE, SALES_ORDER, SalesDocument
from app.users.models import User

sales_router = APIRouter(prefix="/sales", tags=["sales invoices"])
ar_router = APIRouter(prefix="/ar", tags=["receivables"])


def commit(db: Session) -> None:
    with db_guard(db):
        db.commit()


def _num(value):
    return float(value) if isinstance(value, Decimal) else value


def _plain(data):
    """Decimals to floats, recursively, for JSON."""
    if isinstance(data, dict):
        return {k: _plain(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_plain(v) for v in data]
    if isinstance(data, uuid.UUID):
        return str(data)
    return _num(data)


def _users(db, ids) -> dict:
    ids = {i for i in ids if i}
    return {u.id: u.full_name for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


# ============================================================ documents

PERMS = {
    SALES_INVOICE: {"view": "sales.invoice.view", "create": "sales.invoice.create", "edit": "sales.invoice.edit",
                    "confirm": "sales.invoice.confirm", "post": "sales.invoice.post",
                    "cancel": "sales.invoice.cancel"},
    CREDIT_NOTE: {"view": "ar.view", "create": "ar.credit_note.create", "edit": "ar.credit_note.create",
                  "confirm": "ar.credit_note.create", "post": "ar.credit_note.post",
                  "cancel": "ar.credit_note.reverse"},
    DEBIT_NOTE: {"view": "ar.view", "create": "ar.credit_note.create", "edit": "ar.credit_note.create",
                 "confirm": "ar.credit_note.create", "post": "ar.credit_note.post",
                 "cancel": "ar.credit_note.reverse"},
}
PATHS = {SALES_INVOICE: "invoices", CREDIT_NOTE: "credit-notes", DEBIT_NOTE: "debit-notes"}


def _doc_summary(db, d: SalesDocument, customers: dict) -> dict:
    state = documents.payment_state(db, d)
    c = customers.get(d.customer_id)
    return {
        "id": str(d.id), "doc_type": d.doc_type, "doc_number": d.doc_number, "doc_date": d.doc_date,
        "due_date": d.due_date, "customer_id": str(d.customer_id), "customer_name": c.name if c else None,
        "customer_code": c.code if c else None, "status": d.status, "payment_status": state["payment_status"],
        "overdue": state["overdue"], "currency": d.currency, "exchange_rate": _num(d.exchange_rate or 1),
        "excluding_tax_value": _num(d.excluding_tax_value), "sales_tax_value": _num(d.sales_tax_value),
        "discount_amount": _num(d.discount_amount), "freight_amount": _num(d.freight_amount),
        "net_total": _num(d.net_receivable), "paid": _num(state["paid"]), "outstanding": _num(state["outstanding"]),
        "is_cash_sale": d.is_cash_sale, "branch_id": str(d.branch_id) if d.branch_id else None,
        "source_document_id": str(d.source_document_id) if d.source_document_id else None,
        "credit_check_status": d.credit_check_status,
    }


def _doc_detail(db, d: SalesDocument) -> dict:
    customer = db.get(BusinessPartner, d.customer_id)
    data = _doc_summary(db, d, {d.customer_id: customer})
    refs = {}
    for key, ref_id in (("source", d.source_document_id), ("quotation", d.quotation_id)):
        if ref_id:
            ref = db.get(SalesDocument, ref_id)
            refs[key] = {"id": str(ref.id), "doc_type": ref.doc_type, "doc_number": ref.doc_number} if ref else None
    if d.gate_pass_id:
        gp = db.get(GatePass, d.gate_pass_id)
        refs["gate_pass"] = {"id": str(gp.id), "doc_number": gp.doc_number} if gp else None
    journals = {}
    for key, jid in (("journal", d.journal_entry_id), ("cancel_journal", d.cancel_journal_id)):
        if jid:
            j = db.get(JournalEntry, jid)
            journals[key] = {"id": str(j.id), "journal_number": j.journal_number}
    users = _users(db, [d.created_by, d.confirmed_by, d.posted_by, d.cancelled_by, d.credit_approved_by])

    allocations = []
    item = subledger.item_for_document(db, d.id)
    if item is not None:
        side = ARAllocation.from_item_id if d.doc_type == CREDIT_NOTE else ARAllocation.to_item_id
        other_side = ARAllocation.to_item_id if d.doc_type == CREDIT_NOTE else ARAllocation.from_item_id
        rows = db.execute(select(ARAllocation, ARItem).join(ARItem, ARItem.id == other_side)
                          .where(side == item.id).order_by(ARAllocation.allocation_date)).all()
        allocations = [{"id": str(a.id), "document_number": other.document_number, "item_type": other.item_type,
                        "receipt_id": str(other.receipt_id) if other.receipt_id else None,
                        "sales_document_id": str(other.sales_document_id) if other.sales_document_id else None,
                        "amount": _num(a.amount), "date": a.allocation_date, "status": a.status,
                        "reason": a.reason} for a, other in rows]
    order_progress = None
    if d.doc_type == SALES_INVOICE and d.source_document_id:
        order = db.get(SalesDocument, d.source_document_id)
        if order is not None and order.doc_type == SALES_ORDER:
            order_progress = _plain(documents.order_progress(db, order))
    return {
        **data, "customer": {"id": str(customer.id), "code": customer.code, "name": customer.name,
                             "address": customer.address, "ntn": customer.ntn, "stn": customer.stn,
                             "credit_limit": _num(customer.credit_limit)},
        "fiscal_year": d.fiscal_year, "payment_term_id": str(d.payment_term_id) if d.payment_term_id else None,
        "payment_terms": d.payment_terms, "due_date_overridden": d.due_date_overridden,
        "billing_address": d.billing_address, "shipping_address": d.shipping_address,
        "customer_po_number": d.customer_po_number, "location": d.location, "remarks": d.remarks,
        "tax_inclusive": d.tax_inclusive, "cash_account_id": str(d.cash_account_id) if d.cash_account_id else None,
        "reason_code": d.reason_code, "reason": d.reason, "cancel_reason": d.cancel_reason,
        "quotation_id": str(d.quotation_id) if d.quotation_id else None,
        "gate_pass_id": str(d.gate_pass_id) if d.gate_pass_id else None,
        "references": refs, **journals,
        "created_by": users.get(d.created_by), "created_at": d.created_at,
        "confirmed_by": users.get(d.confirmed_by), "confirmed_at": d.confirmed_at,
        "posted_by": users.get(d.posted_by), "posted_at": d.posted_at,
        "cancelled_by": users.get(d.cancelled_by), "cancelled_at": d.cancelled_at,
        "credit_approved_by": users.get(d.credit_approved_by),
        "allocations": allocations, "order_progress": order_progress,
        "lines": [{
            "id": str(l.id), "line_number": l.line_number, "item_id": str(l.item_id) if l.item_id else None,
            "item_code": l.item_code, "description": l.description, "uom": l.uom, "lot_number": l.lot_number,
            "quantity": _num(l.quantity), "unit_price": _num(l.unit_price),
            "discount_percent": _num(l.discount_percent), "tax_code_id": str(l.tax_code_id) if l.tax_code_id else None,
            "tax_percent": _num(l.tax_percent), "gross_amount": _num(l.gross_amount),
            "discount_amount": _num(l.discount_amount), "taxable_amount": _num(l.taxable_amount),
            "tax_amount": _num(l.tax_amount), "net_amount": _num(l.net_amount),
            "source_line_id": str(l.source_line_id) if l.source_line_id else None,
            "gate_pass_line_id": str(l.gate_pass_line_id) if l.gate_pass_line_id else None,
        } for l in d.lines],
    }


def _register_documents(doc_type: str):
    perms, path = PERMS[doc_type], PATHS[doc_type]

    @sales_router.get(f"/{path}", name=f"list_{path}")
    def list_documents(
        search: str | None = None, status: str | None = None, customer_id: uuid.UUID | None = None,
        payment_status: str | None = None, date_from: date | None = None, date_to: date | None = None,
        page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=5000),
        db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(perms["view"])),
    ):
        stmt = select(SalesDocument).where(SalesDocument.company_id == ctx.company_id,
                                           SalesDocument.doc_type == doc_type)
        condition = ctx.branch_condition(SalesDocument.branch_id)
        if condition is not None:
            stmt = stmt.where(condition)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(SalesDocument.doc_number.ilike(like), SalesDocument.remarks.ilike(like),
                                  SalesDocument.customer_po_number.ilike(like),
                                  SalesDocument.customer_id.in_(select(BusinessPartner.id).where(
                                      BusinessPartner.name.ilike(like)))))
        if status:
            stmt = stmt.where(SalesDocument.status == status)
        if customer_id:
            stmt = stmt.where(SalesDocument.customer_id == customer_id)
        if date_from:
            stmt = stmt.where(SalesDocument.doc_date >= date_from)
        if date_to:
            stmt = stmt.where(SalesDocument.doc_date <= date_to)
        stmt = stmt.order_by(SalesDocument.doc_date.desc(), SalesDocument.doc_number.desc())
        if payment_status:
            # Derived, so filtered after loading; lists of posted documents are small.
            rows = [d for d in db.scalars(stmt) if documents.payment_state(db, d)["payment_status"] == payment_status
                    or (payment_status == "OVERDUE" and documents.payment_state(db, d)["overdue"])]
            total, rows = len(rows), rows[(page - 1) * page_size: page * page_size]
        else:
            total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
        customers = {p.id: p for p in db.scalars(select(BusinessPartner).where(
            BusinessPartner.id.in_({d.customer_id for d in rows})))} if rows else {}
        return {"items": [_doc_summary(db, d, customers) for d in rows], "total": total,
                "page": page, "page_size": page_size}

    @sales_router.get(f"/{path}/{{doc_id}}", name=f"get_{path}")
    def get_document(doc_id: uuid.UUID, db: Session = Depends(get_db),
                     ctx: FinanceContext = Depends(finance_context(perms["view"]))):
        return _doc_detail(db, documents.load(db, ctx, doc_id, doc_type))

    @sales_router.post(f"/{path}", status_code=201, name=f"create_{path}")
    def create_document(payload: DocumentIn, db: Session = Depends(get_db),
                        ctx: FinanceContext = Depends(finance_context(perms["create"]))):
        doc = documents.create(db, ctx, doc_type, payload.model_dump())
        commit(db)
        return _doc_detail(db, documents.load(db, ctx, doc.id))

    @sales_router.put(f"/{path}/{{doc_id}}", name=f"update_{path}")
    def update_document(doc_id: uuid.UUID, payload: DocumentIn, db: Session = Depends(get_db),
                        ctx: FinanceContext = Depends(finance_context(perms["edit"]))):
        documents.load(db, ctx, doc_id, doc_type)
        documents.update(db, ctx, doc_id, payload.model_dump())
        commit(db)
        return _doc_detail(db, documents.load(db, ctx, doc_id))

    @sales_router.post(f"/{path}/{{doc_id}}/confirm", name=f"confirm_{path}")
    def confirm_document(doc_id: uuid.UUID, db: Session = Depends(get_db),
                         ctx: FinanceContext = Depends(finance_context(perms["confirm"]))):
        documents.load(db, ctx, doc_id, doc_type)
        doc, check = documents.confirm(db, ctx, doc_id)
        commit(db)
        return {**_doc_detail(db, documents.load(db, ctx, doc.id)), "credit_check": _plain(check)}

    @sales_router.post(f"/{path}/{{doc_id}}/reopen", name=f"reopen_{path}")
    def reopen_document(doc_id: uuid.UUID, db: Session = Depends(get_db),
                        ctx: FinanceContext = Depends(finance_context(perms["edit"]))):
        documents.load(db, ctx, doc_id, doc_type)
        documents.reopen(db, ctx, doc_id)
        commit(db)
        return _doc_detail(db, documents.load(db, ctx, doc_id))

    @sales_router.post(f"/{path}/{{doc_id}}/post", name=f"post_{path}")
    def post_document(doc_id: uuid.UUID, db: Session = Depends(get_db),
                      ctx: FinanceContext = Depends(finance_context(perms["post"]))):
        documents.load(db, ctx, doc_id, doc_type)
        documents.post(db, ctx, doc_id)
        commit(db)
        return _doc_detail(db, documents.load(db, ctx, doc_id))

    @sales_router.post(f"/{path}/{{doc_id}}/cancel", name=f"cancel_{path}")
    def cancel_document(doc_id: uuid.UUID, payload: ReasonIn, db: Session = Depends(get_db),
                        ctx: FinanceContext = Depends(finance_context(perms["cancel"]))):
        documents.load(db, ctx, doc_id, doc_type)
        documents.cancel(db, ctx, doc_id, payload.reason or "")
        commit(db)
        return _doc_detail(db, documents.load(db, ctx, doc_id))


for _type in (SALES_INVOICE, CREDIT_NOTE, DEBIT_NOTE):
    _register_documents(_type)


@sales_router.post("/invoices/{doc_id}/approve-credit")
def approve_credit(doc_id: uuid.UUID, payload: ReasonIn, db: Session = Depends(get_db),
                   ctx: FinanceContext = Depends(finance_context("sales.invoice.credit_approve"))):
    documents.approve_credit(db, ctx, doc_id, payload.reason or "")
    commit(db)
    return _doc_detail(db, documents.load(db, ctx, doc_id))


@sales_router.get("/invoicing/from-order/{order_id}")
def invoice_from_order(order_id: uuid.UUID, db: Session = Depends(get_db),
                       ctx: FinanceContext = Depends(finance_context("sales.invoice.create"))):
    """The invoice a sales order would produce: customer and every line with
    quantity left to invoice. Nothing is saved until the form is."""
    return _plain(documents.draft_from_order(db, ctx, order_id))


@sales_router.get("/invoicing/from-gate-pass/{pass_id}")
def invoice_from_gate_pass(pass_id: uuid.UUID, db: Session = Depends(get_db),
                           ctx: FinanceContext = Depends(finance_context("sales.invoice.create"))):
    return _plain(documents.draft_from_gate_pass(db, ctx, pass_id))


@sales_router.get("/invoicing/from-invoice/{invoice_id}")
def note_from_invoice(invoice_id: uuid.UUID, kind: str = Query("credit_note", pattern="^(credit_note|debit_note)$"),
                      db: Session = Depends(get_db),
                      ctx: FinanceContext = Depends(finance_context("ar.credit_note.create"))):
    return _plain(documents.draft_from_invoice(db, ctx, invoice_id, kind))


@sales_router.get("/invoicing/order-progress/{order_id}")
def order_progress(order_id: uuid.UUID, db: Session = Depends(get_db),
                   ctx: FinanceContext = Depends(finance_context("sales.invoice.view"))):
    order = documents._load_order(db, ctx, order_id)
    invoices = db.scalars(select(SalesDocument).where(
        SalesDocument.doc_type == SALES_INVOICE, SalesDocument.source_document_id == order.id)
        .order_by(SalesDocument.doc_date)).all()
    return {"order_id": str(order.id), "order_number": order.doc_number, "status": order.status,
            "lines": _plain(documents.order_progress(db, order)),
            "invoices": [{"id": str(i.id), "doc_number": i.doc_number, "status": i.status,
                          "net_total": _num(i.net_receivable)} for i in invoices]}


# ============================================================ receipts

def _receipt_detail(db, r: CustomerReceipt) -> dict:
    customer = db.get(BusinessPartner, r.customer_id)
    method = db.get(PaymentMethod, r.payment_method_id)
    account = db.get(Account, r.deposit_account_id)
    s = receipts.summary(db, r)
    users = _users(db, [r.created_by, r.posted_by, r.reversed_by])
    journals = {}
    for key, jid in (("journal", r.journal_entry_id), ("reversal_journal", r.reversal_journal_id)):
        if jid:
            j = db.get(JournalEntry, jid)
            journals[key] = {"id": str(j.id), "journal_number": j.journal_number}
    allocations = []
    item = receipts.receipt_item(db, r)
    if item is not None:
        rows = db.execute(select(ARAllocation, ARItem).join(ARItem, ARItem.id == ARAllocation.to_item_id)
                          .where(ARAllocation.from_item_id == item.id).order_by(ARAllocation.created_at)).all()
        allocations = [{"id": str(a.id), "item_id": str(t.id), "document_number": t.document_number,
                        "sales_document_id": str(t.sales_document_id) if t.sales_document_id else None,
                        "amount": _num(a.amount), "date": a.allocation_date, "status": a.status,
                        "reason": a.reason} for a, t in rows]
    return {
        "id": str(r.id), "receipt_number": r.receipt_number, "receipt_date": r.receipt_date,
        "customer_id": str(r.customer_id), "customer_name": customer.name, "customer_code": customer.code,
        "payment_method_id": str(r.payment_method_id), "payment_method": method.name, "method_kind": method.kind,
        "deposit_account_id": str(r.deposit_account_id), "deposit_account": f"{account.code} {account.name}",
        "amount": _num(r.amount), "currency": r.currency, "exchange_rate": _num(r.exchange_rate),
        "wht_amount": _num(r.wht_amount or 0), "banked": _num(r.amount - (r.wht_amount or 0)),
        "amount_base": _num(r.amount_base), "reference": r.reference, "cheque_number": r.cheque_number,
        "cheque_date": r.cheque_date, "bank_name": r.bank_name, "notes": r.notes, "status": r.status,
        "branch_id": str(r.branch_id) if r.branch_id else None,
        "planned_allocations": r.planned_allocations, "allocations": allocations,
        "allocated": _num(s["allocated"]), "unallocated": _num(s["unallocated"]),
        "allocation_status": s["allocation_status"], **journals,
        "created_by": users.get(r.created_by), "created_at": r.created_at,
        "posted_by": users.get(r.posted_by), "posted_at": r.posted_at,
        "reversed_by": users.get(r.reversed_by), "reversed_at": r.reversed_at, "reverse_reason": r.reverse_reason,
    }


@ar_router.get("/receipts")
def list_receipts(
    search: str | None = None, status: str | None = None, customer_id: uuid.UUID | None = None,
    date_from: date | None = None, date_to: date | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=5000),
    db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context("ar.view")),
):
    stmt = select(CustomerReceipt).where(CustomerReceipt.company_id == ctx.company_id)
    condition = ctx.branch_condition(CustomerReceipt.branch_id)
    if condition is not None:
        stmt = stmt.where(condition)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(CustomerReceipt.receipt_number.ilike(like), CustomerReceipt.reference.ilike(like),
                              CustomerReceipt.cheque_number.ilike(like),
                              CustomerReceipt.customer_id.in_(select(BusinessPartner.id).where(
                                  BusinessPartner.name.ilike(like)))))
    if status:
        stmt = stmt.where(CustomerReceipt.status == status)
    if customer_id:
        stmt = stmt.where(CustomerReceipt.customer_id == customer_id)
    if date_from:
        stmt = stmt.where(CustomerReceipt.receipt_date >= date_from)
    if date_to:
        stmt = stmt.where(CustomerReceipt.receipt_date <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(CustomerReceipt.receipt_date.desc(), CustomerReceipt.receipt_number.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_receipt_detail(db, r) for r in rows], "total": total, "page": page, "page_size": page_size}


@ar_router.get("/receipts/{receipt_id}")
def get_receipt(receipt_id: uuid.UUID, db: Session = Depends(get_db),
                ctx: FinanceContext = Depends(finance_context("ar.view"))):
    return _receipt_detail(db, receipts.load(db, ctx, receipt_id))


@ar_router.get("/receipts/{receipt_id}/voucher.pdf")
def print_receipt(receipt_id: uuid.UUID, db: Session = Depends(get_db),
                  ctx: FinanceContext = Depends(finance_context("ar.view"))):
    from app.receivables.receipt_pdf import render_receipt
    receipt = receipts.load(db, ctx, receipt_id)
    if receipt.status == "DRAFT":
        raise FinanceError("Post the receipt before printing the voucher.")
    detail = _receipt_detail(db, receipt)
    pdf = render_receipt(db.get(Company, ctx.company_id).name, detail, detail["allocations"])
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{receipt.receipt_number}.pdf"'})


@ar_router.post("/receipts", status_code=201)
def create_receipt(payload: ReceiptIn, db: Session = Depends(get_db),
                   ctx: FinanceContext = Depends(finance_context("ar.receipt.create"))):
    receipt = receipts.create(db, ctx, payload.model_dump())
    commit(db)
    return _receipt_detail(db, receipts.load(db, ctx, receipt.id))


@ar_router.put("/receipts/{receipt_id}")
def update_receipt(receipt_id: uuid.UUID, payload: ReceiptIn, db: Session = Depends(get_db),
                   ctx: FinanceContext = Depends(finance_context("ar.receipt.create"))):
    receipts.update(db, ctx, receipt_id, payload.model_dump())
    commit(db)
    return _receipt_detail(db, receipts.load(db, ctx, receipt_id))


@ar_router.post("/receipts/{receipt_id}/post")
def post_receipt(receipt_id: uuid.UUID, db: Session = Depends(get_db),
                 ctx: FinanceContext = Depends(finance_context("ar.receipt.post"))):
    receipts.post(db, ctx, receipt_id)
    commit(db)
    return _receipt_detail(db, receipts.load(db, ctx, receipt_id))


@ar_router.post("/receipts/{receipt_id}/cancel")
def cancel_receipt(receipt_id: uuid.UUID, payload: ReasonIn, db: Session = Depends(get_db),
                   ctx: FinanceContext = Depends(finance_context("ar.receipt.create"))):
    receipts.cancel(db, ctx, receipt_id, payload.reason or "")
    commit(db)
    return _receipt_detail(db, receipts.load(db, ctx, receipt_id))


@ar_router.post("/receipts/{receipt_id}/reverse")
def reverse_receipt(receipt_id: uuid.UUID, payload: ReasonIn, db: Session = Depends(get_db),
                    ctx: FinanceContext = Depends(finance_context("ar.receipt.reverse"))):
    receipts.reverse(db, ctx, receipt_id, payload.reason or "")
    commit(db)
    return _receipt_detail(db, receipts.load(db, ctx, receipt_id))


@ar_router.post("/receipts/{receipt_id}/allocate")
def allocate_receipt(receipt_id: uuid.UUID, payload: AllocateIn, db: Session = Depends(get_db),
                     ctx: FinanceContext = Depends(finance_context("ar.receipt.allocate"))):
    receipts.allocate(db, ctx, receipt_id, [a.model_dump() for a in payload.allocations], payload.allocation_date)
    commit(db)
    return _receipt_detail(db, receipts.load(db, ctx, receipt_id))


@ar_router.post("/allocations")
def allocate_credit(payload: CreditAllocateIn, db: Session = Depends(get_db),
                    ctx: FinanceContext = Depends(finance_context("ar.receipt.allocate"))):
    """Allocate any unapplied credit (credit note, opening credit or advance)."""
    source = db.get(ARItem, payload.from_item_id)
    if source is None or source.company_id != ctx.company_id:
        raise FinanceError("That credit does not exist.", 404)
    allocation = subledger.allocate(db, ctx.audit, ctx.company_id, payload.from_item_id, payload.to_item_id,
                                    payload.amount, payload.allocation_date or date.today())
    commit(db)
    return {"id": str(allocation.id)}


@ar_router.post("/allocations/{allocation_id}/unallocate")
def unallocate(allocation_id: uuid.UUID, payload: ReasonIn, db: Session = Depends(get_db),
               ctx: FinanceContext = Depends(finance_context("ar.receipt.allocate"))):
    subledger.unallocate(db, ctx.audit, ctx.company_id, allocation_id, payload.reason or "")
    commit(db)
    return {"id": str(allocation_id), "status": "REVERSED"}


# ============================================================ customers

@ar_router.get("/customers/{customer_id}/open-items")
def customer_open_items(customer_id: uuid.UUID, include_credits: bool = False, db: Session = Depends(get_db),
                        ctx: FinanceContext = Depends(finance_context("ar.view"))):
    return _plain(reports.open_items(db, ctx, customer_id, include_credits))


@ar_router.get("/customers/{customer_id}/profile")
def customer_profile(customer_id: uuid.UUID, db: Session = Depends(get_db),
                     ctx: FinanceContext = Depends(finance_context("ar.view"))):
    return _plain(reports.customer_profile(db, ctx, customer_id))


@ar_router.put("/customers/{customer_id}/credit")
def set_customer_credit(customer_id: uuid.UUID, payload: CustomerCreditIn, db: Session = Depends(get_db),
                        ctx: FinanceContext = Depends(finance_context("ar.settings"))):
    customer = db.get(BusinessPartner, customer_id)
    if customer is None or customer.company_id != ctx.company_id:
        raise FinanceError("That customer does not exist.", 404)
    if payload.credit_limit is not None and payload.credit_limit < 0:
        raise FinanceError("A credit limit cannot be negative.")
    if payload.default_payment_term_id:
        documents._term(db, ctx.company_id, payload.default_payment_term_id)
    before = {"credit_limit": customer.credit_limit, "default_payment_term_id": customer.default_payment_term_id}
    customer.credit_limit = payload.credit_limit
    customer.default_payment_term_id = payload.default_payment_term_id
    record(db, ctx.audit, action="update", module="receivables", entity="business_partners",
           entity_id=customer.id, company_id=ctx.company_id, old_values=before,
           new_values={"credit_limit": payload.credit_limit,
                       "default_payment_term_id": payload.default_payment_term_id})
    commit(db)
    return _plain(reports.customer_profile(db, ctx, customer_id))


# ============================================================ reports

REPORTS = "ar.reports"


@ar_router.get("/statement")
def customer_statement(customer_id: uuid.UUID, date_from: date | None = None, date_to: date | None = None,
                       branch_id: uuid.UUID | None = None, currency: str | None = None,
                       db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(REPORTS))):
    return _plain(reports.statement(db, ctx, customer_id, date_from, date_to, branch_id, currency))


@ar_router.get("/aging")
def ar_aging(as_of: date | None = None, customer_id: uuid.UUID | None = None, branch_id: uuid.UUID | None = None,
             buckets: str | None = None, db: Session = Depends(get_db),
             ctx: FinanceContext = Depends(finance_context(REPORTS))):
    edges = None
    if buckets:
        try:
            edges = sorted({int(x) for x in buckets.split(",") if x.strip()})
        except ValueError as error:
            raise FinanceError("Buckets are day counts separated by commas, e.g. 30,60,90,120.") from error
    return _plain(reports.aging(db, ctx, as_of, customer_id, branch_id, edges))


@ar_router.get("/large-balances")
def ar_large_balances(minimum: Decimal = Decimal("2000000"), as_of: date | None = None,
                      db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(REPORTS))):
    return _plain(reports.large_balances(db, ctx, minimum, as_of))


@ar_router.get("/balances")
def ar_balances(as_of: date | None = None, db: Session = Depends(get_db),
                ctx: FinanceContext = Depends(finance_context(REPORTS))):
    return _plain(reports.customer_balances(db, ctx, as_of))


@ar_router.get("/reconciliation")
def ar_reconciliation(as_of: date | None = None, db: Session = Depends(get_db),
                      ctx: FinanceContext = Depends(finance_context(REPORTS))):
    return _plain(reports.reconciliation(db, ctx, as_of))


@ar_router.get("/sales-summary")
def sales_summary(date_from: date | None = None, date_to: date | None = None, db: Session = Depends(get_db),
                  ctx: FinanceContext = Depends(finance_context(REPORTS))):
    return _plain(reports.sales_summary(db, ctx, date_from, date_to))


@ar_router.get("/dashboard")
def ar_dashboard(db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context("ar.view"))):
    return _plain(reports.dashboard(db, ctx))


REGISTERS = {
    "invoices": ("Sales Invoice Register", SALES_INVOICE),
    "credit-notes": ("Credit Note Register", CREDIT_NOTE),
    "debit-notes": ("Debit Note Register", DEBIT_NOTE),
    "receipts": ("Receipts Register", None),
}
DOC_COLUMNS = [("doc_number", "Number"), ("doc_date", "Date"), ("due_date", "Due"), ("customer", "Customer"),
               ("status", "Status"), ("payment_status", "Payment"), ("excluding_tax_value", "Excl. Tax"),
               ("sales_tax_value", "Sales Tax"), ("freight_amount", "Freight"), ("net_total", "Total"),
               ("paid", "Paid / Applied"), ("outstanding", "Outstanding"), ("currency", "Currency"),
               ("journal_number", "Journal")]
RECEIPT_COLUMNS = [("receipt_number", "Receipt"), ("receipt_date", "Date"), ("customer", "Customer"),
                   ("method", "Method"), ("deposit_account", "Deposited to"), ("reference", "Reference"),
                   ("amount", "Amount"), ("currency", "Currency"), ("allocated", "Allocated"),
                   ("unallocated", "Unallocated"), ("status", "Status"), ("journal_number", "Journal")]


def _register_rows(db, ctx, kind, date_from, date_to, customer_id, status):
    if kind not in REGISTERS:
        raise FinanceError("Unknown register.", 404)
    title, doc_type = REGISTERS[kind]
    if doc_type:
        return title, DOC_COLUMNS, reports.document_register(db, ctx, doc_type, date_from=date_from, date_to=date_to,
                                                             customer_id=customer_id, status=status)
    return title, RECEIPT_COLUMNS, reports.receipt_register(db, ctx, date_from=date_from, date_to=date_to,
                                                            customer_id=customer_id, status=status)


@ar_router.get("/registers/{kind}")
def register(kind: str, date_from: date | None = None, date_to: date | None = None,
             customer_id: uuid.UUID | None = None, status: str | None = None,
             db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(REPORTS))):
    title, columns, rows = _register_rows(db, ctx, kind, date_from, date_to, customer_id, status)
    return {"title": title, "columns": [{"key": k, "label": l} for k, l in columns], "rows": _plain(rows)}


def _file(db, ctx, title: str, stem: str, columns, rows, fmt: str, header: dict | None = None) -> Response:
    media_type, extension, writer = FORMATS[fmt]
    company = db.get(Company, ctx.company_id)
    heading = f"{title} — {company.name} ({company.default_currency})"
    if fmt == "csv":
        payload = writer(columns, rows)
    elif fmt == "pdf" and header:
        payload = writer(columns, rows, title, header)
    else:
        payload = writer(columns, rows, heading)
    record(db, ctx.audit, action="export", module="receivables", entity=stem, company_id=ctx.company_id,
           new_values={"format": fmt, "rows": len(rows)})
    commit(db)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return Response(content=payload, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{stem}-{stamp}.{extension}"'})


@ar_router.get("/export/{report}")
def export_report(
    report: str, request_format: str = Query("xlsx", alias="format", pattern="^(csv|xlsx|pdf)$"),
    customer_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None,
    as_of: date | None = None, status: str | None = None,
    db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context(REPORTS)),
):
    """Every AR report as XLSX, PDF or CSV, with the same filters as on screen."""
    if report in REGISTERS:
        title, columns, rows = _register_rows(db, ctx, report, date_from, date_to, customer_id, status)
        return _file(db, ctx, title, report, columns, rows, request_format)
    if report == "statement":
        if not customer_id:
            raise FinanceError("Choose a customer.")
        # The same file as the General Ledger download for this customer.
        from app.finance.router import ledger_file
        title, columns, rows, stem, header = ledger_file(db, ctx, customer_id=customer_id,
                                                         date_from=date_from, date_to=date_to)
        return _file(db, ctx, title, stem, columns, rows, request_format, header)
    if report == "aging":
        a = reports.aging(db, ctx, as_of)
        rows = [{"customer": r["customer_name"], **{f"b{n}": v for n, v in enumerate(r["buckets"])},
                 "total_due": r["total_due"], "credits": r["credit_balance"], "net": r["net"]}
                for r in a["customers"]]
        columns = ([("customer", "Customer")] + [(f"b{n}", label) for n, label in enumerate(a["labels"])]
                   + [("total_due", "Total due"), ("credits", "Credit balance"), ("net", "Ledger balance")])
        return _file(db, ctx, f"AR Aging as at {a['as_of']:%d-%b-%Y}", "ar-aging", columns, rows, request_format)
    if report == "balances":
        rows = reports.customer_balances(db, ctx, as_of)
        columns = [("customer_code", "Code"), ("customer_name", "Customer"), ("invoiced", "Invoiced"),
                   ("credit_notes", "Credit notes"), ("receipts", "Receipts"), ("receivable", "Receivable"),
                   ("advances", "Advances"), ("net_balance", "Net balance"), ("overdue", "Overdue"),
                   ("credit_limit", "Credit limit"), ("available_credit", "Available")]
        return _file(db, ctx, "Customer Balances", "customer-balances", columns, rows, request_format)
    if report == "reconciliation":
        r = reports.reconciliation(db, ctx, as_of)
        columns = [("customer_name", "Customer"), ("sub_receivable", "Subledger AR"), ("gl_receivable", "GL AR"),
                   ("receivable_difference", "Difference"), ("sub_advances", "Subledger advances"),
                   ("gl_advances", "GL advances"), ("advances_difference", "Difference")]
        return _file(db, ctx, f"AR Reconciliation as at {r['as_of']:%d-%b-%Y}", "ar-reconciliation", columns,
                     r["customers"], request_format)
    if report == "sales-summary":
        s = reports.sales_summary(db, ctx, date_from, date_to)
        columns = [("customer_name", "Customer"), ("net_sales", "Net sales")]
        return _file(db, ctx, "Sales Summary by Customer", "sales-summary", columns, s["by_customer"], request_format)
    raise FinanceError("Unknown report.", 404)


# ============================================================ setup

SETUP = "ar.settings"


def _crud(model, schema, path: str, entity: str, fields):
    def serialize(row):
        return {"id": str(row.id), **{f: _plain(getattr(row, f)) for f in fields}}

    @ar_router.get(f"/{path}", name=f"list_{path}")
    def list_rows(db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context("ar.view"))):
        order = getattr(model, "sort_order", model.code)
        return [serialize(r) for r in db.scalars(select(model).where(model.company_id == ctx.company_id)
                                                 .order_by(order, model.code))]

    @ar_router.post(f"/{path}", status_code=201, name=f"create_{path}")
    def create_row(payload: schema, db: Session = Depends(get_db),
                   ctx: FinanceContext = Depends(finance_context(SETUP))):
        row = model(company_id=ctx.company_id, created_by=ctx.user_id, **payload.model_dump())
        _check(db, ctx, row)
        db.add(row)
        with db_guard(db):
            db.flush()
        record(db, ctx.audit, action="create", module="receivables", entity=entity, entity_id=row.id,
               company_id=ctx.company_id, new_values=snapshot(row))
        commit(db)
        return serialize(row)

    @ar_router.put(f"/{path}/{{row_id}}", name=f"update_{path}")
    def update_row(row_id: uuid.UUID, payload: schema, db: Session = Depends(get_db),
                   ctx: FinanceContext = Depends(finance_context(SETUP))):
        row = db.get(model, row_id)
        if row is None or row.company_id != ctx.company_id:
            raise FinanceError("Not found.", 404)
        before = snapshot(row)
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
        _check(db, ctx, row)
        row.updated_by = ctx.user_id
        old, new = changed(before, snapshot(row))
        record(db, ctx.audit, action="update", module="receivables", entity=entity, entity_id=row.id,
               company_id=ctx.company_id, old_values=old, new_values=new)
        commit(db)
        return serialize(row)


def _check(db, ctx, row) -> None:
    account_id = getattr(row, "output_account_id", None) or getattr(row, "default_account_id", None)
    if account_id:
        account = db.get(Account, account_id)
        if account is None or account.company_id != ctx.company_id or not account.is_postable:
            raise FinanceError("Choose a posting account of this company.")
        if isinstance(row, PaymentMethod) and account.control_type not in ("CASH", "BANK"):
            raise FinanceError("A payment method deposits into a cash or bank account.")
    if isinstance(row, TaxCode):
        if row.tax_type in ("EXEMPT", "ZERO_RATED") and row.rate != 0:
            raise FinanceError("An exempt or zero-rated code has a rate of 0.")
        if not (0 <= row.rate < 100):
            raise FinanceError("The rate must be between 0 and 100.")
        if row.effective_from and row.effective_to and row.effective_to < row.effective_from:
            raise FinanceError("The code cannot expire before it takes effect.")


_crud(PaymentTerm, PaymentTermIn, "payment-terms", "payment_terms",
      ["code", "name", "days", "is_cash", "is_active", "sort_order"])
_crud(PaymentMethod, PaymentMethodIn, "payment-methods", "payment_methods",
      ["code", "name", "kind", "requires_reference", "default_account_id", "is_active", "sort_order"])
_crud(TaxCode, TaxCodeIn, "tax-codes", "tax_codes",
      ["code", "name", "tax_type", "rate", "output_account_id", "effective_from", "effective_to", "is_active",
       "description"])


@ar_router.get("/settings")
def get_settings(db: Session = Depends(get_db), ctx: FinanceContext = Depends(finance_context("ar.view"))):
    row = documents.settings(db, ctx.company_id)
    return {"credit_limit_policy": row.credit_limit_policy, "sales_order_cutoff_date": row.sales_order_cutoff_date,
            "allow_quotation_invoice": row.allow_quotation_invoice,
            "default_payment_term_id": str(row.default_payment_term_id) if row.default_payment_term_id else None,
            "aging_buckets": row.aging_buckets,
            "cash_accounts": [{"id": str(a.id), "label": f"{a.code} {a.name}", "control_type": a.control_type}
                              for a in db.scalars(select(Account).where(
                                  Account.company_id == ctx.company_id, Account.control_type.in_(["CASH", "BANK"]),
                                  Account.is_postable.is_(True), Account.is_active.is_(True)).order_by(Account.code))]}


@ar_router.put("/settings")
def update_settings(payload: ARSettingsIn, db: Session = Depends(get_db),
                    ctx: FinanceContext = Depends(finance_context(SETUP))):
    row = documents.settings(db, ctx.company_id)
    if payload.default_payment_term_id:
        documents._term(db, ctx.company_id, payload.default_payment_term_id)
    before = snapshot(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    row.updated_by = ctx.user_id
    old, new = changed(before, snapshot(row))
    record(db, ctx.audit, action="update", module="receivables", entity="ar_settings", entity_id=row.id,
           company_id=ctx.company_id, old_values=old, new_values=new)
    commit(db)
    return get_settings(db, ctx)
