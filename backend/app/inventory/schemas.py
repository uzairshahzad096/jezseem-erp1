from decimal import Decimal
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator

_orm = ConfigDict(from_attributes=True)


# ---------- generic paged envelope ----------
class Page(BaseModel):
    """Server-side pagination envelope — spec section 18: never ship
    thousands of rows to the browser."""
    items: list
    total: int
    page: int
    page_size: int


# ---------- Item Rack ----------
class ItemRackIn(BaseModel):
    rack_name: str = Field(min_length=1, max_length=100)
    is_active: bool = True


class ItemRackOut(ItemRackIn):
    model_config = _orm
    id: str
    created_at: datetime


# ---------- Item Location ----------
class ItemLocationIn(BaseModel):
    location: str = Field(min_length=1)
    is_active: bool = True


class ItemLocationOut(ItemLocationIn):
    model_config = _orm
    id: str
    created_at: datetime


# ---------- Main Product ----------
class UomIn(BaseModel):
    """A unit of measure. The code is upper-cased so the same unit typed two
    ways cannot become two rows."""

    code: str = Field(min_length=1, max_length=30)
    description: str = Field(min_length=1, max_length=150)
    category: str | None = None
    base_uom_code: str | None = None
    conversion_to_base: Decimal | None = None
    decimal_places: int = Field(default=2, ge=0, le=6)
    is_active: bool = True
    sort_order: int = 0

    @field_validator("code", "base_uom_code")
    @classmethod
    def _upper(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else value


class MainProductIn(BaseModel):
    description: str = Field(min_length=1, max_length=150)
    remarks: str | None = None
    is_active: bool = True


class MainProductOut(MainProductIn):
    model_config = _orm
    id: str
    created_at: datetime


# ---------- Inventory Sub Category ----------
class SubCategoryIn(BaseModel):
    main_product_id: str
    sub_code: str | None = None
    description: str = Field(min_length=1, max_length=255)
    remarks: str | None = None
    detailcode_purchase_local: str | None = None
    detailcode_purchase_import: str | None = None
    detailcode_wip: str | None = None
    detailcode_finish_stock: str | None = None
    detailcode_sales_local: str | None = None
    detailcode_sales_export: str | None = None
    cos_account: str | None = None
    detailcode_consumption: str | None = None
    is_active: bool = True


class SubCategoryOut(SubCategoryIn):
    model_config = _orm
    id: str
    main_product_name: str | None = None
    created_at: datetime


# ---------- Inventory Sub Detail Category ----------
class SubDetailCategoryIn(BaseModel):
    main_product_id: str
    sub_category_id: str
    description: str = Field(min_length=1, max_length=255)
    remarks: str | None = None
    is_active: bool = True


class SubDetailCategoryOut(SubDetailCategoryIn):
    model_config = _orm
    id: str
    main_product_name: str | None = None
    sub_category_name: str | None = None
    created_at: datetime


# ---------- Item UOM conversion ----------
class UomConversionIn(BaseModel):
    uom: str
    conversion_factor: Decimal


class UomConversionOut(UomConversionIn):
    model_config = _orm
    id: str


# ---------- Inventory Item ----------
class ItemIn(BaseModel):
    # Optional on create: the server allocates the 12-digit code from the
    # chosen categories, so two people adding products at once cannot pick
    # the same number. Anything sent here is ignored on create, and on edit
    # the existing code is kept — documents, barcodes and the legacy reports
    # all quote it.
    item_code: str | None = Field(default=None, max_length=40)
    main_product_id: str | None = None
    sub_category_id: str | None = None
    sub_detail_category_id: str | None = None
    rack_id: str | None = None
    location_id: str | None = None
    description: str = Field(min_length=1)
    short_name: str | None = None
    uom: str | None = None
    market_name: str | None = None
    market_uom: str | None = None
    import_uom: str | None = None
    sku: str | None = None
    barcode: str | None = None
    item_status: str = "ACTIVE"
    currency: str | None = None
    price: Decimal | None = None
    min_level: Decimal | None = None
    max_level: Decimal | None = None
    re_order_qty: Decimal | None = None
    origin_country: str | None = None
    lead_days: int | None = None
    image_path: str | None = None
    uom_conversions: list[UomConversionIn] = []


class ItemOut(BaseModel):
    model_config = _orm
    id: str
    item_code: str
    description: str
    short_name: str | None
    uom: str | None
    sku: str | None
    barcode: str | None
    item_status: str
    currency: str | None
    price: Decimal | None
    min_level: Decimal | None
    max_level: Decimal | None
    re_order_qty: Decimal | None
    opening_stock: Decimal | None
    image_path: str | None
    main_product_id: str | None
    sub_category_id: str | None
    sub_detail_category_id: str | None
    rack_id: str | None
    main_product_name: str | None = None
    sub_category_name: str | None = None
    sub_detail_category_name: str | None = None
    rack_name: str | None = None
    uom_conversions: list[UomConversionOut] = []


class FacetBucket(BaseModel):
    id: str | None
    label: str
    count: int


class ItemFacets(BaseModel):
    """Counts for the left-hand filter panel on Product Details."""
    main_categories: list[FacetBucket]
    sub_categories: list[FacetBucket]
    sub_detail_categories: list[FacetBucket]
    racks: list[FacetBucket]
    item_statuses: list[FacetBucket]


# ---------- Stock adjustment ----------
class StockAdjustmentIn(BaseModel):
    """A manual correction to stock held at a location.

    Corrections are movements, never edits to a balance: the ledger stays an
    append-only record of what happened, and the reason is required so a
    figure can always be explained later.
    """
    item_id: str
    location_id: str | None = None
    direction: str = Field(pattern="^(in|out)$")
    quantity: Decimal = Field(gt=0)
    entry_date: date | None = None
    remarks: str = Field(min_length=3, max_length=500)


class StockTransferIn(BaseModel):
    """Move stock from one location to another.

    A transfer is two movements, not one: the quantity leaves the source and
    arrives at the destination in the same transaction. The company total is
    unchanged — only where the goods sit changes.
    """
    item_id: str
    from_location_id: str
    to_location_id: str
    quantity: Decimal = Field(gt=0)
    entry_date: date | None = None
    remarks: str | None = None


class StockOpeningIn(BaseModel):
    """Set a product's starting stock at a location.

    Recorded as a movement like everything else, so the balance is still the
    sum of its history rather than a number someone typed over the top.
    """
    item_id: str
    location_id: str | None = None
    quantity: Decimal = Field(gt=0)
    entry_date: date | None = None
    remarks: str | None = None


class ItemPriceIn(BaseModel):
    """The selling price carried on the product record."""
    currency: str | None = None
    price: Decimal = Field(ge=0)
