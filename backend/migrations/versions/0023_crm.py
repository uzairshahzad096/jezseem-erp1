"""crm: contacts fields and one activity log for leads and customers

Revision ID: 0023
Revises: 0022

- partner_contacts gains department, whatsapp and is_primary.
- lead_activities may now belong to a customer without a lead (a courtesy
  visit, a complaint call): lead_id becomes optional, customer_id and
  contact_id are added, and every activity must name a lead or a customer.
- The CRM permissions are given to the Administrator role.
No existing row is changed.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

ACTIONS = ["view", "create", "edit", "delete", "approve", "post", "cancel", "export", "print"]
CODES = [(sub, action, f"crm.{sub}.{action}")
         for sub in ("customers", "contacts", "opportunities", "activities") for action in ACTIONS]


def upgrade() -> None:
    op.add_column("partner_contacts", sa.Column("department", sa.String(100), nullable=True))
    op.add_column("partner_contacts", sa.Column("whatsapp", sa.String(50), nullable=True))
    op.add_column("partner_contacts", sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"))

    op.alter_column("lead_activities", "lead_id", nullable=True)
    op.add_column("lead_activities", sa.Column("customer_id", UUID(as_uuid=True),
                                               sa.ForeignKey("business_partners.id"), nullable=True))
    op.add_column("lead_activities", sa.Column("contact_id", UUID(as_uuid=True),
                                               sa.ForeignKey("partner_contacts.id"), nullable=True))
    op.create_index("ix_lead_activities_customer_id", "lead_activities", ["customer_id"])
    op.create_check_constraint("ck_activity_lead_or_customer", "lead_activities",
                               "lead_id is not null or customer_id is not null")

    bind = op.get_bind()
    for _sub, action, code in CODES:
        bind.execute(sa.text("""
            insert into permissions (id, module, action, code) values (gen_random_uuid(), 'crm', :action, :code)
            on conflict (code) do nothing
        """), {"action": action, "code": code})
    bind.execute(sa.text("""
        insert into role_permissions (role_id, permission_id)
        select r.id, p.id from roles r cross join permissions p
        where r.name = 'Administrator' and p.code = any(:codes)
        on conflict do nothing
    """), {"codes": [c[2] for c in CODES]})


def downgrade() -> None:
    op.drop_constraint("ck_activity_lead_or_customer", "lead_activities", type_="check")
    op.drop_index("ix_lead_activities_customer_id", "lead_activities")
    op.drop_column("lead_activities", "contact_id")
    op.drop_column("lead_activities", "customer_id")
    op.alter_column("lead_activities", "lead_id", nullable=False)
    op.drop_column("partner_contacts", "is_primary")
    op.drop_column("partner_contacts", "whatsapp")
    op.drop_column("partner_contacts", "department")
