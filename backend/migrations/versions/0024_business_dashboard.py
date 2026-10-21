"""business dashboard permission, and Staff / Business Dashboard roles

Revision ID: 0024
Revises: 0023

The home dashboard shows sales, receivables and the best customers only to
users holding `dashboard.business.view`; everyone else sees a simple one.

- `dashboard.business.view` is added and given to the Administrator role.
- A "Staff" role: every permission except the business figures and the
  Security screens (users, roles, permissions), for ordinary employees.
- A "Business Dashboard" role holding only the business figures, ticked on a
  user in Security -> Users to let a selected employee see them.
No user is changed.
"""
import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

CODE = "dashboard.business.view"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("""
        insert into permissions (id, module, action, code, description)
        values (gen_random_uuid(), 'dashboard', 'view', :code, 'See sales, receivables and customer figures on the home dashboard')
        on conflict (code) do nothing
    """), {"code": CODE})
    bind.execute(sa.text("""
        insert into role_permissions (role_id, permission_id)
        select r.id, p.id from roles r cross join permissions p
        where r.name = 'Administrator' and p.code = :code
        on conflict do nothing
    """), {"code": CODE})
    for name, description in (("Staff", "Every module, without the business figures on the dashboard or the Security screens."),
                              ("Business Dashboard", "Sees sales, receivables and customer figures on the home dashboard.")):
        bind.execute(sa.text("""
            insert into roles (id, company_id, name, description, is_system_role, created_at, updated_at)
            select gen_random_uuid(), c.id, cast(:name as varchar), cast(:description as varchar), true, now(), now()
            from companies c
            where not exists (select 1 from roles r where r.name = cast(:name as varchar) and r.company_id = c.id)
        """), {"name": name, "description": description})
    bind.execute(sa.text("""
        insert into role_permissions (role_id, permission_id)
        select r.id, p.id from roles r cross join permissions p
        where r.name = 'Staff' and p.code <> :code and p.code not like 'security.%'
        on conflict do nothing
    """), {"code": CODE})
    bind.execute(sa.text("""
        insert into role_permissions (role_id, permission_id)
        select r.id, p.id from roles r cross join permissions p
        where r.name = 'Business Dashboard' and p.code = :code
        on conflict do nothing
    """), {"code": CODE})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("""
        delete from role_permissions where role_id in (select id from roles where name in ('Staff', 'Business Dashboard'))
           or permission_id in (select id from permissions where code = :code)
    """), {"code": CODE})
    bind.execute(sa.text("delete from user_roles where role_id in (select id from roles where name in ('Staff', 'Business Dashboard'))"))
    bind.execute(sa.text("delete from roles where name in ('Staff', 'Business Dashboard')"))
    bind.execute(sa.text("delete from permissions where code = :code"), {"code": CODE})
