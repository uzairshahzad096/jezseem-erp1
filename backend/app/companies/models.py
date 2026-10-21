import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.mixins import AuditMixin, UUIDPKMixin
from app.core.database import Base


class Company(UUIDPKMixin, AuditMixin, Base):
    """A legal entity / tenant. Everything else (branches, users, data) hangs
    off a company. REQUIRES CONFIRMATION: exact company-level fields used in
    the existing ERP (tax/registration numbers, logo, letterhead, currency,
    fiscal-year start month, etc.) — placeholders below cover common ERP
    needs, to be reconciled against ERP discovery."""

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    tax_number: Mapped[str | None] = mapped_column(String(100))
    default_currency: Mapped[str] = mapped_column(String(10), default="PKR")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    branches: Mapped[list["Branch"]] = relationship(back_populates="company")


class Branch(UUIDPKMixin, AuditMixin, Base):
    """A physical/operational branch belonging to a company. Warehouses,
    users and transactions can be scoped to a branch."""

    __tablename__ = "branches"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    company: Mapped["Company"] = relationship(back_populates="branches")


class FinancialYear(UUIDPKMixin, AuditMixin, Base):
    """Financial years are company-scoped; only one should be marked current
    at a time (enforced in the service layer, not the DB, since business
    rules around FY rollover need REQUIRES BUSINESS CONFIRMATION)."""

    __tablename__ = "financial_years"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "2026-2027"
    start_date: Mapped[str] = mapped_column(String(10), nullable=False)  # ISO date
    end_date: Mapped[str] = mapped_column(String(10), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
