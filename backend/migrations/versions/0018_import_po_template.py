"""import purchase order template fields

Revision ID: 0018
Revises: 0017

Fields from the company's Import Purchase Order template: purchase category
and revision; buyer and supplier contacts, ship-to and bill-to; Incoterm
edition and named place, partial shipment / transshipment, packing marks and
country of export; packing, insurance and other agreed charges; payment
method, advance, balance trigger, bank charges and payment reference; goods
condition, warranty, remedy, packing, pre-shipment inspection and special
instructions; and the origin of each line.
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

TEXT = ["purchase_category", "buyer_designation", "supplier_contact", "supplier_contact_designation", "ship_to_address", "bill_to_address", "incoterm_edition", "named_place", "partial_shipment", "transshipment", "packing_marks", "country_of_export", "payment_method", "balance_trigger", "bank_charges", "payment_reference", "goods_condition", "warranty_terms", "defect_remedy", "special_packing", "pre_shipment_inspection", "special_instructions"]
MONEY = ["packing_amount", "insurance_amount", "other_charges", "advance_amount", "advance_percent"]


def upgrade() -> None:
    for name in TEXT:
        op.add_column("purchase_orders", sa.Column(name, sa.Text(), nullable=True))
    for name in MONEY:
        op.add_column("purchase_orders", sa.Column(name, sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("purchase_orders", sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("purchase_order_lines", sa.Column("origin_country", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_order_lines", "origin_country")
    op.drop_column("purchase_orders", "revision")
    for name in [*TEXT, *MONEY]:
        op.drop_column("purchase_orders", name)