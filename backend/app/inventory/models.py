"""
Inventory module — Setup Forms entities.

Modelled directly on the existing ERP's screens (Item Racks, Item Locations,
Main Products, Inventory Sub Category, Inventory Sub Detail Category,
Product Details) so the terminology stays familiar to staff, while the
storage itself is normalised PostgreSQL rather than the legacy structure.

The category chain is three levels, exactly as in the old system:

    MainProduct  ->  InventorySubCategory  ->  InventorySubDetailCategory
       (7 rows)            (28 rows)                    (57 rows)
                                  \\_______  InventoryItem  _______/
"""

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.mixins import AuditMixin, UUIDPKMixin
from app.core.database import Base


class ItemRack(UUIDPKMixin, AuditMixin, Base):
    """Physical storage rack, e.g. "A1", "B7". The old screen holds a single
    Rack Name field."""

    __tablename__ = "item_racks"
    __table_args__ = (UniqueConstraint("company_id", "rack_name", name="uq_rack_per_company"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    rack_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ItemLocation(UUIDPKMixin, AuditMixin, Base):
    """Inventory storage location. The old form uses a free-text area plus an
    Active toggle, so this is Text rather than a short string."""

    __tablename__ = "item_locations"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    location: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class UnitOfMeasure(UUIDPKMixin, AuditMixin, Base):
    """A unit goods are counted in — PCS, SET, KG, MT.

    A table rather than free text on the item, because a typed unit drifts:
    "Pcs", "PCS" and "pieces" are three units to a report and one to a human,
    and a quantity whose unit cannot be trusted cannot be converted, totalled
    or reconciled against a supplier's packing list.

    The forms still accept anything typed — a one-off unit on a single
    purchase should not need a master-data change first — but what is typed
    is offered from this list, so the common case stays consistent.
    """

    __tablename__ = "unit_of_measures"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_uom_code"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    #: What appears on documents: PCS, KG. Stored upper-case so the same unit
    #: typed two ways is one row.
    code: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(150), nullable=False)
    #: Free text on purpose: "weight", "length", "count". Grouping units is
    #: useful in a picker and not worth a second table.
    category: Mapped[str | None] = mapped_column(String(50))
    #: How many of the base unit this one is, where that is known — a SET of
    #: 12 is 12 PCS. Conversions between arbitrary units need a rate table;
    #: this covers the common "bigger pack of the same thing" case.
    base_uom_code: Mapped[str | None] = mapped_column(String(30))
    conversion_to_base: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    #: Decimal places a quantity in this unit sensibly carries. Pieces are
    #: whole; kilogrammes are not.
    decimal_places: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class MainProduct(UUIDPKMixin, AuditMixin, Base):
    """Top category level — "MACHINERY AND PARTS", "SPARE PARTS", etc.
    Called Invmaincode in the legacy exports."""

    __tablename__ = "main_products"
    __table_args__ = (UniqueConstraint("company_id", "description", name="uq_main_product_per_company"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(150), nullable=False)
    remarks: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sub_categories: Mapped[list["InventorySubCategory"]] = relationship(
        back_populates="main_product", cascade="all, delete-orphan"
    )


class InventorySubCategory(UUIDPKMixin, AuditMixin, Base):
    """Second category level. `sub_code` is the 4-digit code shown in the old
    grid (1111, 1315, 1611 …).

    REQUIRES BUSINESS CONFIRMATION: whether sub_code is assigned by the user
    or derived from the main product. It is stored as entered for now, never
    generated, so no rule is invented.
    """

    __tablename__ = "inventory_sub_categories"
    __table_args__ = (UniqueConstraint("company_id", "sub_code", name="uq_sub_code_per_company"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    main_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("main_products.id"), nullable=False, index=True
    )
    sub_code: Mapped[str | None] = mapped_column(String(20), index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    remarks: Mapped[str | None] = mapped_column(String(500))

    # Account detail codes carried over from the legacy export. They are
    # plain strings until the Finance module defines a chart of accounts,
    # at which point they become foreign keys.
    detailcode_purchase_local: Mapped[str | None] = mapped_column(String(50))
    detailcode_purchase_import: Mapped[str | None] = mapped_column(String(50))
    detailcode_wip: Mapped[str | None] = mapped_column(String(50))
    detailcode_finish_stock: Mapped[str | None] = mapped_column(String(50))
    detailcode_sales_local: Mapped[str | None] = mapped_column(String(50))
    detailcode_sales_export: Mapped[str | None] = mapped_column(String(50))
    cos_account: Mapped[str | None] = mapped_column(String(50))
    detailcode_consumption: Mapped[str | None] = mapped_column(String(50))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    main_product: Mapped["MainProduct"] = relationship(back_populates="sub_categories")
    detail_categories: Mapped[list["InventorySubDetailCategory"]] = relationship(
        back_populates="sub_category", cascade="all, delete-orphan"
    )


class InventorySubDetailCategory(UUIDPKMixin, AuditMixin, Base):
    """Third category level — the old screen calls this Product Family on the
    item form and Sub Dtl Category on the product filters."""

    __tablename__ = "inventory_sub_detail_categories"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    main_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("main_products.id"), nullable=False, index=True
    )
    sub_category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_sub_categories.id"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    remarks: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sub_category: Mapped["InventorySubCategory"] = relationship(back_populates="detail_categories")


class InventoryItem(UUIDPKMixin, AuditMixin, Base):
    """A product. `item_code` is the legacy 12-digit INVDETAILCODE, preserved
    so old documents, barcodes and reports still resolve (spec section 10:
    preserve old ERP references where possible)."""

    __tablename__ = "inventory_items"
    __table_args__ = (UniqueConstraint("company_id", "item_code", name="uq_item_code_per_company"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    item_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    main_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("main_products.id"), index=True
    )
    sub_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_sub_categories.id"), index=True
    )
    sub_detail_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_sub_detail_categories.id"), index=True
    )
    rack_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("item_racks.id"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("item_locations.id")
    )

    description: Mapped[str] = mapped_column(Text, nullable=False)
    new_description: Mapped[str | None] = mapped_column(Text)
    short_name: Mapped[str | None] = mapped_column(String(255))
    composition: Mapped[str | None] = mapped_column(String(255))
    uom: Mapped[str | None] = mapped_column(String(30), index=True)
    import_uom: Mapped[str | None] = mapped_column(String(30))
    market_uom: Mapped[str | None] = mapped_column(String(30))
    market_name: Mapped[str | None] = mapped_column(String(255))
    sku: Mapped[str | None] = mapped_column(String(100), index=True)
    barcode: Mapped[str | None] = mapped_column(String(100), index=True)

    item_status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False, index=True)
    item_type: Mapped[str | None] = mapped_column(String(50))
    nature: Mapped[str | None] = mapped_column(String(50))
    processed_item: Mapped[str | None] = mapped_column(String(50))
    origin_country: Mapped[str | None] = mapped_column(String(100))
    lead_days: Mapped[int | None] = mapped_column(Integer)

    min_level: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    max_level: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    re_order_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    multiplier_factor: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))

    currency: Mapped[str | None] = mapped_column(String(10))
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    image_path: Mapped[str | None] = mapped_column(String(500))

    # Denormalised opening figure carried from the legacy export. Live stock
    # will come from the stock ledger once Transactions are built; this column
    # is the imported starting point only, never written by transactions.
    opening_stock: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    # Legacy identifiers kept for reconciliation against the old system.
    legacy_cat_id: Mapped[str | None] = mapped_column(String(50))
    legacy_comp_id: Mapped[str | None] = mapped_column(String(50))

    uom_conversions: Mapped[list["ItemUomConversion"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class ItemUomConversion(UUIDPKMixin, Base):
    """The "Conversions Uoms" child grid on the item form."""

    __tablename__ = "item_uom_conversions"

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False, index=True
    )
    uom: Mapped[str] = mapped_column(String(30), nullable=False)
    conversion_factor: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)

    item: Mapped["InventoryItem"] = relationship(back_populates="uom_conversions")
