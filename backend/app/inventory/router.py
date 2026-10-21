"""
Inventory module REST API.

Every endpoint declares its own permission (spec section 21 rule 13) and
every list endpoint paginates server-side (section 18). Company scoping is
applied from the caller's active company rather than trusted from the client.
"""

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import require_permission
from app.companies.models import Company
from app.core.database import get_db
from app.inventory import coding
from app.inventory import images
from app.inventory import models as m
from app.inventory import stock
from app.inventory import schemas as s
from app.users.models import User

router = APIRouter(prefix="/inventory", tags=["inventory"])


def active_company_id(db: Session) -> uuid.UUID:
    """The caller's working company.

    REQUIRES BUSINESS CONFIRMATION: how a user switches company when they
    have access to several. Until the company selector is specified, this
    resolves to the single seeded company.
    """
    company = db.scalar(select(Company).order_by(Company.created_at).limit(1))
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No company exists yet. Run the seed command first.",
        )
    return company.id


def paged(db: Session, stmt, page: int, page_size: int) -> tuple[list[Any], int]:
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return list(rows), total


# =====================================================================
# Item Racks
# =====================================================================
def _rack_item_counts(db: Session, rack_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """How many products sit on each rack, for the racks on this page only —
    one grouped query rather than a count per row."""
    if not rack_ids:
        return {}
    rows = db.execute(
        select(m.InventoryItem.rack_id, func.count())
        .where(m.InventoryItem.rack_id.in_(rack_ids))
        .group_by(m.InventoryItem.rack_id)
    ).all()
    return {rack_id: count for rack_id, count in rows}


@router.get("/racks")
def list_racks(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.racks.view")),
):
    stmt = select(m.ItemRack).where(m.ItemRack.company_id == active_company_id(db))
    if search:
        stmt = stmt.where(m.ItemRack.rack_name.ilike(f"%{search}%"))
    stmt = stmt.order_by(m.ItemRack.rack_name)
    rows, total = paged(db, stmt, page, page_size)
    counts = _rack_item_counts(db, [r.id for r in rows])
    return {
        "items": [
            {"id": str(r.id), "rack_name": r.rack_name, "is_active": r.is_active,
             "item_count": counts.get(r.id, 0), "created_at": r.created_at}
            for r in rows
        ],
        "total": total, "page": page, "page_size": page_size,
    }


@router.get("/racks/{rack_id}/items")
def list_rack_items(
    rack_id: uuid.UUID,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.view")),
):
    """The products stored on one rack — the drill-down behind the item count
    in the rack listing. Requires the items permission, not the rack one,
    because what it returns is item data."""
    company_id = active_company_id(db)
    rack = db.scalar(
        select(m.ItemRack).where(
            m.ItemRack.id == rack_id, m.ItemRack.company_id == company_id
        )
    )
    if not rack:
        raise HTTPException(404, "Rack not found.")

    stmt = select(m.InventoryItem).where(
        m.InventoryItem.company_id == company_id,
        m.InventoryItem.rack_id == rack_id,
    )
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            m.InventoryItem.item_code.ilike(like),
            m.InventoryItem.description.ilike(like),
        ))
    stmt = stmt.order_by(m.InventoryItem.item_code)
    rows, total = paged(db, stmt, page, page_size)
    return {
        "rack_name": rack.rack_name,
        "items": [
            {"id": str(i.id), "item_code": i.item_code, "description": i.description,
             "uom": i.uom, "item_status": i.item_status}
            for i in rows
        ],
        "total": total, "page": page, "page_size": page_size,
    }


@router.post("/racks", status_code=status.HTTP_201_CREATED)
def create_rack(
    payload: s.ItemRackIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.racks.create")),
):
    company_id = active_company_id(db)
    existing = db.scalar(
        select(m.ItemRack).where(
            m.ItemRack.company_id == company_id, m.ItemRack.rack_name == payload.rack_name
        )
    )
    if existing:
        raise HTTPException(400, f"Rack '{payload.rack_name}' already exists.")
    rack = m.ItemRack(company_id=company_id, created_by=user.id, **payload.model_dump())
    db.add(rack)
    db.commit()
    db.refresh(rack)
    return {"id": str(rack.id), "rack_name": rack.rack_name, "is_active": rack.is_active}


@router.put("/racks/{rack_id}")
def update_rack(
    rack_id: uuid.UUID,
    payload: s.ItemRackIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.racks.edit")),
):
    rack = db.get(m.ItemRack, rack_id)
    if not rack:
        raise HTTPException(404, "Rack not found.")
    for key, value in payload.model_dump().items():
        setattr(rack, key, value)
    rack.updated_by = user.id
    db.commit()
    return {"id": str(rack.id), "rack_name": rack.rack_name, "is_active": rack.is_active}


@router.delete("/racks/{rack_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rack(
    rack_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.racks.delete")),
):
    rack = db.get(m.ItemRack, rack_id)
    if not rack:
        raise HTTPException(404, "Rack not found.")
    in_use = db.scalar(select(func.count()).select_from(m.InventoryItem).where(
        m.InventoryItem.rack_id == rack_id))
    if in_use:
        raise HTTPException(400, f"Cannot delete: {in_use} item(s) are assigned to this rack.")
    db.delete(rack)
    db.commit()


# =====================================================================
# Item Locations
# =====================================================================
@router.get("/locations")
def list_locations(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.locations.view")),
):
    stmt = select(m.ItemLocation).where(m.ItemLocation.company_id == active_company_id(db))
    if search:
        stmt = stmt.where(m.ItemLocation.location.ilike(f"%{search}%"))
    stmt = stmt.order_by(m.ItemLocation.location)
    rows, total = paged(db, stmt, page, page_size)
    return {
        "items": [
            {"id": str(r.id), "location": r.location, "is_active": r.is_active,
             "created_at": r.created_at}
            for r in rows
        ],
        "total": total, "page": page, "page_size": page_size,
    }


@router.post("/locations", status_code=status.HTTP_201_CREATED)
def create_location(
    payload: s.ItemLocationIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.locations.create")),
):
    loc = m.ItemLocation(company_id=active_company_id(db), created_by=user.id, **payload.model_dump())
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return {"id": str(loc.id), "location": loc.location, "is_active": loc.is_active}


@router.put("/locations/{location_id}")
def update_location(
    location_id: uuid.UUID,
    payload: s.ItemLocationIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.locations.edit")),
):
    loc = db.get(m.ItemLocation, location_id)
    if not loc:
        raise HTTPException(404, "Location not found.")
    for key, value in payload.model_dump().items():
        setattr(loc, key, value)
    loc.updated_by = user.id
    db.commit()
    return {"id": str(loc.id), "location": loc.location, "is_active": loc.is_active}


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(
    location_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.locations.delete")),
):
    loc = db.get(m.ItemLocation, location_id)
    if not loc:
        raise HTTPException(404, "Location not found.")
    db.delete(loc)
    db.commit()


# =====================================================================
# Main Products
# =====================================================================
@router.get("/main-products")
def list_main_products(
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.main_products.view")),
):
    stmt = select(m.MainProduct).where(m.MainProduct.company_id == active_company_id(db))
    if search:
        stmt = stmt.where(m.MainProduct.description.ilike(f"%{search}%"))
    stmt = stmt.order_by(m.MainProduct.description)
    rows, total = paged(db, stmt, page, page_size)
    return {
        "items": [
            {"id": str(r.id), "description": r.description, "remarks": r.remarks,
             "is_active": r.is_active, "created_at": r.created_at}
            for r in rows
        ],
        "total": total, "page": page, "page_size": page_size,
    }


@router.post("/main-products", status_code=status.HTTP_201_CREATED)
def create_main_product(
    payload: s.MainProductIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.main_products.create")),
):
    company_id = active_company_id(db)
    if db.scalar(select(m.MainProduct).where(
        m.MainProduct.company_id == company_id,
        m.MainProduct.description == payload.description,
    )):
        raise HTTPException(400, f"Main product '{payload.description}' already exists.")
    mp = m.MainProduct(company_id=company_id, created_by=user.id, **payload.model_dump())
    db.add(mp)
    db.commit()
    db.refresh(mp)
    return {"id": str(mp.id), "description": mp.description, "remarks": mp.remarks}


@router.put("/main-products/{main_product_id}")
def update_main_product(
    main_product_id: uuid.UUID,
    payload: s.MainProductIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.main_products.edit")),
):
    mp = db.get(m.MainProduct, main_product_id)
    if not mp:
        raise HTTPException(404, "Main product not found.")
    for key, value in payload.model_dump().items():
        setattr(mp, key, value)
    mp.updated_by = user.id
    db.commit()
    return {"id": str(mp.id), "description": mp.description, "remarks": mp.remarks}


@router.delete("/main-products/{main_product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_main_product(
    main_product_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.main_products.delete")),
):
    mp = db.get(m.MainProduct, main_product_id)
    if not mp:
        raise HTTPException(404, "Main product not found.")
    children = db.scalar(select(func.count()).select_from(m.InventorySubCategory).where(
        m.InventorySubCategory.main_product_id == main_product_id))
    if children:
        raise HTTPException(400, f"Cannot delete: {children} sub-categories belong to this main product.")
    db.delete(mp)
    db.commit()


# =====================================================================
# Inventory Sub Categories
# =====================================================================
@router.get("/sub-categories")
def list_sub_categories(
    search: str | None = None,
    main_product_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.sub_categories.view")),
):
    stmt = (
        select(m.InventorySubCategory)
        .options(selectinload(m.InventorySubCategory.main_product))
        .where(m.InventorySubCategory.company_id == active_company_id(db))
    )
    if main_product_id:
        stmt = stmt.where(m.InventorySubCategory.main_product_id == main_product_id)
    if search:
        stmt = stmt.where(or_(
            m.InventorySubCategory.description.ilike(f"%{search}%"),
            m.InventorySubCategory.sub_code.ilike(f"%{search}%"),
        ))
    stmt = stmt.order_by(m.InventorySubCategory.sub_code)
    rows, total = paged(db, stmt, page, page_size)
    return {
        "items": [
            {
                "id": str(r.id),
                "main_product_id": str(r.main_product_id),
                "main_product_name": r.main_product.description if r.main_product else None,
                "sub_code": r.sub_code,
                "description": r.description,
                "remarks": r.remarks,
                "detailcode_purchase_local": r.detailcode_purchase_local,
                "detailcode_purchase_import": r.detailcode_purchase_import,
                "is_active": r.is_active,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "total": total, "page": page, "page_size": page_size,
    }


@router.post("/sub-categories", status_code=status.HTTP_201_CREATED)
def create_sub_category(
    payload: s.SubCategoryIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.sub_categories.create")),
):
    company_id = active_company_id(db)
    if not db.get(m.MainProduct, uuid.UUID(payload.main_product_id)):
        raise HTTPException(400, "Selected main product does not exist.")
    if payload.sub_code and db.scalar(select(m.InventorySubCategory).where(
        m.InventorySubCategory.company_id == company_id,
        m.InventorySubCategory.sub_code == payload.sub_code,
    )):
        raise HTTPException(400, f"Sub code '{payload.sub_code}' is already in use.")

    data = payload.model_dump()
    data["main_product_id"] = uuid.UUID(data["main_product_id"])
    sc = m.InventorySubCategory(company_id=company_id, created_by=user.id, **data)
    db.add(sc)
    db.commit()
    db.refresh(sc)
    return {"id": str(sc.id), "description": sc.description, "sub_code": sc.sub_code}


@router.put("/sub-categories/{sub_category_id}")
def update_sub_category(
    sub_category_id: uuid.UUID,
    payload: s.SubCategoryIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.sub_categories.edit")),
):
    sc = db.get(m.InventorySubCategory, sub_category_id)
    if not sc:
        raise HTTPException(404, "Sub category not found.")
    data = payload.model_dump()
    data["main_product_id"] = uuid.UUID(data["main_product_id"])
    for key, value in data.items():
        setattr(sc, key, value)
    sc.updated_by = user.id
    db.commit()
    return {"id": str(sc.id), "description": sc.description, "sub_code": sc.sub_code}


@router.delete("/sub-categories/{sub_category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sub_category(
    sub_category_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.sub_categories.delete")),
):
    sc = db.get(m.InventorySubCategory, sub_category_id)
    if not sc:
        raise HTTPException(404, "Sub category not found.")
    children = db.scalar(select(func.count()).select_from(m.InventorySubDetailCategory).where(
        m.InventorySubDetailCategory.sub_category_id == sub_category_id))
    if children:
        raise HTTPException(400, f"Cannot delete: {children} detail categories belong to this sub category.")
    db.delete(sc)
    db.commit()


# =====================================================================
# Inventory Sub Detail Categories
# =====================================================================
@router.get("/sub-detail-categories")
def list_sub_detail_categories(
    search: str | None = None,
    main_product_id: uuid.UUID | None = None,
    sub_category_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.sub_detail_categories.view")),
):
    SC = m.InventorySubCategory
    MP = m.MainProduct
    stmt = (
        select(m.InventorySubDetailCategory)
        .where(m.InventorySubDetailCategory.company_id == active_company_id(db))
    )
    if main_product_id:
        stmt = stmt.where(m.InventorySubDetailCategory.main_product_id == main_product_id)
    if sub_category_id:
        stmt = stmt.where(m.InventorySubDetailCategory.sub_category_id == sub_category_id)
    if search:
        stmt = stmt.where(m.InventorySubDetailCategory.description.ilike(f"%{search}%"))
    stmt = stmt.order_by(m.InventorySubDetailCategory.description)
    rows, total = paged(db, stmt, page, page_size)

    mp_names = dict(db.execute(select(MP.id, MP.description)).all())
    sc_names = dict(db.execute(select(SC.id, SC.description)).all())

    return {
        "items": [
            {
                "id": str(r.id),
                "main_product_id": str(r.main_product_id),
                "main_product_name": mp_names.get(r.main_product_id),
                "sub_category_id": str(r.sub_category_id),
                "sub_category_name": sc_names.get(r.sub_category_id),
                "description": r.description,
                "remarks": r.remarks,
                "is_active": r.is_active,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        "total": total, "page": page, "page_size": page_size,
    }


@router.post("/sub-detail-categories", status_code=status.HTTP_201_CREATED)
def create_sub_detail_category(
    payload: s.SubDetailCategoryIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.sub_detail_categories.create")),
):
    sub = db.get(m.InventorySubCategory, uuid.UUID(payload.sub_category_id))
    if not sub:
        raise HTTPException(400, "Selected sub category does not exist.")
    if str(sub.main_product_id) != payload.main_product_id:
        raise HTTPException(400, "The sub category does not belong to the selected main product.")

    data = payload.model_dump()
    data["main_product_id"] = uuid.UUID(data["main_product_id"])
    data["sub_category_id"] = uuid.UUID(data["sub_category_id"])
    sdc = m.InventorySubDetailCategory(
        company_id=active_company_id(db), created_by=user.id, **data
    )
    db.add(sdc)
    db.commit()
    db.refresh(sdc)
    return {"id": str(sdc.id), "description": sdc.description}


@router.put("/sub-detail-categories/{detail_id}")
def update_sub_detail_category(
    detail_id: uuid.UUID,
    payload: s.SubDetailCategoryIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.sub_detail_categories.edit")),
):
    sdc = db.get(m.InventorySubDetailCategory, detail_id)
    if not sdc:
        raise HTTPException(404, "Detail category not found.")
    data = payload.model_dump()
    data["main_product_id"] = uuid.UUID(data["main_product_id"])
    data["sub_category_id"] = uuid.UUID(data["sub_category_id"])
    for key, value in data.items():
        setattr(sdc, key, value)
    sdc.updated_by = user.id
    db.commit()
    return {"id": str(sdc.id), "description": sdc.description}


@router.delete("/sub-detail-categories/{detail_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sub_detail_category(
    detail_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.sub_detail_categories.delete")),
):
    sdc = db.get(m.InventorySubDetailCategory, detail_id)
    if not sdc:
        raise HTTPException(404, "Detail category not found.")
    db.delete(sdc)
    db.commit()


# =====================================================================
# Product Details (items)
# =====================================================================
def _ledger_balance_subquery(company_id):
    """Per-item stock from the ledger, as a subquery the item listing can join.

    Stock is the sum of its movements — opening balances included, since those
    were posted as movements too. Doing it in SQL keeps filtering and paging
    on the database rather than pulling 5,000 rows into memory to add up.
    """
    return (
        select(
            stock.StockLedgerEntry.item_id.label("item_id"),
            func.sum(case(
                (stock.StockLedgerEntry.direction == stock.IN,
                 stock.StockLedgerEntry.quantity),
                else_=-stock.StockLedgerEntry.quantity,
            )).label("quantity"),
        )
        .where(stock.StockLedgerEntry.company_id == company_id)
        .group_by(stock.StockLedgerEntry.item_id)
        .subquery()
    )


def _item_filters(
    stmt, company_id, search, main, sub, detail, rack, item_status,
    stock_from=None, stock_to=None,
):
    stmt = stmt.where(m.InventoryItem.company_id == company_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            m.InventoryItem.description.ilike(like),
            m.InventoryItem.item_code.ilike(like),
            m.InventoryItem.sku.ilike(like),
            m.InventoryItem.barcode.ilike(like),
        ))
    if main:
        stmt = stmt.where(m.InventoryItem.main_product_id.in_(main))
    if sub:
        stmt = stmt.where(m.InventoryItem.sub_category_id.in_(sub))
    if detail:
        stmt = stmt.where(m.InventoryItem.sub_detail_category_id.in_(detail))
    if rack:
        stmt = stmt.where(m.InventoryItem.rack_id.in_(rack))
    if item_status:
        stmt = stmt.where(m.InventoryItem.item_status.in_(item_status))

    # Stock quantity range, read from the ledger. COALESCE so an item with no
    # movements counts as zero, matching what the product card shows —
    # otherwise "0 to 0" would skip the very rows displaying Stock-0.
    if stock_from is not None or stock_to is not None:
        ledger = _ledger_balance_subquery(company_id)
        stmt = stmt.outerjoin(ledger, ledger.c.item_id == m.InventoryItem.id)
        if stock_from is not None:
            stmt = stmt.where(func.coalesce(ledger.c.quantity, 0) >= stock_from)
        if stock_to is not None:
            stmt = stmt.where(func.coalesce(ledger.c.quantity, 0) <= stock_to)

    return stmt


@router.get("/items")
def list_items(
    request: Request,
    search: str | None = None,
    main_category: list[uuid.UUID] = Query(default=[]),
    sub_category: list[uuid.UUID] = Query(default=[]),
    sub_detail_category: list[uuid.UUID] = Query(default=[]),
    rack: list[uuid.UUID] = Query(default=[]),
    item_status: list[str] = Query(default=[]),
    stock_from: Decimal | None = Query(None, ge=0),
    stock_to: Decimal | None = Query(None, ge=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.view")),
):
    if stock_from is not None and stock_to is not None and stock_to < stock_from:
        raise HTTPException(
            400, "The 'to' quantity cannot be lower than the 'from' quantity.")

    company_id = active_company_id(db)
    stmt = _item_filters(
        select(m.InventoryItem), company_id, search,
        main_category, sub_category, sub_detail_category, rack, item_status,
        stock_from, stock_to,
    ).order_by(m.InventoryItem.item_code)

    rows, total = paged(db, stmt, page, page_size)

    mp = dict(db.execute(select(m.MainProduct.id, m.MainProduct.description)).all())
    sc = dict(db.execute(select(m.InventorySubCategory.id, m.InventorySubCategory.description)).all())
    sd = dict(db.execute(select(
        m.InventorySubDetailCategory.id, m.InventorySubDetailCategory.description)).all())
    rk = dict(db.execute(select(m.ItemRack.id, m.ItemRack.rack_name)).all())
    lc = dict(db.execute(select(m.ItemLocation.id, m.ItemLocation.location)).all())
    balances = stock.stock_balances(db, company_id)

    return {
        "items": [
            {
                "id": str(r.id),
                "item_code": r.item_code,
                "description": r.description,
                "uom": r.uom,
                "sku": r.sku,
                "barcode": r.barcode,
                "item_status": r.item_status,
                "price": float(r.price) if r.price is not None else None,
                "currency": r.currency,
                # What the card shows. From the ledger, so it agrees with the
                # Product Stock report rather than being a frozen import value.
                "opening_stock": float(balances.get(r.id, 0)),
                "image_path": r.image_path,
                "image_url": images.image_url(request, r.image_path),
                "main_product_name": mp.get(r.main_product_id),
                "sub_category_name": sc.get(r.sub_category_id),
                "sub_detail_category_name": sd.get(r.sub_detail_category_id),
                "rack_name": rk.get(r.rack_id),
                "location_name": lc.get(r.location_id),
                # The ids the edit form needs to preselect its dropdowns.
                # Without them the form opens blank and refuses to save until
                # every category is chosen again.
                "main_product_id": str(r.main_product_id) if r.main_product_id else None,
                "sub_category_id": str(r.sub_category_id) if r.sub_category_id else None,
                "sub_detail_category_id": (
                    str(r.sub_detail_category_id) if r.sub_detail_category_id else None),
                "rack_id": str(r.rack_id) if r.rack_id else None,
                "location_id": str(r.location_id) if r.location_id else None,
            }
            for r in rows
        ],
        "total": total, "page": page, "page_size": page_size,
    }


@router.get("/items/facets", response_model=s.ItemFacets)
def item_facets(
    search: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.view")),
):
    """Counts per filter value, for the left-hand panel on Product Details."""
    company_id = active_company_id(db)
    II = m.InventoryItem

    def bucket(id_col, label_col, join_model, join_cond):
        stmt = (
            select(id_col, label_col, func.count(II.id))
            .select_from(II)
            .join(join_model, join_cond)
            .where(II.company_id == company_id)
        )
        if search:
            stmt = stmt.where(II.description.ilike(f"%{search}%"))
        stmt = stmt.group_by(id_col, label_col).order_by(func.count(II.id).desc())
        return [
            s.FacetBucket(id=str(i), label=lbl, count=c)
            for i, lbl, c in db.execute(stmt).all()
        ]

    status_rows = db.execute(
        select(II.item_status, func.count(II.id))
        .where(II.company_id == company_id)
        .group_by(II.item_status)
    ).all()

    return s.ItemFacets(
        main_categories=bucket(
            m.MainProduct.id, m.MainProduct.description,
            m.MainProduct, II.main_product_id == m.MainProduct.id),
        sub_categories=bucket(
            m.InventorySubCategory.id, m.InventorySubCategory.description,
            m.InventorySubCategory, II.sub_category_id == m.InventorySubCategory.id),
        sub_detail_categories=bucket(
            m.InventorySubDetailCategory.id, m.InventorySubDetailCategory.description,
            m.InventorySubDetailCategory,
            II.sub_detail_category_id == m.InventorySubDetailCategory.id),
        racks=bucket(
            m.ItemRack.id, m.ItemRack.rack_name,
            m.ItemRack, II.rack_id == m.ItemRack.id),
        item_statuses=[
            s.FacetBucket(id=st, label=st, count=c) for st, c in status_rows
        ],
    )


@router.get("/items/next-code")
def preview_item_code(
    sub_category_id: str = Query(...),
    sub_detail_category_id: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission("inventory.items.view")),
):
    """What the next product in these categories will be called.

    A preview for the form. The code is allocated again when the product is
    actually created, so nothing is reserved by looking.
    """
    try:
        code = coding.next_item_code(
            db, active_company_id(db), sub_category_id, sub_detail_category_id)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    return {"item_code": code}


@router.post("/items", status_code=status.HTTP_201_CREATED)
def create_item(
    payload: s.ItemIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.create")),
):
    company_id = active_company_id(db)
    if not payload.sub_category_id:
        raise HTTPException(400, "Choose a Product Sub Category — the product "
                                 "code is built from it.")

    data = payload.model_dump()
    # The code is the system's to give, never the caller's: whatever arrived
    # in the payload is dropped so a hand-typed number cannot land outside
    # the scheme or on top of an existing product.
    data.pop("item_code", None)
    conversions = data.pop("uom_conversions", [])
    for key in ("main_product_id", "sub_category_id", "sub_detail_category_id",
                "rack_id", "location_id"):
        data[key] = uuid.UUID(data[key]) if data.get(key) else None

    # Two people saving at the same moment would compute the same next code;
    # the unique index catches the loser, who simply takes the next one.
    for attempt in range(5):
        try:
            code = coding.next_item_code(
                db, company_id, data["sub_category_id"], data["sub_detail_category_id"])
        except ValueError as err:
            raise HTTPException(400, str(err)) from err

        item = m.InventoryItem(
            company_id=company_id, created_by=user.id, item_code=code, **data)
        item.uom_conversions = [
            m.ItemUomConversion(uom=c["uom"], conversion_factor=c["conversion_factor"])
            for c in conversions
        ]
        db.add(item)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if attempt == 4:
                raise HTTPException(
                    409, "Could not allocate a product code — several products "
                         "are being created at once. Try again.") from None
            continue
        db.refresh(item)
        return {"id": str(item.id), "item_code": item.item_code,
                "description": item.description}


@router.put("/items/{item_id}")
def update_item(
    item_id: uuid.UUID,
    payload: s.ItemIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.edit")),
):
    item = db.get(m.InventoryItem, item_id)
    if not item:
        raise HTTPException(404, "Item not found.")

    # Only what the form sent is changed: a field it leaves out keeps its value.
    data = payload.model_dump(exclude_unset=True)
    # The code a product was created with is the one every document, barcode
    # and legacy report quotes, so editing never moves it.
    data.pop("item_code", None)
    # The picture changes only through its own upload / remove endpoints;
    # saving the product's details must never drop it.
    data.pop("image_path", None)
    conversions = data.pop("uom_conversions", None)
    for key in ("main_product_id", "sub_category_id", "sub_detail_category_id",
                "rack_id", "location_id"):
        data[key] = uuid.UUID(data[key]) if data.get(key) else None
    for key, value in data.items():
        setattr(item, key, value)

    if conversions is not None:
        item.uom_conversions = [
            m.ItemUomConversion(uom=c["uom"], conversion_factor=c["conversion_factor"])
            for c in conversions
        ]
    item.updated_by = user.id
    db.commit()
    return {"id": str(item.id), "item_code": item.item_code}


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.delete")),
):
    item = db.get(m.InventoryItem, item_id)
    if not item:
        raise HTTPException(404, "Item not found.")
    db.delete(item)
    db.commit()


# =====================================================================
# Stock adjustments
# =====================================================================
@router.post("/stock/adjustments", status_code=status.HTTP_201_CREATED)
def create_stock_adjustment(
    payload: s.StockAdjustmentIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.edit")),
):
    """Add or remove stock at a location by hand.

    Written as a ledger movement, not as an edit to a balance: stock is the
    sum of its movements, so a correction has to be a movement too. Taking
    stock out is refused when the location does not hold that much, because a
    negative balance is a data-entry mistake rather than a fact about a
    warehouse.
    """
    company_id = active_company_id(db)

    item = db.scalar(select(m.InventoryItem).where(
        m.InventoryItem.id == uuid.UUID(payload.item_id),
        m.InventoryItem.company_id == company_id))
    if item is None:
        raise HTTPException(404, "Product not found.")

    location = None
    if payload.location_id:
        location = db.scalar(select(m.ItemLocation).where(
            m.ItemLocation.id == uuid.UUID(payload.location_id),
            m.ItemLocation.company_id == company_id))
        if location is None:
            raise HTTPException(400, "Select a valid location.")

    location_id = location.id if location else None
    if payload.direction == stock.OUT:
        held = stock.stock_balance_at(db, company_id, item.id, location_id)
        if payload.quantity > held:
            where = f"at {location.location}" if location else "with no location"
            raise HTTPException(
                400,
                f"Cannot remove {payload.quantity:g}: only {held:g} of "
                f"{item.item_code} is held {where}.",
            )

    entry = stock.post_movement(
        db,
        company_id=company_id,
        item_id=item.id,
        direction=payload.direction,
        quantity=payload.quantity,
        source_type="adjustment",
        source_number=None,
        entry_date=payload.entry_date,
        user_id=user.id,
        location_id=location_id,
        remarks=payload.remarks.strip(),
    )
    db.commit()
    db.refresh(entry)

    return {
        "id": str(entry.id),
        "item_code": item.item_code,
        "direction": entry.direction,
        "quantity": float(entry.quantity),
        "location": location.location if location else None,
        "balance_after": float(stock.stock_balance_at(db, company_id, item.id, location_id)),
        "remarks": entry.remarks,
    }


@router.post("/stock/transfers", status_code=status.HTTP_201_CREATED)
def create_stock_transfer(
    payload: s.StockTransferIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.edit")),
):
    """Move stock between locations.

    Written as a matched pair of ledger movements sharing one source id, so
    the two halves can never be separated and the company total is untouched
    — a transfer changes where stock is, not how much there is.
    """
    company_id = active_company_id(db)

    item = db.scalar(select(m.InventoryItem).where(
        m.InventoryItem.id == uuid.UUID(payload.item_id),
        m.InventoryItem.company_id == company_id))
    if item is None:
        raise HTTPException(404, "Product not found.")

    if payload.from_location_id == payload.to_location_id:
        raise HTTPException(400, "Choose two different locations.")

    def location(raw: str) -> m.ItemLocation:
        found = db.scalar(select(m.ItemLocation).where(
            m.ItemLocation.id == uuid.UUID(raw),
            m.ItemLocation.company_id == company_id))
        if found is None:
            raise HTTPException(400, "Select a valid location.")
        return found

    source = location(payload.from_location_id)
    destination = location(payload.to_location_id)

    held = stock.stock_balance_at(db, company_id, item.id, source.id)
    if payload.quantity > held:
        raise HTTPException(
            400,
            f"Cannot transfer {payload.quantity:g}: only {held:g} of "
            f"{item.item_code} is held at {source.location}.",
        )

    # One id shared by both halves, so the pair reads as a single transfer.
    transfer_id = uuid.uuid4()
    note = (payload.remarks or "").strip() or None
    for direction, where in ((stock.OUT, source), (stock.IN, destination)):
        stock.post_movement(
            db,
            company_id=company_id,
            item_id=item.id,
            direction=direction,
            quantity=payload.quantity,
            source_type="transfer",
            source_id=transfer_id,
            source_number=f"{source.location} -> {destination.location}",
            entry_date=payload.entry_date,
            user_id=user.id,
            location_id=where.id,
            remarks=note,
        )
    db.commit()

    return {
        "transfer_id": str(transfer_id),
        "item_code": item.item_code,
        "quantity": float(payload.quantity),
        "from": {"location": source.location,
                 "balance_after": float(
                     stock.stock_balance_at(db, company_id, item.id, source.id))},
        "to": {"location": destination.location,
               "balance_after": float(
                   stock.stock_balance_at(db, company_id, item.id, destination.id))},
    }


@router.post("/stock/openings", status_code=status.HTTP_201_CREATED)
def create_stock_opening(
    payload: s.StockOpeningIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.edit")),
):
    """Give a product a starting quantity at a location.

    Uses its own source type so the location import, which replaces the
    balances it loaded, never deletes an opening entered here by hand.
    """
    company_id = active_company_id(db)
    item = db.scalar(select(m.InventoryItem).where(
        m.InventoryItem.id == uuid.UUID(payload.item_id),
        m.InventoryItem.company_id == company_id))
    if item is None:
        raise HTTPException(404, "Product not found.")

    location_id = uuid.UUID(payload.location_id) if payload.location_id else item.location_id
    location = db.get(m.ItemLocation, location_id) if location_id else None
    if location_id and (location is None or location.company_id != company_id):
        raise HTTPException(400, "Select a valid location.")

    entry = stock.post_movement(
        db,
        company_id=company_id,
        item_id=item.id,
        direction=stock.IN,
        quantity=payload.quantity,
        source_type="opening",
        source_number="Opening",
        entry_date=payload.entry_date,
        user_id=user.id,
        location_id=location_id,
        remarks=(payload.remarks or "").strip() or "Opening quantity",
    )
    # File the product where its stock was entered, if it has no location yet.
    if item.location_id is None and location_id:
        item.location_id = location_id
    db.commit()
    db.refresh(entry)

    return {
        "id": str(entry.id),
        "item_code": item.item_code,
        "quantity": float(entry.quantity),
        "location": location.location if location else None,
        "balance_after": float(
            stock.stock_balance_at(db, company_id, item.id, location_id)),
    }


@router.put("/items/{item_id}/price")
def set_item_price(
    item_id: uuid.UUID,
    payload: s.ItemPriceIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.edit")),
):
    """Set the price on a product without reopening the whole item form."""
    item = _owned_item(db, item_id)
    item.price = payload.price
    if payload.currency:
        item.currency = payload.currency.strip().upper()
    item.updated_by = user.id
    db.commit()
    return {
        "id": str(item.id), "item_code": item.item_code,
        "price": float(item.price), "currency": item.currency,
    }


@router.get("/items/{item_id}/transactions")
def item_transactions(
    item_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.view")),
):
    """Everything that has moved this product, newest first.

    The ledger is the whole history, so this answers "why is the stock what it
    is" without anyone having to open the documents one by one.
    """
    item = _owned_item(db, item_id)

    rows = db.execute(
        select(stock.StockLedgerEntry, m.ItemLocation.location)
        .outerjoin(m.ItemLocation, m.ItemLocation.id == stock.StockLedgerEntry.location_id)
        .where(stock.StockLedgerEntry.item_id == item.id)
        .order_by(stock.StockLedgerEntry.entry_date.desc(),
                  stock.StockLedgerEntry.id.desc())
        .limit(limit)
    ).all()

    return {
        "item_code": item.item_code,
        "description": item.description,
        "uom": item.uom,
        "balance": float(stock.stock_balances(db, active_company_id(db)).get(item.id, 0)),
        "items": [
            {
                "id": str(entry.id),
                "entry_date": entry.entry_date,
                "direction": entry.direction,
                "quantity": float(entry.quantity),
                "source_type": entry.source_type,
                "source_number": entry.source_number,
                "location": location,
                "remarks": entry.remarks,
            }
            for entry, location in rows
        ],
    }


# ---------- Item image ----------
def _owned_item(db: Session, item_id: uuid.UUID) -> m.InventoryItem:
    item = db.scalar(
        select(m.InventoryItem).where(
            m.InventoryItem.id == item_id,
            m.InventoryItem.company_id == active_company_id(db),
        )
    )
    if not item:
        raise HTTPException(404, "Item not found.")
    return item


@router.post("/items/{item_id}/image")
def upload_item_image(
    item_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.edit")),
):
    """Attach a picture to a product, replacing any existing one.

    A new product is created first and its image uploaded second — the file
    needs somewhere to belong before it can be stored.
    """
    item = _owned_item(db, item_id)
    item.image_path = images.save_item_image(file, item.id)
    item.updated_by = user.id
    db.commit()
    return {
        "id": str(item.id),
        "image_path": item.image_path,
        "image_url": images.image_url(request, item.image_path),
    }


@router.delete("/items/{item_id}/image", status_code=status.HTTP_204_NO_CONTENT)
def remove_item_image(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.edit")),
):
    item = _owned_item(db, item_id)
    images.delete_item_image(item.id)
    item.image_path = None
    item.updated_by = user.id
    db.commit()


# ---------------------------------------------------------- units of measure

@router.get("/uoms")
def list_uoms(
    search: str | None = None,
    include_inactive: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=5000),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.view")),
):
    """The units goods are counted in.

    Read by every form that asks for a UOM, so the page size is generous:
    a picker that silently omits the unit being looked for is worse than no
    picker. Searching matches the code and the description, because someone
    types "kilo" as readily as "KG".
    """
    stmt = select(m.UnitOfMeasure).where(
        m.UnitOfMeasure.company_id == active_company_id(db))
    if not include_inactive:
        stmt = stmt.where(m.UnitOfMeasure.is_active.is_(True))
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(or_(
            m.UnitOfMeasure.code.ilike(like),
            m.UnitOfMeasure.description.ilike(like),
            m.UnitOfMeasure.category.ilike(like),
        ))
    stmt = stmt.order_by(m.UnitOfMeasure.sort_order, m.UnitOfMeasure.code)
    rows, total = paged(db, stmt, page, page_size)
    return {
        "items": [
            {
                "id": str(r.id),
                "code": r.code,
                "description": r.description,
                "category": r.category,
                "base_uom_code": r.base_uom_code,
                "conversion_to_base": (float(r.conversion_to_base)
                                       if r.conversion_to_base is not None else None),
                "decimal_places": r.decimal_places,
                "is_active": r.is_active,
                "sort_order": r.sort_order,
            }
            for r in rows
        ],
        "total": total, "page": page, "page_size": page_size,
    }


@router.post("/uoms", status_code=status.HTTP_201_CREATED)
def create_uom(
    payload: s.UomIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.create")),
):
    company_id = active_company_id(db)
    if db.scalar(select(m.UnitOfMeasure).where(
        m.UnitOfMeasure.company_id == company_id,
        m.UnitOfMeasure.code == payload.code,
    )):
        raise HTTPException(400, f"A unit called '{payload.code}' already exists.")
    row = m.UnitOfMeasure(company_id=company_id, created_by=user.id,
                          **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": str(row.id), "code": row.code, "description": row.description}


@router.put("/uoms/{uom_id}")
def update_uom(
    uom_id: uuid.UUID,
    payload: s.UomIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.edit")),
):
    row = db.get(m.UnitOfMeasure, uom_id)
    if row is None or row.company_id != active_company_id(db):
        raise HTTPException(404, "That unit does not exist.")

    # Renaming a code would orphan every document already written in it,
    # because the documents hold the text and not a reference.
    if payload.code != row.code:
        in_use = db.scalar(
            select(func.count()).select_from(m.InventoryItem)
            .where(m.InventoryItem.company_id == row.company_id,
                   func.upper(func.trim(m.InventoryItem.uom)) == row.code)
        ) or 0
        if in_use:
            raise HTTPException(
                400,
                f"{in_use:,} product(s) are measured in {row.code}, so its code "
                "cannot be changed — the documents hold the text, not a link. "
                "Retire this unit and add the new one instead.")

    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    row.updated_by = user.id
    db.commit()
    return {"id": str(row.id), "code": row.code}


@router.delete("/uoms/{uom_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_uom(
    uom_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.items.delete")),
):
    """Remove a unit nothing is measured in; retire it otherwise.

    Deleting a unit in use would leave products reading in a unit the picker
    no longer offers, so the count is checked and the caller is pointed at
    the Active switch instead.
    """
    row = db.get(m.UnitOfMeasure, uom_id)
    if row is None or row.company_id != active_company_id(db):
        raise HTTPException(404, "That unit does not exist.")

    in_use = db.scalar(
        select(func.count()).select_from(m.InventoryItem)
        .where(m.InventoryItem.company_id == row.company_id,
               func.upper(func.trim(m.InventoryItem.uom)) == row.code)
    ) or 0
    if in_use:
        raise HTTPException(
            400,
            f"{in_use:,} product(s) are measured in {row.code}. Turn Active off to "
            "take it out of the pickers while the existing products keep reading "
            "correctly.")

    db.delete(row)
    db.commit()
