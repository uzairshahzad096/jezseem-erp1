"""HRMS: employees, attendance, leave, loans and payroll

Revision ID: 0011
Revises: 0010

Everything here is new: eighteen `hr_` tables and the HRMS permissions. No
existing table is changed and no existing row is touched.

    setup        hr_settings, hr_departments, hr_designations, hr_shifts,
                 hr_holidays, hr_leave_types, hr_salary_components
    employees    hr_employees, hr_salary_structures (+ lines)
    attendance   hr_attendance
    leave        hr_leave_balances, hr_leave_requests
    loans        hr_loans, hr_loan_repayments
    payroll      hr_payroll_runs, hr_payslips (+ lines)

No employee, salary, rate or balance is inserted. The standard departments,
leave types and salary components are added from the HR Setup screen (or by
the seed command), so a figure is only ever there because someone chose it.
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

#: Submodules already in the permission catalogue (employees, attendance,
#: leave, payroll) get their codes from the seed; these two are new.
ACTIONS = ["view", "create", "edit", "delete", "approve", "post", "cancel", "export", "print"]
SUBMODULES = ["employees", "attendance", "leave", "payroll", "setup", "loans"]
PERMISSIONS = [("hrms", "view", "hrms.module.view")] + [
    ("hrms", action, f"hrms.{sub}.{action}") for sub in SUBMODULES for action in ACTIONS]

CHECKS = [
    ("hr_employees", "ck_hr_employee_status", "status in ('ACTIVE','INACTIVE','RESIGNED','TERMINATED')"),
    ("hr_employees", "ck_hr_employee_payment_mode", "payment_mode in ('BANK','CASH','CHEQUE')"),
    ("hr_attendance", "ck_hr_attendance_status",
     "status in ('PRESENT','ABSENT','LATE','HALF_DAY','LEAVE','HOLIDAY','WEEKLY_OFF')"),
    ("hr_leave_requests", "ck_hr_leave_request_status", "status in ('PENDING','APPROVED','REJECTED','CANCELLED')"),
    ("hr_leave_requests", "ck_hr_leave_request_dates", "to_date >= from_date"),
    ("hr_salary_components", "ck_hr_salary_component_kind", "kind in ('EARNING','DEDUCTION')"),
    ("hr_salary_structures", "ck_hr_salary_basic", "basic_salary >= 0"),
    ("hr_loans", "ck_hr_loan_amounts", "amount > 0 and installment_amount > 0"),
    ("hr_loans", "ck_hr_loan_status", "status in ('ACTIVE','SETTLED','CANCELLED')"),
    ("hr_loan_repayments", "ck_hr_loan_repayment_amount", "amount > 0"),
    ("hr_payroll_runs", "ck_hr_payroll_status", "status in ('DRAFT','APPROVED','PAID','CANCELLED')"),
    ("hr_payroll_runs", "ck_hr_payroll_month", "period_month between 1 and 12"),
    ("hr_payslip_lines", "ck_hr_payslip_line_kind", "kind in ('EARNING','DEDUCTION')"),
]

TABLES = ['hr_departments', 'hr_designations', 'hr_holidays', 'hr_leave_types', 'hr_payroll_runs', 'hr_salary_components', 'hr_settings', 'hr_shifts', 'hr_employees', 'hr_leave_balances', 'hr_leave_requests', 'hr_loans', 'hr_payslips', 'hr_salary_structures', 'hr_attendance', 'hr_loan_repayments', 'hr_payslip_lines', 'hr_salary_structure_lines']


def upgrade() -> None:
    op.create_table('hr_departments',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('head_id', sa.UUID(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['parent_id'], ['hr_departments.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'code', name='uq_hr_department_code')
    )
    op.create_index(op.f('ix_hr_departments_company_id'), 'hr_departments', ['company_id'], unique=False)
    op.create_index(op.f('ix_hr_departments_head_id'), 'hr_departments', ['head_id'], unique=False)
    op.create_index(op.f('ix_hr_departments_parent_id'), 'hr_departments', ['parent_id'], unique=False)
    op.create_table('hr_designations',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('grade', sa.String(length=30), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'code', name='uq_hr_designation_code')
    )
    op.create_index(op.f('ix_hr_designations_company_id'), 'hr_designations', ['company_id'], unique=False)
    op.create_table('hr_holidays',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('holiday_date', sa.Date(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'holiday_date', name='uq_hr_holiday_date')
    )
    op.create_index(op.f('ix_hr_holidays_company_id'), 'hr_holidays', ['company_id'], unique=False)
    op.create_index(op.f('ix_hr_holidays_holiday_date'), 'hr_holidays', ['holiday_date'], unique=False)
    op.create_table('hr_leave_types',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('annual_days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('is_paid', sa.Boolean(), nullable=False),
    sa.Column('carry_forward', sa.Boolean(), nullable=False),
    sa.Column('max_carry_days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'code', name='uq_hr_leave_type_code')
    )
    op.create_index(op.f('ix_hr_leave_types_company_id'), 'hr_leave_types', ['company_id'], unique=False)
    op.create_table('hr_payroll_runs',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('run_number', sa.String(length=30), nullable=False),
    sa.Column('period_year', sa.Integer(), nullable=False),
    sa.Column('period_month', sa.Integer(), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('employee_count', sa.Integer(), nullable=False),
    sa.Column('total_earnings', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('total_deductions', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('total_net', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('approved_by', sa.UUID(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('paid_by', sa.UUID(), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('payment_date', sa.Date(), nullable=True),
    sa.Column('cancel_reason', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['paid_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_hr_payroll_runs_company_id'), 'hr_payroll_runs', ['company_id'], unique=False)
    op.create_index(op.f('ix_hr_payroll_runs_status'), 'hr_payroll_runs', ['status'], unique=False)
    op.create_index('uq_hr_payroll_month', 'hr_payroll_runs', ['company_id', 'period_year', 'period_month'], unique=True, postgresql_where=sa.text("status <> 'CANCELLED'"))
    op.create_table('hr_salary_components',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('calc_type', sa.String(length=16), nullable=False),
    sa.Column('default_value', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'code', name='uq_hr_salary_component_code')
    )
    op.create_index(op.f('ix_hr_salary_components_company_id'), 'hr_salary_components', ['company_id'], unique=False)
    op.create_table('hr_settings',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('week_off_days', sa.String(length=40), nullable=False),
    sa.Column('unmarked_day_policy', sa.String(length=10), nullable=False),
    sa.Column('salary_days_basis', sa.String(length=12), nullable=False),
    sa.Column('hours_per_day', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('overtime_multiplier', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('lates_per_absence', sa.Integer(), nullable=False),
    sa.Column('employee_code_prefix', sa.String(length=10), nullable=False),
    sa.Column('employee_code_digits', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id')
    )
    op.create_table('hr_shifts',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=False),
    sa.Column('end_time', sa.Time(), nullable=False),
    sa.Column('grace_minutes', sa.Integer(), nullable=False),
    sa.Column('break_minutes', sa.Integer(), nullable=False),
    sa.Column('working_days', sa.String(length=40), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'code', name='uq_hr_shift_code')
    )
    op.create_index(op.f('ix_hr_shifts_company_id'), 'hr_shifts', ['company_id'], unique=False)
    op.create_table('hr_employees',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('branch_id', sa.UUID(), nullable=True),
    sa.Column('employee_code', sa.String(length=30), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('father_name', sa.String(length=200), nullable=True),
    sa.Column('gender', sa.String(length=10), nullable=True),
    sa.Column('date_of_birth', sa.Date(), nullable=True),
    sa.Column('marital_status', sa.String(length=20), nullable=True),
    sa.Column('blood_group', sa.String(length=5), nullable=True),
    sa.Column('cnic', sa.String(length=20), nullable=True),
    sa.Column('cnic_expiry', sa.Date(), nullable=True),
    sa.Column('phone', sa.String(length=40), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('city', sa.String(length=100), nullable=True),
    sa.Column('emergency_contact_name', sa.String(length=200), nullable=True),
    sa.Column('emergency_contact_phone', sa.String(length=40), nullable=True),
    sa.Column('department_id', sa.UUID(), nullable=True),
    sa.Column('designation_id', sa.UUID(), nullable=True),
    sa.Column('shift_id', sa.UUID(), nullable=True),
    sa.Column('manager_id', sa.UUID(), nullable=True),
    sa.Column('employment_type', sa.String(length=20), nullable=False),
    sa.Column('joining_date', sa.Date(), nullable=False),
    sa.Column('probation_end_date', sa.Date(), nullable=True),
    sa.Column('confirmation_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('separation_date', sa.Date(), nullable=True),
    sa.Column('separation_reason', sa.Text(), nullable=True),
    sa.Column('payment_mode', sa.String(length=10), nullable=False),
    sa.Column('bank_name', sa.String(length=150), nullable=True),
    sa.Column('bank_account_title', sa.String(length=200), nullable=True),
    sa.Column('bank_account_number', sa.String(length=60), nullable=True),
    sa.Column('iban', sa.String(length=40), nullable=True),
    sa.Column('ntn', sa.String(length=30), nullable=True),
    sa.Column('eobi_number', sa.String(length=30), nullable=True),
    sa.Column('social_security_number', sa.String(length=30), nullable=True),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.id'], ),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['department_id'], ['hr_departments.id'], ),
    sa.ForeignKeyConstraint(['designation_id'], ['hr_designations.id'], ),
    sa.ForeignKeyConstraint(['manager_id'], ['hr_employees.id'], ),
    sa.ForeignKeyConstraint(['shift_id'], ['hr_shifts.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'employee_code', name='uq_hr_employee_code')
    )
    op.create_index(op.f('ix_hr_employees_branch_id'), 'hr_employees', ['branch_id'], unique=False)
    op.create_index(op.f('ix_hr_employees_cnic'), 'hr_employees', ['cnic'], unique=False)
    op.create_index(op.f('ix_hr_employees_company_id'), 'hr_employees', ['company_id'], unique=False)
    op.create_index(op.f('ix_hr_employees_department_id'), 'hr_employees', ['department_id'], unique=False)
    op.create_index(op.f('ix_hr_employees_designation_id'), 'hr_employees', ['designation_id'], unique=False)
    op.create_index(op.f('ix_hr_employees_employee_code'), 'hr_employees', ['employee_code'], unique=False)
    op.create_index(op.f('ix_hr_employees_full_name'), 'hr_employees', ['full_name'], unique=False)
    op.create_index(op.f('ix_hr_employees_manager_id'), 'hr_employees', ['manager_id'], unique=False)
    op.create_index(op.f('ix_hr_employees_shift_id'), 'hr_employees', ['shift_id'], unique=False)
    op.create_index(op.f('ix_hr_employees_status'), 'hr_employees', ['status'], unique=False)
    op.create_index(op.f('ix_hr_employees_user_id'), 'hr_employees', ['user_id'], unique=False)
    op.create_table('hr_leave_balances',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('leave_type_id', sa.UUID(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('entitled', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('carried_forward', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('adjustment', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('adjustment_note', sa.String(length=255), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['employee_id'], ['hr_employees.id'], ),
    sa.ForeignKeyConstraint(['leave_type_id'], ['hr_leave_types.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_id', 'leave_type_id', 'year', name='uq_hr_leave_balance')
    )
    op.create_index(op.f('ix_hr_leave_balances_company_id'), 'hr_leave_balances', ['company_id'], unique=False)
    op.create_index(op.f('ix_hr_leave_balances_employee_id'), 'hr_leave_balances', ['employee_id'], unique=False)
    op.create_index(op.f('ix_hr_leave_balances_leave_type_id'), 'hr_leave_balances', ['leave_type_id'], unique=False)
    op.create_table('hr_leave_requests',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('request_number', sa.String(length=30), nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('leave_type_id', sa.UUID(), nullable=False),
    sa.Column('from_date', sa.Date(), nullable=False),
    sa.Column('to_date', sa.Date(), nullable=False),
    sa.Column('half_day', sa.Boolean(), nullable=False),
    sa.Column('days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('decided_by', sa.UUID(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['employee_id'], ['hr_employees.id'], ),
    sa.ForeignKeyConstraint(['leave_type_id'], ['hr_leave_types.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'request_number', name='uq_hr_leave_request_number')
    )
    op.create_index(op.f('ix_hr_leave_requests_company_id'), 'hr_leave_requests', ['company_id'], unique=False)
    op.create_index(op.f('ix_hr_leave_requests_employee_id'), 'hr_leave_requests', ['employee_id'], unique=False)
    op.create_index(op.f('ix_hr_leave_requests_from_date'), 'hr_leave_requests', ['from_date'], unique=False)
    op.create_index(op.f('ix_hr_leave_requests_leave_type_id'), 'hr_leave_requests', ['leave_type_id'], unique=False)
    op.create_index(op.f('ix_hr_leave_requests_status'), 'hr_leave_requests', ['status'], unique=False)
    op.create_table('hr_loans',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('loan_number', sa.String(length=30), nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('loan_date', sa.Date(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('installment_amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('recovery_start', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['employee_id'], ['hr_employees.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'loan_number', name='uq_hr_loan_number')
    )
    op.create_index(op.f('ix_hr_loans_company_id'), 'hr_loans', ['company_id'], unique=False)
    op.create_index(op.f('ix_hr_loans_employee_id'), 'hr_loans', ['employee_id'], unique=False)
    op.create_index(op.f('ix_hr_loans_status'), 'hr_loans', ['status'], unique=False)
    op.create_table('hr_payslips',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('employee_code', sa.String(length=30), nullable=False),
    sa.Column('employee_name', sa.String(length=200), nullable=False),
    sa.Column('department', sa.String(length=150), nullable=True),
    sa.Column('designation', sa.String(length=150), nullable=True),
    sa.Column('payment_mode', sa.String(length=10), nullable=False),
    sa.Column('bank_name', sa.String(length=150), nullable=True),
    sa.Column('bank_account_title', sa.String(length=200), nullable=True),
    sa.Column('bank_account_number', sa.String(length=60), nullable=True),
    sa.Column('days_in_period', sa.Integer(), nullable=False),
    sa.Column('present_days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('absent_days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('paid_leave_days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('unpaid_leave_days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('holidays', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('weekly_offs', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('not_employed_days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('unmarked_days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('late_count', sa.Integer(), nullable=False),
    sa.Column('unpaid_days', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('overtime_hours', sa.Numeric(precision=8, scale=2), nullable=False),
    sa.Column('basic_salary', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('gross_salary', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('total_earnings', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('total_deductions', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('net_pay', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('warnings', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['employee_id'], ['hr_employees.id'], ),
    sa.ForeignKeyConstraint(['run_id'], ['hr_payroll_runs.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('run_id', 'employee_id', name='uq_hr_payslip_employee')
    )
    op.create_index(op.f('ix_hr_payslips_company_id'), 'hr_payslips', ['company_id'], unique=False)
    op.create_index(op.f('ix_hr_payslips_employee_id'), 'hr_payslips', ['employee_id'], unique=False)
    op.create_index(op.f('ix_hr_payslips_run_id'), 'hr_payslips', ['run_id'], unique=False)
    op.create_table('hr_salary_structures',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('basic_salary', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('remarks', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['employee_id'], ['hr_employees.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_id', 'effective_from', name='uq_hr_salary_effective')
    )
    op.create_index(op.f('ix_hr_salary_structures_company_id'), 'hr_salary_structures', ['company_id'], unique=False)
    op.create_index(op.f('ix_hr_salary_structures_employee_id'), 'hr_salary_structures', ['employee_id'], unique=False)
    op.create_table('hr_attendance',
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('work_date', sa.Date(), nullable=False),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('check_in', sa.Time(), nullable=True),
    sa.Column('check_out', sa.Time(), nullable=True),
    sa.Column('worked_minutes', sa.Integer(), nullable=False),
    sa.Column('late_minutes', sa.Integer(), nullable=False),
    sa.Column('overtime_minutes', sa.Integer(), nullable=False),
    sa.Column('leave_request_id', sa.UUID(), nullable=True),
    sa.Column('remarks', sa.String(length=255), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['employee_id'], ['hr_employees.id'], ),
    sa.ForeignKeyConstraint(['leave_request_id'], ['hr_leave_requests.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_id', 'work_date', name='uq_hr_attendance_day')
    )
    op.create_index(op.f('ix_hr_attendance_company_id'), 'hr_attendance', ['company_id'], unique=False)
    op.create_index(op.f('ix_hr_attendance_employee_id'), 'hr_attendance', ['employee_id'], unique=False)
    op.create_index(op.f('ix_hr_attendance_leave_request_id'), 'hr_attendance', ['leave_request_id'], unique=False)
    op.create_index(op.f('ix_hr_attendance_work_date'), 'hr_attendance', ['work_date'], unique=False)
    op.create_table('hr_loan_repayments',
    sa.Column('loan_id', sa.UUID(), nullable=False),
    sa.Column('paid_on', sa.Date(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.Column('payslip_id', sa.UUID(), nullable=True),
    sa.Column('is_reversed', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.String(length=255), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['loan_id'], ['hr_loans.id'], ),
    sa.ForeignKeyConstraint(['payslip_id'], ['hr_payslips.id'], ),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_hr_loan_repayments_loan_id'), 'hr_loan_repayments', ['loan_id'], unique=False)
    op.create_index(op.f('ix_hr_loan_repayments_payslip_id'), 'hr_loan_repayments', ['payslip_id'], unique=False)
    op.create_table('hr_payslip_lines',
    sa.Column('payslip_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('kind', sa.String(length=12), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('is_manual', sa.Boolean(), nullable=False),
    sa.Column('loan_id', sa.UUID(), nullable=True),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['loan_id'], ['hr_loans.id'], ),
    sa.ForeignKeyConstraint(['payslip_id'], ['hr_payslips.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_hr_payslip_lines_loan_id'), 'hr_payslip_lines', ['loan_id'], unique=False)
    op.create_index(op.f('ix_hr_payslip_lines_payslip_id'), 'hr_payslip_lines', ['payslip_id'], unique=False)
    op.create_table('hr_salary_structure_lines',
    sa.Column('structure_id', sa.UUID(), nullable=False),
    sa.Column('component_id', sa.UUID(), nullable=False),
    sa.Column('calc_type', sa.String(length=16), nullable=False),
    sa.Column('value', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['component_id'], ['hr_salary_components.id'], ),
    sa.ForeignKeyConstraint(['structure_id'], ['hr_salary_structures.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('structure_id', 'component_id', name='uq_hr_salary_line_component')
    )
    op.create_index(op.f('ix_hr_salary_structure_lines_component_id'), 'hr_salary_structure_lines', ['component_id'], unique=False)
    op.create_index(op.f('ix_hr_salary_structure_lines_structure_id'), 'hr_salary_structure_lines', ['structure_id'], unique=False)

    # A department's head is an employee, and an employee sits in a
    # department: the second half of that circle is added once both exist.
    op.create_foreign_key("fk_hr_department_head", "hr_departments", "hr_employees", ["head_id"], ["id"])
    for table, name, rule in CHECKS:
        op.create_check_constraint(name, table, rule)

    bind = op.get_bind()
    for module, action, code in PERMISSIONS:
        bind.execute(sa.text("""
            insert into permissions (id, module, action, code)
            values (gen_random_uuid(), :module, :action, :code)
            on conflict (code) do nothing
        """), {"module": module, "action": action, "code": code})
    bind.execute(sa.text("""
        insert into role_permissions (role_id, permission_id)
        select r.id, p.id from roles r cross join permissions p
        where r.name = 'Administrator' and p.code = any(:codes)
        on conflict do nothing
    """), {"codes": [p[2] for p in PERMISSIONS]})


def downgrade() -> None:
    bind = op.get_bind()
    # Only the codes this revision introduced; the rest belong to the seed.
    codes = [p[2] for p in PERMISSIONS if p[2].split(".")[1] in ("setup", "loans")]
    bind.execute(sa.text("delete from role_permissions where permission_id in "
                         "(select id from permissions where code = any(:c))"), {"c": codes})
    bind.execute(sa.text("delete from permissions where code = any(:c)"), {"c": codes})
    op.drop_constraint("fk_hr_department_head", "hr_departments", type_="foreignkey")
    for table in reversed(TABLES):
        op.drop_table(table)
