"""
Vouchers brought over from the previous ERP, shown read-only.

They sit in `voucher_import_staging`, loaded outside the application. Each row
is a voucher HEADER: number, date, party, total and narration. The old ERP
holds no account lines, so a row cannot become a journal entry by itself.

Receipt vouchers for a known customer were posted as customer receipts by
`app.finance.import_legacy_receipts` (bank or cash debit, the customer's
advance credit); those rows carry `import_status` POSTED and the receipt they
became. Everything else is listed here for reference only, with the reason in
`import_note`, and does not touch the ledger.

The staging table has no company column; it belongs to the one company this
installation holds.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.finance.context import FinanceContext, finance_context

router = APIRouter(prefix="/finance", tags=["finance"])

TABLE = "voucher_import_staging"
SORTS = {"voucher_date": "voucher_date", "voucher_number": "voucher_number", "customer_name": "customer_name",
         "amount": "debit_total", "voucher_type": "voucher_type"}


def _exists(db: Session) -> bool:
    return db.scalar(text("select to_regclass(:t) is not null"), {"t": f"public.{TABLE}"}) is True


@router.get("/imported-vouchers")
def imported_vouchers(
    search: str | None = None,
    voucher_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    posted: str | None = Query(None, pattern="^(yes|no)$"),
    sort: str = "voucher_date",
    direction: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=5000),
    db: Session = Depends(get_db),
    ctx: FinanceContext = Depends(finance_context("finance.view")),
):
    empty = {"items": [], "total": 0, "page": page, "page_size": page_size, "all_count": 0, "all_amount": 0.0,
             "filtered_amount": 0.0, "types": [], "statuses": {}, "posted_count": 0, "posted_amount": 0.0}
    if not _exists(db):
        return empty

    where, params = ["true"], {}
    if search:
        where.append("(voucher_number ilike :q or customer_name ilike :q or narration ilike :q "
                     "or reference_number ilike :q)")
        params["q"] = f"%{search.strip()}%"
    if voucher_type:
        where.append("voucher_type = :voucher_type")
        params["voucher_type"] = voucher_type
    if date_from:
        where.append("voucher_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        where.append("voucher_date <= :date_to")
        params["date_to"] = date_to
    condition = " and ".join(where)
    order = f"{SORTS.get(sort, 'voucher_date')} {'asc' if direction == 'asc' else 'desc'}, source_voucher_id"

    # The columns the receipt import adds; absent until it has been run.
    extra = {c for (c,) in db.execute(text(
        "select column_name from information_schema.columns where table_name = :t"), {"t": TABLE})}
    tracked = "posted_receipt_id" in extra
    if posted in ("yes", "no") and tracked:
        condition += " and posted_receipt_id is " + ("not null" if posted == "yes" else "null")
    more = ", posted_receipt_id, posted_receipt_number, import_note" if tracked else ""
    rows = db.execute(text(
        f"select source_voucher_id, voucher_number, voucher_date, voucher_type, customer_name, debit_total, "
        f"credit_total, reference_number, narration, import_status, source_financial_year{more} "
        f"from {TABLE} where {condition} order by {order} limit :limit offset :offset"),
        {**params, "limit": page_size, "offset": (page - 1) * page_size}).mappings().all()
    total, amount = db.execute(
        text(f"select count(*), coalesce(sum(debit_total), 0) from {TABLE} where {condition}"), params).one()
    posted_count, posted_amount = db.execute(text(
        f"select count(*), coalesce(sum(debit_total), 0) from {TABLE} where posted_receipt_id is not null")).one() \
        if tracked else (0, 0)
    types = db.execute(text(
        f"select voucher_type, count(*), coalesce(sum(debit_total), 0), min(voucher_date), max(voucher_date) "
        f"from {TABLE} group by voucher_type order by count(*) desc")).all()
    statuses = dict(db.execute(text(f"select import_status, count(*) from {TABLE} group by import_status")).all())

    return {
        "items": [{
            "id": r["source_voucher_id"], "voucher_number": r["voucher_number"], "voucher_date": r["voucher_date"],
            "voucher_type": r["voucher_type"], "party": r["customer_name"],
            "debit_total": float(r["debit_total"] or 0), "credit_total": float(r["credit_total"] or 0),
            "reference_number": r["reference_number"], "narration": r["narration"],
            "import_status": r["import_status"], "source_financial_year": r["source_financial_year"],
            "posted_receipt_id": str(r["posted_receipt_id"]) if tracked and r["posted_receipt_id"] else None,
            "posted_receipt_number": r["posted_receipt_number"] if tracked else None,
            "import_note": r["import_note"] if tracked else None,
        } for r in rows],
        "total": total, "page": page, "page_size": page_size,
        "filtered_amount": float(amount),
        "all_count": sum(t[1] for t in types), "all_amount": float(sum(t[2] for t in types)),
        "types": [{"voucher_type": t[0], "count": t[1], "amount": float(t[2]), "from": t[3], "to": t[4]} for t in types],
        "statuses": statuses,
        "posted_count": posted_count, "posted_amount": float(posted_amount),
    }
