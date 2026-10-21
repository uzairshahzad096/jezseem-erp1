"""procurement: in-house orders, import purchasing, landed costing

Revision ID: 0006
Revises: 0005

Builds the procurement chain:

  in_house_orders / in_house_order_lines   the requirement
  purchase_orders                          extended for local vs import
  import_shipments / _lines                what left the supplier
  landed_cost_charge_types                 configurable import costs
  landed_costs / _charges / _items / _allocations   what it really cost
  material_receiving_notes                 extended: warehouse, shipment,
                                           requirement and costing links

Every added column is nullable or carries a server default, so the existing
purchase_orders and material_receiving_notes tables keep working; the four
of them are empty today, but the migration does not rely on that.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _money(precision=18, scale=2):
    return sa.Numeric(precision, scale)


def _add_missing(table: str, columns: list) -> None:
    """Add only the columns the table does not already have.

    `purchase_orders` and `material_receiving_notes` were created by 0003 and
    already carry a few of these names, so a blind ADD COLUMN fails halfway
    through and leaves the migration unrunnable. Checking first also makes
    this safe on a database that was patched by hand.
    """
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}
    for column in columns:
        if column.name not in existing:
            op.add_column(table, column)


def upgrade() -> None:
    # ---------------------------------------------------------- in-house order
    op.create_table(
        "in_house_orders",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("branch_id", pg.UUID(as_uuid=True), sa.ForeignKey("branches.id"), index=True),
        sa.Column("doc_number", sa.String(50), nullable=False, index=True),
        sa.Column("doc_date", sa.Date, nullable=False, index=True),
        sa.Column("fiscal_year", sa.String(20)),
        sa.Column("warehouse_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("item_locations.id"), index=True),
        sa.Column("department", sa.String(150)),
        sa.Column("requested_by", sa.String(150)),
        sa.Column("requested_by_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("required_date", sa.Date),
        sa.Column("priority", sa.String(20), nullable=False, server_default="Normal"),
        sa.Column("purpose", sa.Text),
        sa.Column("source", sa.String(40), nullable=False, server_default="Manual", index=True),
        sa.Column("source_document_type", sa.String(50)),
        sa.Column("source_document_id", pg.UUID(as_uuid=True), index=True),
        sa.Column("remarks", sa.Text),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft", index=True),
        sa.Column("submitted_at", sa.Date),
        sa.Column("approved_at", sa.Date),
        sa.Column("approved_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("total_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("updated_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("company_id", "doc_number", name="uq_iho_number"),
    )

    op.create_table(
        "in_house_order_lines",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("in_house_order_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("in_house_orders.id"), nullable=False, index=True),
        sa.Column("line_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("item_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("inventory_items.id"), index=True),
        sa.Column("item_code", sa.String(40)),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("uom", sa.String(30)),
        sa.Column("stock_on_hand", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("reserved_stock", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("available_stock", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("stock_other_warehouses", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("stock_on_order", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("goods_in_transit", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("reorder_level", _money(18, 4)),
        sa.Column("min_level", _money(18, 4)),
        sa.Column("max_level", _money(18, 4)),
        sa.Column("requested_quantity", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("approved_quantity", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("ordered_quantity", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("received_quantity", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("fulfilment_source", sa.String(40)),
        sa.Column("required_date", sa.Date),
        sa.Column("destination_warehouse_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("item_locations.id")),
        sa.Column("remarks", sa.Text),
    )

    # ------------------------------------------------- purchase order additions
    po_columns = [
        sa.Column("branch_id", pg.UUID(as_uuid=True), sa.ForeignKey("branches.id")),
        sa.Column("in_house_order_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("in_house_orders.id")),
        sa.Column("warehouse_id", pg.UUID(as_uuid=True), sa.ForeignKey("item_locations.id")),
        sa.Column("expected_delivery_date", sa.Date),
        sa.Column("delivery_terms", sa.String(255)),
        sa.Column("supplier_quotation_number", sa.String(100)),
        sa.Column("supplier_quotation_date", sa.Date),
        sa.Column("approved_at", sa.Date),
        sa.Column("approved_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("exchange_rate_date", sa.Date),
        sa.Column("supplier_country", sa.String(100)),
        sa.Column("country_of_origin", sa.String(100)),
        sa.Column("incoterm", sa.String(30)),
        sa.Column("shipping_mode", sa.String(30)),
        sa.Column("port_of_loading", sa.String(150)),
        sa.Column("port_of_discharge", sa.String(150)),
        sa.Column("expected_shipment_date", sa.Date),
        sa.Column("expected_arrival_date", sa.Date),
        sa.Column("commercial_invoice_number", sa.String(100)),
        sa.Column("commercial_invoice_date", sa.Date),
        sa.Column("packing_list_number", sa.String(100)),
        sa.Column("bill_of_lading_number", sa.String(100)),
        sa.Column("airway_bill_number", sa.String(100)),
        sa.Column("container_number", sa.String(100)),
        sa.Column("lc_number", sa.String(100)),
        sa.Column("lc_date", sa.Date),
        sa.Column("bank_name", sa.String(200)),
        sa.Column("freight_forwarder", sa.String(200)),
        sa.Column("clearing_agent", sa.String(200)),
        sa.Column("insurance_provider", sa.String(200)),
        sa.Column("customs_reference", sa.String(100)),
        sa.Column("import_reference", sa.String(100)),
        sa.Column("net_payable_base", _money(), nullable=False, server_default="0"),
    ]
    _add_missing("purchase_orders", po_columns)

    # purchase_type already exists from 0003 as a free-text, nullable column.
    # It now decides how the whole document behaves, so it gets a default and
    # a NOT NULL rather than a second column beside it.
    op.execute("update purchase_orders set purchase_type = 'Local' "
               "where purchase_type is null or btrim(purchase_type) = ''")
    op.alter_column("purchase_orders", "purchase_type",
                    existing_type=sa.String(50), type_=sa.String(20),
                    nullable=False, server_default="Local")
    op.create_index("ix_purchase_orders_purchase_type", "purchase_orders", ["purchase_type"])
    # An exchange rate of "unknown" is not a thing: a PKR order is rate 1.
    op.execute("update purchase_orders set exchange_rate = 1 where exchange_rate is null")
    op.alter_column("purchase_orders", "exchange_rate",
                    nullable=False, server_default="1", existing_type=sa.Numeric(18, 6))

    _add_missing("purchase_order_lines", [
        sa.Column("in_house_order_line_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("in_house_order_lines.id")),
        sa.Column("hs_code", sa.String(40)),
        sa.Column("free_quantity", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("shipped_quantity", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("unit_weight", _money(18, 4)),
        sa.Column("unit_volume", _money(18, 4)),
        sa.Column("warehouse_id", pg.UUID(as_uuid=True), sa.ForeignKey("item_locations.id")),
        sa.Column("required_date", sa.Date),
        sa.Column("remarks", sa.Text),
    ])

    # --------------------------------------------------------- import shipments
    op.create_table(
        "import_shipments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("doc_number", sa.String(50), nullable=False, index=True),
        sa.Column("doc_date", sa.Date, nullable=False, index=True),
        sa.Column("fiscal_year", sa.String(20)),
        sa.Column("purchase_order_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("purchase_orders.id"), nullable=False, index=True),
        sa.Column("supplier_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("business_partners.id"), nullable=False, index=True),
        sa.Column("warehouse_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("item_locations.id"), index=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft", index=True),
        sa.Column("transit_status", sa.String(30), nullable=False,
                  server_default="Purchased", index=True),
        sa.Column("customs_status", sa.String(30), index=True),
        sa.Column("clearance_status", sa.String(30)),
        sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
        sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("exchange_rate_date", sa.Date),
        sa.Column("container_number", sa.String(100)),
        sa.Column("bill_of_lading_number", sa.String(100)),
        sa.Column("airway_bill_number", sa.String(100)),
        sa.Column("vessel_or_flight", sa.String(150)),
        sa.Column("port_of_loading", sa.String(150)),
        sa.Column("port_of_discharge", sa.String(150)),
        sa.Column("shipping_mode", sa.String(30)),
        sa.Column("clearing_agent", sa.String(200)),
        sa.Column("customs_reference", sa.String(100)),
        sa.Column("etd", sa.Date),
        sa.Column("eta", sa.Date),
        sa.Column("actual_arrival_date", sa.Date),
        sa.Column("cleared_date", sa.Date),
        sa.Column("freight_amount", _money(), nullable=False, server_default="0"),
        sa.Column("insurance_amount", _money(), nullable=False, server_default="0"),
        sa.Column("shipment_value", _money(), nullable=False, server_default="0"),
        sa.Column("shipment_value_base", _money(), nullable=False, server_default="0"),
        sa.Column("total_quantity", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("total_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("remarks", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("updated_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("company_id", "doc_number", name="uq_shipment_number"),
    )

    op.create_table(
        "import_shipment_lines",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("shipment_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("import_shipments.id"), nullable=False, index=True),
        sa.Column("line_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("purchase_order_line_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("purchase_order_lines.id"), index=True),
        sa.Column("item_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("inventory_items.id"), index=True),
        sa.Column("item_code", sa.String(40)),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("uom", sa.String(30)),
        sa.Column("hs_code", sa.String(40)),
        sa.Column("shipped_quantity", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("received_quantity", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("unit_price", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("line_value", _money(), nullable=False, server_default="0"),
        sa.Column("total_weight", _money(18, 4)),
        sa.Column("total_volume", _money(18, 4)),
        sa.Column("remarks", sa.Text),
    )

    # ----------------------------------------------------------- landed costing
    op.create_table(
        "landed_cost_charge_types",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("cost_group", sa.String(30), nullable=False, index=True),
        sa.Column("default_allocation", sa.String(20), nullable=False, server_default="Value"),
        sa.Column("default_rate_percent", sa.Numeric(9, 4)),
        sa.Column("account_code", sa.String(50)),
        sa.Column("is_inventoriable", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("updated_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("company_id", "name", name="uq_charge_type_name"),
    )

    op.create_table(
        "landed_costs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("doc_number", sa.String(50), nullable=False, index=True),
        sa.Column("doc_date", sa.Date, nullable=False, index=True),
        sa.Column("fiscal_year", sa.String(20)),
        sa.Column("purchase_order_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("purchase_orders.id"), index=True),
        sa.Column("shipment_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("import_shipments.id"), index=True),
        sa.Column("supplier_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("business_partners.id"), index=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft", index=True),
        sa.Column("is_posted", sa.Boolean, nullable=False, server_default=sa.false(), index=True),
        sa.Column("posted_at", sa.Date),
        sa.Column("posted_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.Date),
        sa.Column("approved_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
        sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("exchange_rate_date", sa.Date),
        sa.Column("allocation_method", sa.String(20), nullable=False, server_default="Value"),
        sa.Column("supplier_invoice_number", sa.String(100)),
        sa.Column("supplier_invoice_date", sa.Date),
        sa.Column("customs_reference", sa.String(100)),
        sa.Column("remarks", sa.Text),
        sa.Column("purchase_cost_base", _money(), nullable=False, server_default="0"),
        sa.Column("additional_cost_base", _money(), nullable=False, server_default="0"),
        sa.Column("total_landed_cost", _money(), nullable=False, server_default="0"),
        sa.Column("total_quantity", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("total_items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("updated_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("company_id", "doc_number", name="uq_landed_cost_number"),
    )

    op.create_table(
        "landed_cost_charges",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("landed_cost_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("landed_costs.id"), nullable=False, index=True),
        sa.Column("charge_type_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("landed_cost_charge_types.id"), index=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("cost_group", sa.String(30), nullable=False, index=True),
        sa.Column("vendor_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("business_partners.id"), index=True),
        sa.Column("reference", sa.String(100)),
        sa.Column("currency", sa.String(10), nullable=False, server_default="PKR"),
        sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("amount", _money(), nullable=False, server_default="0"),
        sa.Column("amount_base", _money(), nullable=False, server_default="0"),
        sa.Column("allocation_method", sa.String(20), nullable=False, server_default="Value"),
        sa.Column("is_inventoriable", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("remarks", sa.Text),
    )

    op.create_table(
        "landed_cost_items",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("landed_cost_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("landed_costs.id"), nullable=False, index=True),
        sa.Column("line_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("purchase_order_line_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("purchase_order_lines.id"), index=True),
        sa.Column("shipment_line_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("import_shipment_lines.id"), index=True),
        sa.Column("item_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("inventory_items.id"), index=True),
        sa.Column("item_code", sa.String(40)),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("uom", sa.String(30)),
        sa.Column("hs_code", sa.String(40)),
        sa.Column("quantity", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("total_weight", _money(18, 4)),
        sa.Column("total_volume", _money(18, 4)),
        sa.Column("manual_share_percent", sa.Numeric(9, 4)),
        sa.Column("unit_price", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("purchase_cost", _money(), nullable=False, server_default="0"),
        sa.Column("purchase_cost_base", _money(), nullable=False, server_default="0"),
        sa.Column("freight_cost", _money(), nullable=False, server_default="0"),
        sa.Column("insurance_cost", _money(), nullable=False, server_default="0"),
        sa.Column("customs_cost", _money(), nullable=False, server_default="0"),
        sa.Column("tax_cost", _money(), nullable=False, server_default="0"),
        sa.Column("port_cost", _money(), nullable=False, server_default="0"),
        sa.Column("clearing_cost", _money(), nullable=False, server_default="0"),
        sa.Column("bank_cost", _money(), nullable=False, server_default="0"),
        sa.Column("other_cost", _money(), nullable=False, server_default="0"),
        sa.Column("additional_cost", _money(), nullable=False, server_default="0"),
        sa.Column("total_landed_cost", _money(), nullable=False, server_default="0"),
        sa.Column("unit_landed_cost", _money(18, 4), nullable=False, server_default="0"),
    )

    op.create_table(
        "landed_cost_allocations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("landed_cost_item_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("landed_cost_items.id"), nullable=False, index=True),
        sa.Column("charge_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("landed_cost_charges.id"), nullable=False, index=True),
        sa.Column("cost_group", sa.String(30), nullable=False),
        sa.Column("allocation_method", sa.String(20), nullable=False),
        sa.Column("basis_value", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("basis_total", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("amount", _money(), nullable=False, server_default="0"),
    )

    # -------------------------------------------------- goods receipt additions
    _add_missing("material_receiving_notes", [
        sa.Column("branch_id", pg.UUID(as_uuid=True), sa.ForeignKey("branches.id")),
        sa.Column("shipment_id", pg.UUID(as_uuid=True), sa.ForeignKey("import_shipments.id")),
        sa.Column("in_house_order_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("in_house_orders.id")),
        sa.Column("landed_cost_id", pg.UUID(as_uuid=True), sa.ForeignKey("landed_costs.id")),
        sa.Column("warehouse_id", pg.UUID(as_uuid=True), sa.ForeignKey("item_locations.id")),
        sa.Column("received_by", sa.String(150)),
        sa.Column("posted_at", sa.Date),
        sa.Column("posted_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("exchange_rate", sa.Numeric(18, 6), nullable=False, server_default="1"),
    ])
    op.create_index("ix_mrn_is_posted", "material_receiving_notes", ["is_posted"])

    _add_missing("mrn_lines", [
        sa.Column("shipment_line_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("import_shipment_lines.id")),
        sa.Column("rejected_quantity", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("unit_cost_base", _money(18, 4), nullable=False, server_default="0"),
        sa.Column("warehouse_id", pg.UUID(as_uuid=True), sa.ForeignKey("item_locations.id")),
        sa.Column("remarks", sa.Text),
    ])

    # ------------------------------------------------------- supplier additions
    _add_missing("business_partners", [
        sa.Column("country", sa.String(100)),
        sa.Column("country_of_origin", sa.String(100)),
        sa.Column("is_international", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("currency", sa.String(10)),
        sa.Column("incoterm", sa.String(30)),
        sa.Column("bank_name", sa.String(200)),
        sa.Column("bank_account_number", sa.String(100)),
        sa.Column("bank_iban", sa.String(60)),
        sa.Column("bank_swift", sa.String(30)),
        sa.Column("bank_address", sa.Text),
    ])
    op.create_index("ix_business_partners_country", "business_partners", ["country"])


def downgrade() -> None:
    op.drop_index("ix_business_partners_country", table_name="business_partners")
    for name in ("bank_address", "bank_swift", "bank_iban", "bank_account_number", "bank_name",
                 "incoterm", "currency", "is_international", "country_of_origin", "country"):
        op.drop_column("business_partners", name)

    for name in ("remarks", "warehouse_id", "unit_cost_base",
                 "rejected_quantity", "shipment_line_id"):
        op.drop_column("mrn_lines", name)
    op.drop_index("ix_mrn_is_posted", table_name="material_receiving_notes")
    for name in ("exchange_rate", "posted_by", "posted_at", "received_by", "warehouse_id",
                 "landed_cost_id", "in_house_order_id", "shipment_id", "branch_id"):
        op.drop_column("material_receiving_notes", name)

    op.drop_table("landed_cost_allocations")
    op.drop_table("landed_cost_items")
    op.drop_table("landed_cost_charges")
    op.drop_table("landed_costs")
    op.drop_table("landed_cost_charge_types")
    op.drop_table("import_shipment_lines")
    op.drop_table("import_shipments")

    for name in ("remarks", "required_date", "warehouse_id", "unit_volume", "unit_weight",
                 "shipped_quantity", "free_quantity", "hs_code", "in_house_order_line_id"):
        op.drop_column("purchase_order_lines", name)
    op.drop_index("ix_purchase_orders_purchase_type", table_name="purchase_orders")
    op.alter_column("purchase_orders", "purchase_type",
                    existing_type=sa.String(20), type_=sa.String(50),
                    nullable=True, server_default=None)
    for name in ("net_payable_base", "import_reference", "customs_reference",
                 "insurance_provider", "clearing_agent", "freight_forwarder", "bank_name",
                 "lc_date", "lc_number", "container_number", "airway_bill_number",
                 "bill_of_lading_number", "packing_list_number", "commercial_invoice_date",
                 "commercial_invoice_number", "expected_arrival_date", "expected_shipment_date",
                 "port_of_discharge", "port_of_loading", "shipping_mode", "incoterm",
                 "country_of_origin", "supplier_country", "exchange_rate_date", "approved_by",
                 "approved_at", "supplier_quotation_date", "supplier_quotation_number",
                 "delivery_terms", "expected_delivery_date", "warehouse_id",
                 "in_house_order_id", "branch_id"):
        op.drop_column("purchase_orders", name)

    op.drop_table("in_house_order_lines")
    op.drop_table("in_house_orders")
