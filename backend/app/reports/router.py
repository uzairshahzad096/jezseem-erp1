"""
Inventory and procurement reports: Product Stock, Product Sales, and
Import Landed Costing.

Both read from the stock ledger and the sales documents rather than from any
cached figure, so a report always agrees with the transactions behind it.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.inventory import stock
from app.inventory.models import ItemLocation
from sqlalchemy import false as sa_false
from app.inventory.models import InventoryItem, InventorySubCategory, MainProduct
from app.inventory.router import active_company_id
from app.partners.models import BusinessPartner
from app.reports import landed_costing, movement, valuation
from app.sales.models import SALES_ORDER, SalesDocument, SalesDocumentLine
from app.users.models import User

router = APIRouter(prefix="/reports", tags=["reports"])


def stock_analysis(db: Session, company_id: uuid.UUID, *, search=None, main_product_id=None,
                   sub_category_id=None, location_id=None, stock_status=None, movement_filter=None,
                   restock_only=False, period="fy", date_from=None, date_to=None, repeat_min=3,
                   dead_days=365, restock_percent=40.0, cover_months=2.0) -> tuple[movement.Settings, list[dict], dict]:
    """The Product Stock report's rows and summary, shared by the screen and
    every download so they always agree. Stock is the ledger balance;
    sales are posted sales orders (see app.reports.movement)."""
    start, end, label = movement.resolve_period(db, company_id, period, date_from, date_to)
    cfg = movement.Settings(period_from=start, period_to=end, period_label=label, repeat_min=repeat_min,
                            dead_days=dead_days, restock_percent=restock_percent, cover_months=cover_months)
    rows = movement.analyse(db, company_id, cfg, search=search, main_product_id=main_product_id,
                            sub_category_id=sub_category_id, location_id=location_id)
    # The summary describes the whole selection before the quick filters, so
    # the tiles keep their counts while a tile is used as a filter.
    totals = movement.summary(rows)
    if stock_status == "in_stock":
        rows = [r for r in rows if r["quantity"] > 0]
    elif stock_status == "out_of_stock":
        rows = [r for r in rows if r["quantity"] <= 0]
    elif stock_status == "below_reorder":
        rows = [r for r in rows if r["below_reorder"]]
    if movement_filter:
        rows = [r for r in rows if r["movement"] == movement_filter]
    if restock_only:
        rows = [r for r in rows if r["restock"]]
    return cfg, rows, totals


ANALYSIS_PARAMS = dict(
    period=Query("fy", pattern="^(fy|calendar|last12|custom)$"),
    repeat_min=Query(3, ge=2, le=50),
    dead_days=Query(365, ge=30, le=3650),
    restock_percent=Query(40.0, ge=0, le=100),
    cover_months=Query(2.0, ge=0.5, le=24),
)


@router.get("/product-stock")
def product_stock_report(
    search: str | None = None,
    main_product_id: uuid.UUID | None = None,
    sub_category_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    stock_status: str | None = Query(None, pattern="^(in_stock|out_of_stock|below_reorder)$"),
    movement_filter: str | None = Query(None, alias="movement", pattern="^(REPEAT|OCCASIONAL|SLOW|DEAD|INACTIVE)$"),
    restock: bool = False,
    period: str = ANALYSIS_PARAMS["period"],
    date_from: date | None = None,
    date_to: date | None = None,
    repeat_min: int = ANALYSIS_PARAMS["repeat_min"],
    dead_days: int = ANALYSIS_PARAMS["dead_days"],
    restock_percent: float = ANALYSIS_PARAMS["restock_percent"],
    cover_months: float = ANALYSIS_PARAMS["cover_months"],
    sort: str = "item_code",
    direction: str = "asc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.reports.view")),
):
    company_id = active_company_id(db)
    cfg, rows, totals = stock_analysis(
        db, company_id, search=search, main_product_id=main_product_id, sub_category_id=sub_category_id,
        location_id=location_id, stock_status=stock_status, movement_filter=movement_filter,
        restock_only=restock, period=period, date_from=date_from, date_to=date_to, repeat_min=repeat_min,
        dead_days=dead_days, restock_percent=restock_percent, cover_months=cover_months)

    reverse = direction == "desc"
    if sort == "restock_priority":
        # Most urgent first: priority, then how often it sells, then how much to order.
        rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, None: 3}
        rows.sort(key=lambda r: (rank[r["restock_priority"]], -r["orders_in_period"],
                                 -r["suggested_restock_qty"]), reverse=reverse)
    elif sort == "movement":
        order = {m: n for n, m in enumerate(movement.MOVEMENTS)}
        rows.sort(key=lambda r: (order[r["movement"]], -r["orders_in_period"]), reverse=reverse)
    else:
        rows.sort(key=lambda r: (r.get(sort) is None, r.get(sort)), reverse=reverse)

    total = len(rows)
    start = (page - 1) * page_size
    return {"items": rows[start:start + page_size], "total": total,
            "page": page, "page_size": page_size,
            "period": {"from": cfg.period_from, "to": cfg.period_to, "label": cfg.period_label},
            "settings": {"repeat_min": cfg.repeat_min, "dead_days": cfg.dead_days,
                         "restock_percent": cfg.restock_percent, "cover_months": cfg.cover_months},
            "summary": {k: v for k, v in totals.items() if k != "top_repeat"}}


@router.get("/product-stock/workbook")
def product_stock_workbook(
    search: str | None = None,
    main_product_id: uuid.UUID | None = None,
    sub_category_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    period: str = ANALYSIS_PARAMS["period"],
    date_from: date | None = None,
    date_to: date | None = None,
    repeat_min: int = ANALYSIS_PARAMS["repeat_min"],
    dead_days: int = ANALYSIS_PARAMS["dead_days"],
    restock_percent: float = ANALYSIS_PARAMS["restock_percent"],
    cover_months: float = ANALYSIS_PARAMS["cover_months"],
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.reports.export")),
):
    """The whole analysis as one styled Excel workbook: Summary, Restock
    list, Repeat sellers, Dead stock and All products."""
    from fastapi import Response
    from app.companies.models import Company
    from app.reports.stock_workbook import build_workbook
    company_id = active_company_id(db)
    cfg, rows, totals = stock_analysis(
        db, company_id, search=search, main_product_id=main_product_id, sub_category_id=sub_category_id,
        location_id=location_id, period=period, date_from=date_from, date_to=date_to, repeat_min=repeat_min,
        dead_days=dead_days, restock_percent=restock_percent, cover_months=cover_months)
    company = db.get(Company, company_id)
    content = build_workbook(company.name, cfg, rows, totals)
    filename = f"stock-movement-{date.today():%Y%m%d}.xlsx"
    return Response(content=content,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/product-sales/customers")
def product_sales_customers(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.reports.view")),
):
    """The customers the report can show: those with at least one sales order line, by name."""
    from app.partners.models import BusinessPartner
    rows = db.execute(
        select(BusinessPartner.id, BusinessPartner.name)
        .where(BusinessPartner.id.in_(
            select(SalesDocument.customer_id)
            .join(SalesDocumentLine, SalesDocumentLine.document_id == SalesDocument.id)
            .where(SalesDocument.company_id == active_company_id(db), SalesDocument.doc_type == SALES_ORDER)))
        .order_by(func.lower(BusinessPartner.name))).all()
    return {"items": [{"id": str(i), "name": n} for i, n in rows]}


@router.get("/product-sales")
def product_sales_report(
    date_from: date | None = None,
    date_to: date | None = None,
    customer_id: uuid.UUID | None = None,
    item_id: uuid.UUID | None = None,
    main_product_id: uuid.UUID | None = None,
    status_filter: list[str] = Query(default=[], alias="status"),
    tax_status: str | None = Query(None, pattern="^(with_tax|without_tax)$"),
    sort: str = "doc_date",
    direction: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.reports.view")),
):
    company_id = active_company_id(db)
    stmt = (
        select(SalesDocument, SalesDocumentLine)
        .join(SalesDocumentLine, SalesDocumentLine.document_id == SalesDocument.id)
        .where(SalesDocument.company_id == company_id, SalesDocument.doc_type == SALES_ORDER)
    )
    if date_from:
        stmt = stmt.where(SalesDocument.doc_date >= date_from)
    if date_to:
        stmt = stmt.where(SalesDocument.doc_date <= date_to)
    if customer_id:
        stmt = stmt.where(SalesDocument.customer_id == customer_id)
    if item_id:
        stmt = stmt.where(SalesDocumentLine.item_id == item_id)
    if status_filter:
        stmt = stmt.where(SalesDocument.status.in_(status_filter))
    if tax_status == "with_tax":
        stmt = stmt.where(SalesDocument.with_sales_tax.is_(True))
    elif tax_status == "without_tax":
        stmt = stmt.where(SalesDocument.with_sales_tax.is_(False))
    if main_product_id:
        stmt = stmt.join(InventoryItem, InventoryItem.id == SalesDocumentLine.item_id).where(
            InventoryItem.main_product_id == main_product_id)

    count_stmt = stmt.with_only_columns(func.count(SalesDocumentLine.id)).order_by(None)
    total = db.scalar(count_stmt) or 0

    totals_row = db.execute(
        stmt.with_only_columns(
            func.coalesce(func.sum(SalesDocumentLine.quantity), 0),
            func.coalesce(func.sum(SalesDocumentLine.net_amount), 0),
            func.coalesce(func.sum(SalesDocumentLine.tax_amount), 0),
        ).order_by(None)
    ).first()

    order_column = {
        "doc_date": SalesDocument.doc_date,
        "doc_number": SalesDocument.doc_number,
        "description": SalesDocumentLine.description,
        "net_amount": SalesDocumentLine.net_amount,
        "taxable_amount": SalesDocumentLine.taxable_amount,
        "tax_amount": SalesDocumentLine.tax_amount,
        "quantity": SalesDocumentLine.quantity,
    }.get(sort, SalesDocument.doc_date)
    # Lines of one document keep their own order inside a sorted page, so a
    # document never appears split up or shuffled.
    stmt = stmt.order_by(
        order_column.desc() if direction == "desc" else order_column.asc(),
        SalesDocument.doc_number.desc(),
        SalesDocumentLine.line_number.asc(),
    )

    pairs = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    parties = {
        row[0]: row for row in db.execute(
            select(BusinessPartner.id, BusinessPartner.name, BusinessPartner.ntn)).all()
    }
    names = {pid: row[1] for pid, row in parties.items()}

    rows = [
        {
            "doc_id": str(doc.id),
            "doc_number": doc.doc_number,
            "doc_date": doc.doc_date,
            "customer": names.get(doc.customer_id),
            # The customer's tax number, as the printed report carries it.
            "customer_ntn": (parties.get(doc.customer_id) or (None, None, None))[2],
            "item_code": line.item_code,
            "description": line.description,
            "uom": line.uom,
            "quantity": float(line.quantity),
            "unit_price": float(line.unit_price),
            "gross_amount": float(line.gross_amount),
            "discount_amount": float(line.discount_amount),
            # What the line comes to before sales tax — the report's
            # "Excluding Tax Amount", and the figure the tax is worked out on.
            "taxable_amount": float(line.taxable_amount),
            "tax_amount": float(line.tax_amount),
            "net_amount": float(line.net_amount),
            "status": doc.status,
            "with_sales_tax": doc.with_sales_tax,
            "currency": doc.currency,
        }
        for doc, line in pairs
    ]

    return {
        "items": rows, "total": total, "page": page, "page_size": page_size,
        "totals": {
            "quantity": float(totals_row[0] or 0) if totals_row else 0,
            "net_amount": float(totals_row[1] or 0) if totals_row else 0,
            "tax_amount": float(totals_row[2] or 0) if totals_row else 0,
        },
    }


# ==================================================== import landed costing

def _landed_filters(
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
) -> dict:
    """Every filter from spec section 30, as one dependency.

    Shared by the report, its summary and its analyses so the three cannot
    drift apart — a summary computed over a different set of rows than the
    grid it sits above is worse than no summary.
    """
    return {
        "search": search, "date_from": date_from, "date_to": date_to,
        "purchase_order_id": purchase_order_id, "shipment_id": shipment_id,
        "landed_cost_id": landed_cost_id, "goods_receipt_id": goods_receipt_id,
        "supplier_id": supplier_id, "supplier_country": supplier_country,
        "country_of_origin": country_of_origin, "item_id": item_id,
        "main_product_id": main_product_id, "sub_category_id": sub_category_id,
        "hs_code": hs_code, "warehouse_id": warehouse_id, "port": port,
        "clearing_agent": clearing_agent, "currency": currency,
        "shipment_status": shipment_status, "customs_status": customs_status,
        "posted_only": posted_only,
    }


@router.get("/import-landed-costing")
def import_landed_costing_report(
    filters: dict = Depends(_landed_filters),
    sort: str = "doc_date",
    direction: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
    with_summary: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.reports.view")),
):
    """Import Landed Costing (spec sections 29 to 34).

    One row per product per costing:

        purchase + freight + insurance + customs + taxes + clearing
                 + port + bank + other = total landed cost
        total landed cost / quantity    = unit landed cost

    Posted vouchers only unless `posted_only=false`: an unposted costing has
    not touched inventory valuation, and totalling it with posted ones would
    overstate what the stock is worth.
    """
    company_id = active_company_id(db)
    rows, total = landed_costing.fetch(
        db, company_id, sort=sort, direction=direction,
        limit=page_size, offset=(page - 1) * page_size, **filters)

    payload = {"items": rows, "total": total, "page": page, "page_size": page_size,
               "components": [label for _, label in landed_costing.COMPONENTS]}
    if with_summary:
        payload["summary"] = landed_costing.summarise(db, company_id, **filters)
    return payload


@router.get("/import-landed-costing/analysis")
def import_landed_costing_analysis(
    filters: dict = Depends(_landed_filters),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.reports.view")),
):
    """The same rows grouped by supplier, country, product and shipment
    (section 33), plus where the money went by component (section 44)."""
    company_id = active_company_id(db)
    analysis = landed_costing.analyse(db, company_id, **filters)
    analysis["by_component"] = landed_costing.cost_components(db, company_id, **filters)
    analysis["summary"] = landed_costing.summarise(db, company_id, **filters)
    return analysis


@router.get("/purchase-cost-vs-landed-cost")
def purchase_cost_vs_landed_cost(
    filters: dict = Depends(_landed_filters),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.reports.view")),
):
    """What the supplier charged against what the goods actually cost
    (section 34), per product, with the difference as a percentage."""
    company_id = active_company_id(db)
    rows, _ = landed_costing.fetch(db, company_id, limit=None, **filters)
    return {
        "items": [
            {
                "item_code": row["item_code"],
                "item": row["item"],
                "uom": row["uom"],
                "quantity": row["quantity"],
                "purchase_unit_cost": row["unit_purchase_cost"],
                "additional_unit_cost": round(
                    row["unit_landed_cost"] - row["unit_purchase_cost"], 4),
                "final_unit_landed_cost": row["unit_landed_cost"],
                "additional_cost_percent": row["additional_cost_percent"],
                "landed_cost_number": row["landed_cost_number"],
                "supplier": row["supplier"],
            }
            for row in rows
        ],
        "summary": landed_costing.summarise(db, company_id, **filters),
    }


# ======================================================= inventory valuation

@router.get("/inventory-valuation")
def inventory_valuation_report(
    search: str | None = None,
    main_product_id: uuid.UUID | None = None,
    sub_category_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    source: str | None = Query(None, pattern="^(Import|Local purchase|Purchase|Opening balance)$"),
    in_stock_only: bool = True,
    costed_only: bool = False,
    sort: str = "stock_value",
    direction: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.reports.view")),
):
    """What each product cost to get into stock, and what that stock is worth.

    The cost is the weighted average of the product's costed goods receipts —
    the purchase price on a local one, the full landed cost on an import.

    Products carried over from the old ERP as opening balances have no cost
    recorded anywhere, so they are reported as unknown rather than zero. A
    zero would quietly understate the stock and is exactly the sort of figure
    that ends up in a set of accounts.
    """
    company_id = active_company_id(db)
    data = valuation.rows(
        db, company_id, search=search, main_product_id=main_product_id,
        sub_category_id=sub_category_id, location_id=location_id, source=source,
        in_stock_only=in_stock_only, costed_only=costed_only)

    # Rows that have a figure lead, sorted; the ones with no known cost follow.
    # Sorting them together would put "unknown" at the top of a descending
    # value sort, which buries every row the report exists to show.
    known = [r for r in data if r.get(sort) is not None]
    unknown = [r for r in data if r.get(sort) is None]
    known.sort(key=lambda r: r.get(sort) or 0, reverse=direction == "desc")
    data = known + unknown

    start = (page - 1) * page_size
    return {
        "items": data[start:start + page_size],
        "total": len(data),
        "page": page,
        "page_size": page_size,
        "summary": valuation.summarise(data),
    }


@router.get("/inventory-valuation/{item_id}")
def product_cost_history(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.reports.view")),
):
    """Every costed receipt for one product — how it got to its current cost.

    On an import each receipt splits into what the supplier charged and what
    the import added on top, which is the question landed costing exists to
    answer: not what was paid to the supplier, but what the thing is actually
    worth once it is on the shelf.
    """
    data = valuation.cost_history(db, active_company_id(db), item_id)
    if not data:
        raise HTTPException(404, "That product does not exist.")
    return data
