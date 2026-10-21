"""calibration / services module

Revision ID: 0019
Revises: 0018

New tables for the Calibration / Services module (app/calibration): machine
definitions, customer machines, service contracts and their lines, service
invoices and their lines, calibration definitions with their tests, and
calibration reports with their results. No existing table or row is changed,
apart from the module's permissions being added to the Administrator role.
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

ACTIONS = ["view", "create", "edit", "delete", "approve", "post", "cancel", "export", "print"]
SUBMODULES = ["machines", "customer_machines", "contracts", "invoices", "definitions", "reports"]
CODES = [(sub, action, f"calibration.{sub}.{action}") for sub in SUBMODULES for action in ACTIONS]
NEW_SUBMODULES = [s for s in SUBMODULES if s != "reports"]

TABLES = ["svc_machine_definitions", "svc_customer_machines", "svc_contracts", "svc_contract_lines",
          "svc_calibration_definitions", "svc_calibration_tests", "svc_calibration_reports",
          "svc_calibration_results", "svc_invoices", "svc_invoice_lines"]

DDL = [    'CREATE TABLE svc_machine_definitions (\n\tcompany_id UUID NOT NULL, \n\tmachine_category VARCHAR(150) NOT NULL, \n\tvendor_name VARCHAR(150) NOT NULL, \n\tmodel_number VARCHAR(150) NOT NULL, \n\torigin VARCHAR(100), \n\tdescription TEXT, \n\tremarks TEXT, \n\tactive BOOLEAN NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_by UUID, \n\tupdated_by UUID, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(company_id) REFERENCES companies (id), \n\tFOREIGN KEY(created_by) REFERENCES users (id), \n\tFOREIGN KEY(updated_by) REFERENCES users (id)\n)',
    'CREATE INDEX ix_svc_machine_definitions_company_id ON svc_machine_definitions (company_id)',
    'CREATE TABLE svc_customer_machines (\n\tcompany_id UUID NOT NULL, \n\tcustomer_id UUID NOT NULL, \n\tmachine_definition_id UUID NOT NULL, \n\tmachine_code VARCHAR(100), \n\tserial_number VARCHAR(100), \n\tinstallation_date DATE, \n\tmachine_status VARCHAR(30) NOT NULL, \n\tmachine_location VARCHAR(150), \n\tremarks TEXT, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_by UUID, \n\tupdated_by UUID, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(company_id) REFERENCES companies (id), \n\tFOREIGN KEY(customer_id) REFERENCES business_partners (id), \n\tFOREIGN KEY(machine_definition_id) REFERENCES svc_machine_definitions (id), \n\tFOREIGN KEY(created_by) REFERENCES users (id), \n\tFOREIGN KEY(updated_by) REFERENCES users (id)\n)',
    'CREATE INDEX ix_svc_customer_machines_company_id ON svc_customer_machines (company_id)',
    'CREATE INDEX ix_svc_customer_machines_machine_definition_id ON svc_customer_machines (machine_definition_id)',
    'CREATE INDEX ix_svc_customer_machines_customer_id ON svc_customer_machines (customer_id)',
    'CREATE TABLE svc_contracts (\n\tcompany_id UUID NOT NULL, \n\tcontract_number VARCHAR(50) NOT NULL, \n\treference VARCHAR(100), \n\tcontract_date DATE NOT NULL, \n\tcustomer_id UUID NOT NULL, \n\tcontract_type VARCHAR(40) NOT NULL, \n\tdivision VARCHAR(150), \n\tstart_date DATE NOT NULL, \n\tend_date DATE, \n\tbilling_frequency VARCHAR(20) NOT NULL, \n\tcurrency VARCHAR(10) NOT NULL, \n\tcharge_amount NUMERIC(18, 2) NOT NULL, \n\ttax_applicable BOOLEAN NOT NULL, \n\ttax_percent NUMERIC(9, 4) NOT NULL, \n\twithout_tax_deduction BOOLEAN NOT NULL, \n\tresponse_hours INTEGER, \n\tspare_parts_by VARCHAR(30), \n\tservice_coverage TEXT, \n\tadditional_terms TEXT, \n\tcontract_status VARCHAR(20) NOT NULL, \n\tcontract_owner VARCHAR(150), \n\tremarks TEXT, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_by UUID, \n\tupdated_by UUID, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_svc_contract_number UNIQUE (company_id, contract_number), \n\tFOREIGN KEY(company_id) REFERENCES companies (id), \n\tFOREIGN KEY(customer_id) REFERENCES business_partners (id), \n\tFOREIGN KEY(created_by) REFERENCES users (id), \n\tFOREIGN KEY(updated_by) REFERENCES users (id)\n)',
    'CREATE INDEX ix_svc_contracts_customer_id ON svc_contracts (customer_id)',
    'CREATE INDEX ix_svc_contracts_company_id ON svc_contracts (company_id)',
    'CREATE TABLE svc_contract_lines (\n\tcontract_id UUID NOT NULL, \n\tline_number INTEGER NOT NULL, \n\tcustomer_machine_id UUID, \n\tdescription TEXT NOT NULL, \n\tservice_type VARCHAR(40), \n\tquantity NUMERIC(18, 4) NOT NULL, \n\tremarks TEXT, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(contract_id) REFERENCES svc_contracts (id), \n\tFOREIGN KEY(customer_machine_id) REFERENCES svc_customer_machines (id)\n)',
    'CREATE INDEX ix_svc_contract_lines_contract_id ON svc_contract_lines (contract_id)',
    'CREATE INDEX ix_svc_contract_lines_customer_machine_id ON svc_contract_lines (customer_machine_id)',
    'CREATE TABLE svc_calibration_definitions (\n\tcompany_id UUID NOT NULL, \n\tmachine_definition_id UUID NOT NULL, \n\tdefinition_name VARCHAR(200) NOT NULL, \n\tversion_number INTEGER NOT NULL, \n\tvalidity_days INTEGER NOT NULL, \n\teffective_from DATE, \n\teffective_to DATE, \n\tdefault_temperature VARCHAR(100), \n\tdefault_relative_humidity VARCHAR(100), \n\tdefault_main_voltage VARCHAR(100), \n\tdefault_main_frequency VARCHAR(100), \n\tdefault_noise_level VARCHAR(100), \n\tactive BOOLEAN NOT NULL, \n\tstandard_comments TEXT, \n\tstandard_note TEXT, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_by UUID, \n\tupdated_by UUID, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(company_id) REFERENCES companies (id), \n\tFOREIGN KEY(machine_definition_id) REFERENCES svc_machine_definitions (id), \n\tFOREIGN KEY(created_by) REFERENCES users (id), \n\tFOREIGN KEY(updated_by) REFERENCES users (id)\n)',
    'CREATE INDEX ix_svc_calibration_definitions_company_id ON svc_calibration_definitions (company_id)',
    'CREATE INDEX ix_svc_calibration_definitions_machine_definition_id ON svc_calibration_definitions (machine_definition_id)',
    'CREATE TABLE svc_calibration_tests (\n\tdefinition_id UUID NOT NULL, \n\tseq INTEGER NOT NULL, \n\ttest_title VARCHAR(255) NOT NULL, \n\texpected_result VARCHAR(255), \n\tunit VARCHAR(50), \n\tactive BOOLEAN NOT NULL, \n\tremarks TEXT, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(definition_id) REFERENCES svc_calibration_definitions (id)\n)',
    'CREATE INDEX ix_svc_calibration_tests_definition_id ON svc_calibration_tests (definition_id)',
    'CREATE TABLE svc_calibration_reports (\n\tcompany_id UUID NOT NULL, \n\tcertificate_number VARCHAR(80) NOT NULL, \n\tcustomer_id UUID NOT NULL, \n\tcustomer_machine_id UUID NOT NULL, \n\tcalibration_definition_id UUID NOT NULL, \n\tcontract_id UUID, \n\tcontract_line_id UUID, \n\tcalibration_date DATE NOT NULL, \n\tissue_date DATE NOT NULL, \n\texpiry_date DATE NOT NULL, \n\tnext_calibration_date DATE, \n\ttechnician_name VARCHAR(150), \n\toverall_result VARCHAR(20) NOT NULL, \n\treport_status VARCHAR(20) NOT NULL, \n\ttemperature VARCHAR(100), \n\trelative_humidity VARCHAR(100), \n\tmain_voltage VARCHAR(100), \n\tmain_frequency VARCHAR(100), \n\tnoise_level VARCHAR(100), \n\tcomments TEXT, \n\tnote TEXT, \n\tremarks TEXT, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_by UUID, \n\tupdated_by UUID, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_svc_certificate_number UNIQUE (company_id, certificate_number), \n\tFOREIGN KEY(company_id) REFERENCES companies (id), \n\tFOREIGN KEY(customer_id) REFERENCES business_partners (id), \n\tFOREIGN KEY(customer_machine_id) REFERENCES svc_customer_machines (id), \n\tFOREIGN KEY(calibration_definition_id) REFERENCES svc_calibration_definitions (id), \n\tFOREIGN KEY(contract_id) REFERENCES svc_contracts (id), \n\tFOREIGN KEY(contract_line_id) REFERENCES svc_contract_lines (id), \n\tFOREIGN KEY(created_by) REFERENCES users (id), \n\tFOREIGN KEY(updated_by) REFERENCES users (id)\n)',
    'CREATE INDEX ix_svc_calibration_reports_calibration_date ON svc_calibration_reports (calibration_date)',
    'CREATE INDEX ix_svc_calibration_reports_customer_id ON svc_calibration_reports (customer_id)',
    'CREATE INDEX ix_svc_calibration_reports_customer_machine_id ON svc_calibration_reports (customer_machine_id)',
    'CREATE INDEX ix_svc_calibration_reports_company_id ON svc_calibration_reports (company_id)',
    'CREATE INDEX ix_svc_calibration_reports_contract_id ON svc_calibration_reports (contract_id)',
    'CREATE TABLE svc_calibration_results (\n\treport_id UUID NOT NULL, \n\tseq INTEGER NOT NULL, \n\ttest_title VARCHAR(255) NOT NULL, \n\texpected_result VARCHAR(255), \n\tunit VARCHAR(50), \n\tinitial_reading VARCHAR(100), \n\tobserved VARCHAR(100), \n\tuncertainty VARCHAR(100), \n\tpassed BOOLEAN, \n\tremarks TEXT, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(report_id) REFERENCES svc_calibration_reports (id)\n)',
    'CREATE INDEX ix_svc_calibration_results_report_id ON svc_calibration_results (report_id)',
    'CREATE TABLE svc_invoices (\n\tcompany_id UUID NOT NULL, \n\tbranch_id UUID, \n\tinvoice_number VARCHAR(50) NOT NULL, \n\tinvoice_date DATE NOT NULL, \n\tdue_date DATE, \n\tcustomer_id UUID NOT NULL, \n\tcontract_id UUID, \n\tservice_type VARCHAR(40) NOT NULL, \n\tperiod_from DATE, \n\tperiod_to DATE, \n\tcustomer_po_number VARCHAR(100), \n\tcurrency VARCHAR(10) NOT NULL, \n\texchange_rate NUMERIC(18, 6), \n\tpayment_terms VARCHAR(255), \n\tremarks TEXT, \n\tstatus VARCHAR(20) NOT NULL, \n\texcluding_tax_value NUMERIC(18, 2) NOT NULL, \n\tsales_tax_value NUMERIC(18, 2) NOT NULL, \n\tgross_amount NUMERIC(18, 2) NOT NULL, \n\tdiscount_amount NUMERIC(18, 2) NOT NULL, \n\tnet_receivable NUMERIC(18, 2) NOT NULL, \n\tjournal_entry_id UUID, \n\tposted_by UUID, \n\tposted_at TIMESTAMP WITH TIME ZONE, \n\tcancelled_by UUID, \n\tcancelled_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tcreated_by UUID, \n\tupdated_by UUID, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_svc_invoice_number UNIQUE (company_id, invoice_number), \n\tFOREIGN KEY(company_id) REFERENCES companies (id), \n\tFOREIGN KEY(branch_id) REFERENCES branches (id), \n\tFOREIGN KEY(customer_id) REFERENCES business_partners (id), \n\tFOREIGN KEY(contract_id) REFERENCES svc_contracts (id), \n\tFOREIGN KEY(journal_entry_id) REFERENCES journal_entries (id), \n\tFOREIGN KEY(posted_by) REFERENCES users (id), \n\tFOREIGN KEY(cancelled_by) REFERENCES users (id), \n\tFOREIGN KEY(created_by) REFERENCES users (id), \n\tFOREIGN KEY(updated_by) REFERENCES users (id)\n)',
    'CREATE INDEX ix_svc_invoices_company_id ON svc_invoices (company_id)',
    'CREATE INDEX ix_svc_invoices_customer_id ON svc_invoices (customer_id)',
    'CREATE INDEX ix_svc_invoices_branch_id ON svc_invoices (branch_id)',
    'CREATE INDEX ix_svc_invoices_status ON svc_invoices (status)',
    'CREATE INDEX ix_svc_invoices_invoice_date ON svc_invoices (invoice_date)',
    'CREATE INDEX ix_svc_invoices_contract_id ON svc_invoices (contract_id)',
    'CREATE TABLE svc_invoice_lines (\n\tinvoice_id UUID NOT NULL, \n\tline_number INTEGER NOT NULL, \n\tcustomer_machine_id UUID, \n\tcalibration_report_id UUID, \n\tdescription TEXT NOT NULL, \n\tquantity NUMERIC(18, 4) NOT NULL, \n\tunit_price NUMERIC(18, 4) NOT NULL, \n\tdiscount_percent NUMERIC(9, 4) NOT NULL, \n\ttax_percent NUMERIC(9, 4) NOT NULL, \n\tgross_amount NUMERIC(18, 2) NOT NULL, \n\tdiscount_amount NUMERIC(18, 2) NOT NULL, \n\ttaxable_amount NUMERIC(18, 2) NOT NULL, \n\ttax_amount NUMERIC(18, 2) NOT NULL, \n\tnet_amount NUMERIC(18, 2) NOT NULL, \n\tid UUID NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(invoice_id) REFERENCES svc_invoices (id), \n\tFOREIGN KEY(customer_machine_id) REFERENCES svc_customer_machines (id), \n\tFOREIGN KEY(calibration_report_id) REFERENCES svc_calibration_reports (id)\n)',
    'CREATE INDEX ix_svc_invoice_lines_calibration_report_id ON svc_invoice_lines (calibration_report_id)',
    'CREATE INDEX ix_svc_invoice_lines_customer_machine_id ON svc_invoice_lines (customer_machine_id)',
    'CREATE INDEX ix_svc_invoice_lines_invoice_id ON svc_invoice_lines (invoice_id)',
]


def upgrade() -> None:
    bind = op.get_bind()
    for statement in DDL:
        bind.execute(sa.text(statement))
    for _sub, action, code in CODES:
        bind.execute(sa.text("""
            insert into permissions (id, module, action, code)
            values (gen_random_uuid(), 'calibration', :action, :code)
            on conflict (code) do nothing
        """), {"action": action, "code": code})
    bind.execute(sa.text("""
        insert into role_permissions (role_id, permission_id)
        select r.id, p.id from roles r cross join permissions p
        where r.name = 'Administrator' and p.code = any(:codes)
        on conflict do nothing
    """), {"codes": [c[2] for c in CODES]})


def downgrade() -> None:
    bind = op.get_bind()
    codes = [c[2] for c in CODES if c[0] in NEW_SUBMODULES]
    bind.execute(sa.text("delete from role_permissions where permission_id in "
                         "(select id from permissions where code = any(:c))"), {"c": codes})
    bind.execute(sa.text("delete from permissions where code = any(:c)"), {"c": codes})
    for table in reversed(TABLES):
        op.drop_table(table)