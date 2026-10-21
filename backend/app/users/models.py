import uuid

from sqlalchemy import Boolean, ForeignKey, String, Table, Column
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.mixins import UUIDPKMixin, AuditMixin
from app.core.database import Base

# --- Association tables (many-to-many) ---

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True),
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", UUID(as_uuid=True), ForeignKey("permissions.id"), primary_key=True),
)

user_company_access = Table(
    "user_company_access",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True),
    Column("company_id", UUID(as_uuid=True), ForeignKey("companies.id"), primary_key=True),
)

user_branch_access = Table(
    "user_branch_access",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True),
    Column("branch_id", UUID(as_uuid=True), ForeignKey("branches.id"), primary_key=True),
)


class User(UUIDPKMixin, Base):
    """A login identity. created_by/updated_by are intentionally omitted
    here (AuditMixin depends on users.id, which would self-reference) —
    audit_created_by is tracked instead once the first admin exists."""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)  # bypasses RBAC — platform admin only

    roles: Mapped[list["Role"]] = relationship(secondary=user_roles, back_populates="users")


class Role(UUIDPKMixin, AuditMixin, Base):
    """A named bundle of permissions (e.g. 'Sales Manager', 'Finance').
    Roles are company-scoped so different companies can tailor roles,
    matching the existing ERP's per-company role setup —
    REQUIRES CONFIRMATION on whether roles should instead be global
    templates that companies then customize."""

    __tablename__ = "roles"

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    is_system_role: Mapped[bool] = mapped_column(Boolean, default=False)  # cannot be deleted

    users: Mapped[list["User"]] = relationship(secondary=user_roles, back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permissions, back_populates="roles"
    )


class Permission(UUIDPKMixin, Base):
    """A single action on a single module, e.g. module='sales.quotation',
    action='approve'. Action vocabulary matches spec section 5:
    view / create / edit / delete / approve / post / cancel / export / print."""

    __tablename__ = "permissions"

    module: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)  # "sales.quotation.approve"
    description: Mapped[str | None] = mapped_column(String(255))

    roles: Mapped[list["Role"]] = relationship(secondary=role_permissions, back_populates="permissions")
