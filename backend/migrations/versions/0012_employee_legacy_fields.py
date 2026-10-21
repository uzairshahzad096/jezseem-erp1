"""employee fields carried over from the previous ERP's employee form

Revision ID: 0012
Revises: 0011

Adds columns to `hr_employees` only: the Basic / Official / Personal /
Confidential fields the old ERP's form has and the first version of the
employee table did not. Every new column is nullable or has a default, so
existing rows are unaffected.
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

MONEY = sa.Numeric(18, 2)


def flag(name: str, default: bool = False) -> sa.Column:
    return sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true() if default else sa.false())


COLUMNS = [
    # Basic information
    sa.Column("replacement_employee_id", sa.UUID(), nullable=True),
    sa.Column("father_occupation", sa.String(150)),
    sa.Column("mother_name", sa.String(200)),
    sa.Column("sub_department_id", sa.UUID(), nullable=True),
    sa.Column("weekly_rest", sa.String(3)),
    flag("orientation_done"),
    sa.Column("orientation_date", sa.Date()),
    sa.Column("orientation_remarks", sa.Text()),
    flag("eobi_registered"),
    flag("social_security_registered"),
    flag("attendance_exempt"),
    flag("group_insurance"),
    sa.Column("photo_path", sa.String(255)),
    # Official information
    flag("is_confirmed"),
    sa.Column("vacancy_date", sa.Date()),
    sa.Column("probation_months", sa.Integer()),
    sa.Column("probation_extend_months", sa.Integer()),
    flag("mobile_allowed", default=True),
    sa.Column("official_email", sa.String(255)),
    sa.Column("grade", sa.String(30)),
    flag("late_allowed"),
    # Personal information
    sa.Column("father_cnic", sa.String(20)),
    sa.Column("cnic_issue_date", sa.Date()),
    sa.Column("nationality", sa.String(60)),
    sa.Column("birth_place", sa.String(100)),
    sa.Column("phone_landline", sa.String(40)),
    sa.Column("hepatitis_status", sa.String(20)),
    sa.Column("caste", sa.String(60)),
    sa.Column("children_count", sa.Integer()),
    sa.Column("religion", sa.String(40)),
    # Confidential information
    flag("provident_fund_allowed"),
    flag("overtime_allowed"),
    sa.Column("ledger_account_id", sa.UUID(), nullable=True),
    sa.Column("wages_account_id", sa.UUID(), nullable=True),
    sa.Column("handicap", sa.String(100)),
    sa.Column("mileage", sa.Numeric(12, 2)),
    sa.Column("fixed_fuel_amount", MONEY),
    sa.Column("taxable_salary", MONEY),
    sa.Column("overtime_salary", MONEY),
    sa.Column("shift_premium", MONEY),
    flag("annual_allowance"),
    sa.Column("resign_notice_start", sa.Date()),
    sa.Column("resign_notice_end", sa.Date()),
    flag("temporary_block"),
]

FOREIGN_KEYS = [
    ("replacement_employee_id", "hr_employees"), ("sub_department_id", "hr_departments"),
    ("ledger_account_id", "accounts"), ("wages_account_id", "accounts"),
]


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column("hr_employees", column)
    for column, target in FOREIGN_KEYS:
        op.create_foreign_key(f"fk_hr_employee_{column}", "hr_employees", target, [column], ["id"])
        op.create_index(f"ix_hr_employees_{column}", "hr_employees", [column])
    op.create_check_constraint(
        "ck_hr_employee_weekly_rest", "hr_employees",
        "weekly_rest is null or weekly_rest in ('MON','TUE','WED','THU','FRI','SAT','SUN')")


def downgrade() -> None:
    op.drop_constraint("ck_hr_employee_weekly_rest", "hr_employees", type_="check")
    for column, _target in FOREIGN_KEYS:
        op.drop_index(f"ix_hr_employees_{column}", table_name="hr_employees")
        op.drop_constraint(f"fk_hr_employee_{column}", "hr_employees", type_="foreignkey")
    for column in reversed(COLUMNS):
        op.drop_column("hr_employees", column.name)
