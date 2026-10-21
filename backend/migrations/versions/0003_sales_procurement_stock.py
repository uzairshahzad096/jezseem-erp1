"""sales, partners, gate passes, procurement, stock ledger, numbering

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------------- business partners ----------------
    op.create_table(
        "business_partners",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("is_customer", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_supplier", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("address", sa.Text()),
        sa.Column("city", sa.String(100)),
        sa.Column("territory", sa.String(100)),
        sa.Column("ntn", sa.String(50)),
        sa.Column("stn", sa.String(50)),
        sa.Column("phone", sa.String(50)),
        sa.Column("cell", sa.String(50)),
        sa.Column("email", sa.String(255)),
        sa.Column("payment_terms", sa.String(255)),
        sa.Column("credit_days", sa.Integer()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("company_id", "code", name="uq_partner_code_per_company"),
    )
    op.create_index("ix_partners_company_id", "business_partners", ["company_id"])
    op.create_index("ix_partners_name", "business_partners", ["name"])
    op.create_index("ix_partners_code", "business_partners", ["code"])

    op.create_table(
        "partner_contacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("partner_id", UUID(as_uuid=True), sa.ForeignKey("business_partners.id"), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=False),
        sa.Column("title", sa.String(150)),
        sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(50)),
        sa.Column("cell", sa.String(50)),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_partner_contacts_partner_id", "partner_contacts", ["partner_id"])
    op.create_index("ix_partner_contacts_company_id", "partner_contacts", ["company_id"])

    # ---------------- document numbering ----------------
    op.create_table(
        "document_sequences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("fiscal_year", sa.String(20), nullable=False),
        sa.Column("doc_type", sa.String(50), nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("company_id", "fiscal_year", "doc_type", name="uq_sequence_scope"),
    )

    # ---------------- sales documents ----------------
    op.create_table(
        "sales_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("branch_id", UUID(as_uuid=True), sa.ForeignKey("branches.id")),
        sa.Column("doc_type", sa.String(20), nullable=False),
        sa.Column("doc_number", sa.String(50), nullable=False),
        sa.Column("doc_date", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.String(20)),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("business_partners.id"), nullable=False),
        sa.Column("source_document_id", UUID(as_uuid=True), sa.ForeignKey("sales_documents.id")),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft"),
        sa.Column("payment_status", sa.String(30)),
        sa.Column("demand_number", sa.String(100)),
        sa.Column("customer_po_number", sa.String(100)),
        sa.Column("dc_number", sa.String(100)),
        sa.Column("delivery_person", sa.String(150)),
        sa.Column("vehicle_number", sa.String(100)),
        sa.Column("location", sa.String(150)),
        sa.Column("with_sales_tax", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("currency", sa.String(10), nullable=False, server_default="PKR"),
        sa.Column("exchange_rate", sa.Numeric(18, 6)),
        sa.Column("payment_terms", sa.String(255)),
        sa.Column("payment_reference", sa.Text()),
        sa.Column("remarks", sa.Text()),
        sa.Column("excluding_tax_value", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("sales_tax_value", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("freight_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_receivable", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("company_id", "doc_type", "doc_number", name="uq_sales_doc_number"),
    )
    for col in ["company_id", "doc_type", "doc_number", "doc_date", "customer_id", "status", "fiscal_year", "branch_id", "source_document_id", "payment_status"]:
        op.create_index(f"ix_sales_documents_{col}", "sales_documents", [col])

    op.create_table(
        "sales_document_lines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("sales_documents.id"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("item_id", UUID(as_uuid=True), sa.ForeignKey("inventory_items.id")),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("item_code", sa.String(40)),
        sa.Column("uom", sa.String(30)),
        sa.Column("hs_code", sa.String(50)),
        sa.Column("lot_number", sa.String(50)),
        sa.Column("rack_name", sa.String(100)),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("delivered_quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(10)),
        sa.Column("discount_percent", sa.Numeric(9, 4), nullable=False, server_default="0"),
        sa.Column("tax_percent", sa.Numeric(9, 4), nullable=False, server_default="0"),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("taxable_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )
    op.create_index("ix_sales_lines_document_id", "sales_document_lines", ["document_id"])
    op.create_index("ix_sales_lines_item_id", "sales_document_lines", ["item_id"])

    # ---------------- gate passes ----------------
    op.create_table(
        "gate_passes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("pass_type", sa.String(20), nullable=False),
        sa.Column("doc_number", sa.String(50), nullable=False),
        sa.Column("doc_date", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.String(20)),
        sa.Column("party_id", UUID(as_uuid=True), sa.ForeignKey("business_partners.id")),
        sa.Column("reference_gate_pass_id", UUID(as_uuid=True), sa.ForeignKey("gate_passes.id")),
        sa.Column("sales_document_id", UUID(as_uuid=True), sa.ForeignKey("sales_documents.id")),
        sa.Column("vehicle_number", sa.String(100)),
        sa.Column("driver", sa.String(150)),
        sa.Column("issue_type", sa.String(50)),
        sa.Column("issue_to", sa.String(255)),
        sa.Column("challan_number", sa.String(100)),
        sa.Column("dc_number", sa.String(100)),
        sa.Column("container_number", sa.String(100)),
        sa.Column("remarks", sa.Text()),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft"),
        sa.Column("is_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("currency", sa.String(10), nullable=False, server_default="PKR"),
        sa.Column("excluding_tax_value", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("sales_tax_value", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("freight_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("company_id", "pass_type", "doc_number", name="uq_gatepass_number"),
    )
    for col in ["company_id", "pass_type", "doc_number", "doc_date", "party_id", "status", "reference_gate_pass_id", "sales_document_id"]:
        op.create_index(f"ix_gate_passes_{col}", "gate_passes", [col])

    op.create_table(
        "gate_pass_lines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("gate_pass_id", UUID(as_uuid=True), sa.ForeignKey("gate_passes.id"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("item_id", UUID(as_uuid=True), sa.ForeignKey("inventory_items.id")),
        sa.Column("item_code", sa.String(40)),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("uom", sa.String(30)),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("returned_quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("discount_percent", sa.Numeric(9, 4), nullable=False, server_default="0"),
        sa.Column("tax_percent", sa.Numeric(9, 4), nullable=False, server_default="0"),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("taxable_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )
    op.create_index("ix_gate_pass_lines_gate_pass_id", "gate_pass_lines", ["gate_pass_id"])
    op.create_index("ix_gate_pass_lines_item_id", "gate_pass_lines", ["item_id"])

    # ---------------- purchase orders ----------------
    op.create_table(
        "purchase_orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("doc_number", sa.String(50), nullable=False),
        sa.Column("doc_date", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.String(20)),
        sa.Column("supplier_id", UUID(as_uuid=True), sa.ForeignKey("business_partners.id"), nullable=False),
        sa.Column("purchaser", sa.String(150)),
        sa.Column("purchaser_email", sa.String(255)),
        sa.Column("contact_number", sa.String(50)),
        sa.Column("po_status", sa.String(30), nullable=False, server_default="RUNNING"),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft"),
        sa.Column("expiry_date", sa.Date()),
        sa.Column("target_date", sa.Date()),
        sa.Column("po_type", sa.String(50)),
        sa.Column("purchase_type", sa.String(50)),
        sa.Column("payment_terms", sa.String(255)),
        sa.Column("shipping_terms", sa.String(255)),
        sa.Column("credit_days", sa.Integer()),
        sa.Column("indent_number", sa.String(100)),
        sa.Column("remarks", sa.Text()),
        sa.Column("currency", sa.String(10), nullable=False, server_default="PKR"),
        sa.Column("exchange_rate", sa.Numeric(18, 6)),
        sa.Column("excluding_tax_value", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("sales_tax_value", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("freight_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_payable", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("company_id", "doc_number", name="uq_po_number"),
    )
    for col in ["company_id", "doc_number", "doc_date", "supplier_id", "po_status", "status"]:
        op.create_index(f"ix_purchase_orders_{col}", "purchase_orders", [col])

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("purchase_order_id", UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("item_id", UUID(as_uuid=True), sa.ForeignKey("inventory_items.id")),
        sa.Column("item_code", sa.String(40)),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("uom", sa.String(30)),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("received_quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("discount_percent", sa.Numeric(9, 4), nullable=False, server_default="0"),
        sa.Column("tax_percent", sa.Numeric(9, 4), nullable=False, server_default="0"),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("taxable_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )
    op.create_index("ix_po_lines_purchase_order_id", "purchase_order_lines", ["purchase_order_id"])
    op.create_index("ix_po_lines_item_id", "purchase_order_lines", ["item_id"])

    # ---------------- material receiving notes ----------------
    op.create_table(
        "material_receiving_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("doc_number", sa.String(50), nullable=False),
        sa.Column("doc_date", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.String(20)),
        sa.Column("supplier_id", UUID(as_uuid=True), sa.ForeignKey("business_partners.id"), nullable=False),
        sa.Column("purchase_order_id", UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id")),
        sa.Column("supplier_invoice_number", sa.String(100)),
        sa.Column("supplier_invoice_date", sa.Date()),
        sa.Column("vehicle_number", sa.String(100)),
        sa.Column("remarks", sa.Text()),
        sa.Column("status", sa.String(30), nullable=False, server_default="Draft"),
        sa.Column("is_posted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("currency", sa.String(10), nullable=False, server_default="PKR"),
        sa.Column("excluding_tax_value", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("sales_tax_value", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("freight_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_payable", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("company_id", "doc_number", name="uq_mrn_number"),
    )
    for col in ["company_id", "doc_number", "doc_date", "supplier_id", "purchase_order_id", "status"]:
        op.create_index(f"ix_mrn_{col}", "material_receiving_notes", [col])

    op.create_table(
        "mrn_lines",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("mrn_id", UUID(as_uuid=True), sa.ForeignKey("material_receiving_notes.id"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("purchase_order_line_id", UUID(as_uuid=True), sa.ForeignKey("purchase_order_lines.id")),
        sa.Column("item_id", UUID(as_uuid=True), sa.ForeignKey("inventory_items.id")),
        sa.Column("item_code", sa.String(40)),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("uom", sa.String(30)),
        sa.Column("ordered_quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("received_quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("remaining_quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("unit_price", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("discount_percent", sa.Numeric(9, 4), nullable=False, server_default="0"),
        sa.Column("tax_percent", sa.Numeric(9, 4), nullable=False, server_default="0"),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("taxable_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("net_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )
    op.create_index("ix_mrn_lines_mrn_id", "mrn_lines", ["mrn_id"])
    op.create_index("ix_mrn_lines_item_id", "mrn_lines", ["item_id"])
    op.create_index("ix_mrn_lines_po_line_id", "mrn_lines", ["purchase_order_line_id"])

    # ---------------- stock ledger ----------------
    op.create_table(
        "stock_ledger_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", UUID(as_uuid=True), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("item_id", UUID(as_uuid=True), sa.ForeignKey("inventory_items.id"), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 4)),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", UUID(as_uuid=True)),
        sa.Column("source_number", sa.String(50)),
        sa.Column("remarks", sa.Text()),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id")),
    )
    for col in ["company_id", "item_id", "entry_date", "source_type", "source_id"]:
        op.create_index(f"ix_stock_ledger_{col}", "stock_ledger_entries", [col])


def downgrade() -> None:
    for table in [
        "stock_ledger_entries", "mrn_lines", "material_receiving_notes",
        "purchase_order_lines", "purchase_orders", "gate_pass_lines", "gate_passes",
        "sales_document_lines", "sales_documents", "document_sequences",
        "partner_contacts", "business_partners",
    ]:
        op.drop_table(table)
