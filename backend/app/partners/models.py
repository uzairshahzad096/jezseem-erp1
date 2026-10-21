"""
Business partners — customers and suppliers.

One table rather than two: the existing ERP's quotations, gate passes and
purchase orders all reference a "Party", and the same organisation is often
both a customer and a supplier. Flags say which roles a partner plays.
"""

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.mixins import AuditMixin, UUIDPKMixin
from app.core.database import Base


class BusinessPartner(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "business_partners"
    __table_args__ = (UniqueConstraint("company_id", "code", name="uq_partner_code_per_company"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    is_customer: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_supplier: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Printed on invoices and gate passes — see the Service Invoice reference.
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    territory: Mapped[str | None] = mapped_column(String(100))
    ntn: Mapped[str | None] = mapped_column(String(50))
    stn: Mapped[str | None] = mapped_column(String(50))

    phone: Mapped[str | None] = mapped_column(String(50))
    cell: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(255))

    payment_terms: Mapped[str | None] = mapped_column(String(255))
    credit_days: Mapped[int | None] = mapped_column()
    #: Finance Phase 2. Null means no limit. What happens when an invoice
    #: would exceed it is the company's AR policy (ar_settings).
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    default_payment_term_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_terms.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- what an international supplier needs beyond a local one (spec
    # section 16). On the same table because a supplier is a supplier; a
    # separate "foreign supplier" list would fork every purchase report.
    country: Mapped[str | None] = mapped_column(String(100), index=True)
    #: Where the goods are made, which is a different question from where the
    #: supplier is: duty is assessed on origin, and a trading house in Dubai
    #: may ship goods manufactured in China.
    country_of_origin: Mapped[str | None] = mapped_column(String(100))
    #: True when purchases from this supplier are imports. Not inferred from
    #: the country, because a local agent can invoice in foreign currency.
    is_international: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    #: The currency this supplier invoices in; defaults a purchase order so
    #: nobody types USD on a PKR supplier by accident.
    currency: Mapped[str | None] = mapped_column(String(10))
    incoterm: Mapped[str | None] = mapped_column(String(30))

    bank_name: Mapped[str | None] = mapped_column(String(200))
    bank_account_number: Mapped[str | None] = mapped_column(String(100))
    bank_iban: Mapped[str | None] = mapped_column(String(60))
    bank_swift: Mapped[str | None] = mapped_column(String(30))
    bank_address: Mapped[str | None] = mapped_column(Text)

    contacts: Mapped[list["PartnerContact"]] = relationship(
        back_populates="partner", cascade="all, delete-orphan"
    )


class PartnerContact(UUIDPKMixin, AuditMixin, Base):
    """A named person at a partner — the Contacts Grid export."""

    __tablename__ = "partner_contacts"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_partners.id"), nullable=False, index=True
    )
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    cell: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    # CRM (migration 0023): which part of their business, and the person to ask for first.
    department: Mapped[str | None] = mapped_column(String(100))
    whatsapp: Mapped[str | None] = mapped_column(String(50))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    partner: Mapped["BusinessPartner"] = relationship(back_populates="contacts")


import app.receivables.models  # noqa: E402,F401  (default_payment_term_id)
