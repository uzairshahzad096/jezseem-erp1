"""leads module

Revision ID: 0022
Revises: 0021

New tables for the Leads module (app/leads): lead sources, leads and their
activities / follow-ups. A starting list of sources is added for each company
(Website, Referral, Existing Customer, Exhibition, Cold Call, WhatsApp / Phone,
Social Media, Walk-in) — a configuration list, edited on the Sources screen —
and the module's permissions are given to the Administrator role. No existing
table or row is changed.
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

SOURCES = ["Website", "Referral", "Existing Customer", "Exhibition", "Cold Call", "WhatsApp / Phone",
           "Social Media", "Walk-in"]
ACTIONS = ["view", "create", "edit", "delete", "approve", "post", "cancel", "export", "print"]
CODES = [(sub, action, f"leads.{sub}.{action}")
         for sub in ("view", "assignments", "sources", "followups") for action in ACTIONS]

DDL = [    'CREATE TABLE lead_sources (\n\tcompany_id UUID NOT NULL, \n\tname VARCHAR(100) NOT NULL, \n\tdescription TEXT, \n\tis_active BOOLEAN NOT NULL, \n\tsort_order INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_by UUID, \n\tupdated_by UUID, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_lead_source_name UNIQUE (company_id, name), \n\tFOREIGN KEY(company_id) REFERENCES companies (id), \n\tFOREIGN KEY(created_by) REFERENCES users (id), \n\tFOREIGN KEY(updated_by) REFERENCES users (id)\n)',
    'CREATE INDEX ix_lead_sources_company_id ON lead_sources (company_id)',
    'CREATE TABLE leads (\n\tcompany_id UUID NOT NULL, \n\tlead_number VARCHAR(30) NOT NULL, \n\tlead_date DATE NOT NULL, \n\ttitle VARCHAR(255) NOT NULL, \n\tcustomer_id UUID, \n\tcompany_name VARCHAR(200) NOT NULL, \n\tcontact_person VARCHAR(150), \n\tdesignation VARCHAR(100), \n\tphone VARCHAR(60), \n\temail VARCHAR(150), \n\tcity VARCHAR(100), \n\taddress TEXT, \n\tsource_id UUID, \n\tinterest VARCHAR(200), \n\titem_id UUID, \n\testimated_value NUMERIC(18, 2) NOT NULL, \n\tcurrency VARCHAR(10) NOT NULL, \n\texpected_close_date DATE, \n\tstage VARCHAR(20) NOT NULL, \n\trating VARCHAR(10) NOT NULL, \n\towner_id UUID, \n\tquotation_id UUID, \n\tlost_reason VARCHAR(100), \n\tclosed_at TIMESTAMP WITH TIME ZONE, \n\tremarks TEXT, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_by UUID, \n\tupdated_by UUID, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_lead_number UNIQUE (company_id, lead_number), \n\tFOREIGN KEY(company_id) REFERENCES companies (id), \n\tFOREIGN KEY(customer_id) REFERENCES business_partners (id), \n\tFOREIGN KEY(source_id) REFERENCES lead_sources (id), \n\tFOREIGN KEY(item_id) REFERENCES inventory_items (id), \n\tFOREIGN KEY(owner_id) REFERENCES users (id), \n\tFOREIGN KEY(quotation_id) REFERENCES sales_documents (id), \n\tFOREIGN KEY(created_by) REFERENCES users (id), \n\tFOREIGN KEY(updated_by) REFERENCES users (id)\n)',
    'CREATE INDEX ix_leads_company_id ON leads (company_id)',
    'CREATE INDEX ix_leads_customer_id ON leads (customer_id)',
    'CREATE INDEX ix_leads_lead_date ON leads (lead_date)',
    'CREATE INDEX ix_leads_owner_id ON leads (owner_id)',
    'CREATE INDEX ix_leads_source_id ON leads (source_id)',
    'CREATE INDEX ix_leads_stage ON leads (stage)',
    'CREATE TABLE lead_activities (\n\tlead_id UUID NOT NULL, \n\tactivity_type VARCHAR(30) NOT NULL, \n\tactivity_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tsummary TEXT NOT NULL, \n\toutcome TEXT, \n\tdue_date DATE, \n\tdone_at TIMESTAMP WITH TIME ZONE, \n\towner_id UUID, \n\tcreated_by UUID, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(lead_id) REFERENCES leads (id), \n\tFOREIGN KEY(owner_id) REFERENCES users (id), \n\tFOREIGN KEY(created_by) REFERENCES users (id)\n)',
    'CREATE INDEX ix_lead_activities_due_date ON lead_activities (due_date)',
    'CREATE INDEX ix_lead_activities_lead_id ON lead_activities (lead_id)',
    'CREATE INDEX ix_lead_activities_owner_id ON lead_activities (owner_id)',
]


def upgrade() -> None:
    bind = op.get_bind()
    for statement in DDL:
        bind.execute(sa.text(statement))
    for order, name in enumerate(SOURCES, start=1):
        bind.execute(sa.text("""
            insert into lead_sources (id, company_id, name, is_active, sort_order, created_at, updated_at)
            select gen_random_uuid(), c.id, :name, true, :sort, now(), now() from companies c
            on conflict do nothing
        """), {"name": name, "sort": order * 10})
    for _sub, action, code in CODES:
        bind.execute(sa.text("""
            insert into permissions (id, module, action, code) values (gen_random_uuid(), 'leads', :action, :code)
            on conflict (code) do nothing
        """), {"action": action, "code": code})
    bind.execute(sa.text("""
        insert into role_permissions (role_id, permission_id)
        select r.id, p.id from roles r cross join permissions p
        where r.name = 'Administrator' and p.code = any(:codes)
        on conflict do nothing
    """), {"codes": [c[2] for c in CODES]})


def downgrade() -> None:
    for table in ("lead_activities", "leads", "lead_sources"):
        op.drop_table(table)