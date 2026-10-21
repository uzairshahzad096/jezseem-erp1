"""inventory module: racks, locations, main products, categories, items

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _audit():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "item_racks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        *_audit(),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("rack_name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("company_id", "rack_name", name="uq_rack_per_company"),
    )
    op.create_index("ix_item_racks_company_id", "item_racks", ["company_id"])

    op.create_table(
        "item_locations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        *_audit(),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_item_locations_company_id", "item_locations", ["company_id"])

    op.create_table(
        "main_products",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        *_audit(),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("description", sa.String(150), nullable=False),
        sa.Column("remarks", sa.String(500)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("company_id", "description", name="uq_main_product_per_company"),
    )
    op.create_index("ix_main_products_company_id", "main_products", ["company_id"])

    op.create_table(
        "inventory_sub_categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        *_audit(),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("main_product_id", UUID(as_uuid=True), sa.ForeignKey("main_products.id"), nullable=False),
        sa.Column("sub_code", sa.String(20)),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("remarks", sa.String(500)),
        sa.Column("detailcode_purchase_local", sa.String(50)),
        sa.Column("detailcode_purchase_import", sa.String(50)),
        sa.Column("detailcode_wip", sa.String(50)),
        sa.Column("detailcode_finish_stock", sa.String(50)),
        sa.Column("detailcode_sales_local", sa.String(50)),
        sa.Column("detailcode_sales_export", sa.String(50)),
        sa.Column("cos_account", sa.String(50)),
        sa.Column("detailcode_consumption", sa.String(50)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("company_id", "sub_code", name="uq_sub_code_per_company"),
    )
    op.create_index("ix_sub_categories_company_id", "inventory_sub_categories", ["company_id"])
    op.create_index("ix_sub_categories_main_product_id", "inventory_sub_categories", ["main_product_id"])
    op.create_index("ix_sub_categories_sub_code", "inventory_sub_categories", ["sub_code"])

    op.create_table(
        "inventory_sub_detail_categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        *_audit(),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("main_product_id", UUID(as_uuid=True), sa.ForeignKey("main_products.id"), nullable=False),
        sa.Column("sub_category_id", UUID(as_uuid=True), sa.ForeignKey("inventory_sub_categories.id"), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("remarks", sa.String(500)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_sdc_company_id", "inventory_sub_detail_categories", ["company_id"])
    op.create_index("ix_sdc_main_product_id", "inventory_sub_detail_categories", ["main_product_id"])
    op.create_index("ix_sdc_sub_category_id", "inventory_sub_detail_categories", ["sub_category_id"])

    op.create_table(
        "inventory_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        *_audit(),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("item_code", sa.String(40), nullable=False),
        sa.Column("main_product_id", UUID(as_uuid=True), sa.ForeignKey("main_products.id")),
        sa.Column("sub_category_id", UUID(as_uuid=True), sa.ForeignKey("inventory_sub_categories.id")),
        sa.Column("sub_detail_category_id", UUID(as_uuid=True), sa.ForeignKey("inventory_sub_detail_categories.id")),
        sa.Column("rack_id", UUID(as_uuid=True), sa.ForeignKey("item_racks.id")),
        sa.Column("location_id", UUID(as_uuid=True), sa.ForeignKey("item_locations.id")),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("new_description", sa.Text()),
        sa.Column("short_name", sa.String(255)),
        sa.Column("composition", sa.String(255)),
        sa.Column("uom", sa.String(30)),
        sa.Column("import_uom", sa.String(30)),
        sa.Column("market_uom", sa.String(30)),
        sa.Column("market_name", sa.String(255)),
        sa.Column("sku", sa.String(100)),
        sa.Column("barcode", sa.String(100)),
        sa.Column("item_status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column("item_type", sa.String(50)),
        sa.Column("nature", sa.String(50)),
        sa.Column("processed_item", sa.String(50)),
        sa.Column("origin_country", sa.String(100)),
        sa.Column("lead_days", sa.Integer()),
        sa.Column("min_level", sa.Numeric(18, 4)),
        sa.Column("max_level", sa.Numeric(18, 4)),
        sa.Column("re_order_qty", sa.Numeric(18, 4)),
        sa.Column("multiplier_factor", sa.Numeric(18, 6)),
        sa.Column("currency", sa.String(10)),
        sa.Column("price", sa.Numeric(18, 4)),
        sa.Column("image_path", sa.String(500)),
        sa.Column("opening_stock", sa.Numeric(18, 4)),
        sa.Column("legacy_cat_id", sa.String(50)),
        sa.Column("legacy_comp_id", sa.String(50)),
        sa.UniqueConstraint("company_id", "item_code", name="uq_item_code_per_company"),
    )
    for col in ["company_id", "item_code", "main_product_id", "sub_category_id",
                "sub_detail_category_id", "uom", "sku", "barcode", "item_status"]:
        op.create_index(f"ix_inventory_items_{col}", "inventory_items", [col])

    op.create_table(
        "item_uom_conversions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("item_id", UUID(as_uuid=True), sa.ForeignKey("inventory_items.id"), nullable=False),
        sa.Column("uom", sa.String(30), nullable=False),
        sa.Column("conversion_factor", sa.Numeric(18, 6), nullable=False),
    )
    op.create_index("ix_item_uom_conversions_item_id", "item_uom_conversions", ["item_id"])


def downgrade() -> None:
    for table in ["item_uom_conversions", "inventory_items",
                  "inventory_sub_detail_categories", "inventory_sub_categories",
                  "main_products", "item_locations", "item_racks"]:
        op.drop_table(table)
