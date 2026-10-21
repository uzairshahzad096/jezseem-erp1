"""
Leads: the sales pipeline before a quotation becomes an order.

A lead is either a new prospect (company and contact typed in) or a fresh
opportunity with one of our own customers (linked to the customer record, so
their address, ledger and history come with it). It moves through the stages

    New -> Contacted -> Qualified -> Quoted -> Negotiation -> Won / Lost

with every call, visit, message and meeting logged against it as an activity.
An activity with a due date and no "done" is a follow-up: the next thing
someone has promised to do.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.mixins import AuditMixin, UUIDPKMixin
from app.core.database import Base

#: Stage and the chance it closes, used for the weighted pipeline.
STAGES: dict[str, int] = {"New": 10, "Contacted": 20, "Qualified": 40, "Quoted": 60, "Negotiation": 80,
                          "Won": 100, "Lost": 0}
OPEN_STAGES = ("New", "Contacted", "Qualified", "Quoted", "Negotiation")
RATINGS = ["Hot", "Warm", "Cold"]
ACTIVITY_TYPES = ["Call", "Visit", "WhatsApp", "Email", "Meeting", "Demo", "Quotation Sent", "Note"]
LOST_REASONS = ["Price too high", "Bought from competitor", "No budget", "Not interested",
                "No response", "Requirement cancelled", "Other"]


def _fk(target: str, **kw):
    return mapped_column(UUID(as_uuid=True), ForeignKey(target), **kw)


class LeadSource(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "lead_sources"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_lead_source_name"),)

    company_id: Mapped[uuid.UUID] = _fk("companies.id", nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)


class Lead(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("company_id", "lead_number", name="uq_lead_number"),)

    company_id: Mapped[uuid.UUID] = _fk("companies.id", nullable=False, index=True)
    lead_number: Mapped[str] = mapped_column(String(30), nullable=False)
    lead_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    #: What they want, in a line: "2 x TKT plotters for the new cutting hall".
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    #: One of our customers, when the lead is new business with them.
    customer_id: Mapped[uuid.UUID | None] = _fk("business_partners.id", index=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_person: Mapped[str | None] = mapped_column(String(150))
    designation: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(60))
    email: Mapped[str | None] = mapped_column(String(150))
    city: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[uuid.UUID | None] = _fk("lead_sources.id", index=True)
    #: The product or machine type they are interested in.
    interest: Mapped[str | None] = mapped_column(String(200))
    item_id: Mapped[uuid.UUID | None] = _fk("inventory_items.id")
    estimated_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    expected_close_date: Mapped[date | None] = mapped_column(Date)
    stage: Mapped[str] = mapped_column(String(20), default="New", nullable=False, index=True)
    rating: Mapped[str] = mapped_column(String(10), default="Warm", nullable=False)
    owner_id: Mapped[uuid.UUID | None] = _fk("users.id", index=True)
    quotation_id: Mapped[uuid.UUID | None] = _fk("sales_documents.id")
    lost_reason: Mapped[str | None] = mapped_column(String(100))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(Text)

    activities: Mapped[list["LeadActivity"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan", order_by="LeadActivity.activity_at.desc()")


class LeadActivity(UUIDPKMixin, Base):
    """Something done with a lead or a customer, or — with a due date and not done —
    something to do. The one activity log behind Leads and CRM: an activity belongs
    to a lead, to a customer (a courtesy visit, a complaint call), or to both."""
    __tablename__ = "lead_activities"

    lead_id: Mapped[uuid.UUID | None] = _fk("leads.id", index=True)
    customer_id: Mapped[uuid.UUID | None] = _fk("business_partners.id", index=True)
    contact_id: Mapped[uuid.UUID | None] = _fk("partner_contacts.id")
    activity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str | None] = mapped_column(Text)
    #: A follow-up: planned for this day, open until done_at is set.
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_id: Mapped[uuid.UUID | None] = _fk("users.id", index=True)
    created_by: Mapped[uuid.UUID | None] = _fk("users.id")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.now)

    lead: Mapped["Lead"] = relationship(back_populates="activities")


import app.partners.models  # noqa: E402,F401
