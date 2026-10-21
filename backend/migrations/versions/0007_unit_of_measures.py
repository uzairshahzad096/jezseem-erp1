"""units of measure as master data

Revision ID: 0007
Revises: 0006

UOM was free text on the item and on every document line, which is why 4,914
products say PCS and one says KG with nothing to stop a fifth spelling.

The table is seeded from the units actually in use rather than a generic
list — PCS, SET, MT, KG are what the catalogue and the sales history contain,
and they are exactly what the old ERP's UOM lookup offers. Anything else a
company needs is added on the Unit of Measure screen.

Existing text is left alone: the columns keep holding the code, so nothing
has to be migrated and a document written before this still reads correctly.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

#: (code, description, category, decimal places, order). Whole units get no
#: decimals so a quantity of 2.5 pieces cannot be typed by accident.
SEED = [
    ("PCS", "Pieces", "Count", 0, 10),
    ("SET", "Set", "Count", 0, 20),
    ("KG", "Kilogramme", "Weight", 3, 30),
    ("MT", "Metric Tonne", "Weight", 3, 40),
]


def upgrade() -> None:
    op.create_table(
        "unit_of_measures",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("code", sa.String(30), nullable=False, index=True),
        sa.Column("description", sa.String(150), nullable=False),
        sa.Column("category", sa.String(50)),
        sa.Column("base_uom_code", sa.String(30)),
        sa.Column("conversion_to_base", sa.Numeric(18, 6)),
        sa.Column("decimal_places", sa.Integer, nullable=False, server_default="2"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("updated_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.UniqueConstraint("company_id", "code", name="uq_uom_code"),
    )

    # Seed per company, and also pick up any unit already present in the data
    # that the seed list does not name — a real unit in use must not vanish
    # from the picker just because this migration did not think of it.
    bind = op.get_bind()
    companies = [row[0] for row in bind.execute(sa.text("select id from companies"))]
    for company_id in companies:
        for code, description, category, places, order in SEED:
            bind.execute(sa.text("""
                insert into unit_of_measures
                    (id, company_id, code, description, category, decimal_places,
                     is_active, sort_order)
                values (gen_random_uuid(), :company, :code, :description, :category,
                        :places, true, :order)
                on conflict (company_id, code) do nothing
            """), {"company": company_id, "code": code, "description": description,
                   "category": category, "places": places, "order": order})

        bind.execute(sa.text("""
            insert into unit_of_measures
                (id, company_id, code, description, category, decimal_places,
                 is_active, sort_order)
            select gen_random_uuid(), :company, upper(btrim(u.uom)),
                   upper(btrim(u.uom)), null, 2, true, 900
            from (
                select distinct uom from inventory_items
                where uom is not null and btrim(uom) <> ''
                union
                select distinct uom from sales_document_lines
                where uom is not null and btrim(uom) <> ''
            ) u
            where not exists (
                select 1 from unit_of_measures m
                where m.company_id = :company and m.code = upper(btrim(u.uom))
            )
            on conflict (company_id, code) do nothing
        """), {"company": company_id})


def downgrade() -> None:
    op.drop_table("unit_of_measures")
