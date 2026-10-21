"""
Shared mixins so that EVERY table in the ERP gets, consistently:

- a UUID primary key
- created_at / updated_at timestamps
- created_by / updated_by user references
- company_id / branch_id ownership (for multi-company, multi-branch data)

This directly implements spec section 4 (Multi-Company Architecture) and
section 9 (Database Design): no table should be designed single-company
and "converted" later.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPKMixin:
    """UUID primary key — avoids sequential-ID enumeration and eases future
    multi-database / offline-first sync scenarios."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class AuditMixin:
    """Who/when created and last updated a row. Combined with the
    audit_logs table (app/audit) this gives full traceability per spec
    section 16, without duplicating history on every table."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class CompanyScopedMixin:
    """Ties a row to a company and (optionally) a branch. Required on every
    business-data table — never on truly global reference tables."""

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True, index=True
    )
