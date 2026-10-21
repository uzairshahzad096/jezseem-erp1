"""
Calibration / Services: the machines the company services, the customers'
installed machines, maintenance contracts, service invoices, calibration
definitions (the test procedure for a machine model) and the calibration
reports issued as certificates.

Laid out on the previous ERP's six screens:

    Machine Definitions      a make / model the company services
    Customer Machines        one installed unit of a model, at a customer
    Contracts                a maintenance / calibration agreement with a customer
    Invoices                 a bill for calibration, maintenance or a service visit
    Calibration Definitions  the tests a model is calibrated against, versioned
    Calibration Reports      one calibration of one machine, printed as a certificate

A posted invoice bills the customer through the posting engine
(`app.calibration.service`): Dr Accounts Receivable, Cr Sales - Services,
Cr Output Sales Tax, with a receivable item so receipts can be matched to it.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.mixins import AuditMixin, UUIDPKMixin
from app.core.database import Base

MACHINE_STATUSES = ["ACTIVE", "UNDER SERVICE", "INACTIVE", "DECOMMISSIONED"]
BILLING_FREQUENCIES = {"MONTHLY": 1, "QUARTERLY": 3, "HALF YEARLY": 6, "YEARLY": 12}
CONTRACT_STATUSES = ["DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"]
CONTRACT_TYPES = ["MAINTENANCE", "CALIBRATION", "MAINTENANCE & CALIBRATION"]
SERVICE_TYPES = ["Maintenance", "Calibration", "Service / Repair", "Installation", "Training"]
INVOICE_STATUSES = ["Draft", "Posted", "Cancelled"]
OVERALL_RESULTS = ["PASS", "FAIL", "PENDING"]
REPORT_STATUSES = ["DRAFT", "COMPLETED", "ISSUED", "CANCELLED"]


def _uuid_fk(target: str, **kw):
    return mapped_column(UUID(as_uuid=True), ForeignKey(target), **kw)


class MachineDefinition(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "svc_machine_definitions"

    company_id: Mapped[uuid.UUID] = _uuid_fk("companies.id", nullable=False, index=True)
    machine_category: Mapped[str] = mapped_column(String(150), nullable=False)
    vendor_name: Mapped[str] = mapped_column(String(150), nullable=False)
    model_number: Mapped[str] = mapped_column(String(150), nullable=False)
    origin: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CustomerMachine(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "svc_customer_machines"

    company_id: Mapped[uuid.UUID] = _uuid_fk("companies.id", nullable=False, index=True)
    customer_id: Mapped[uuid.UUID] = _uuid_fk("business_partners.id", nullable=False, index=True)
    machine_definition_id: Mapped[uuid.UUID] = _uuid_fk("svc_machine_definitions.id", nullable=False, index=True)
    machine_code: Mapped[str | None] = mapped_column(String(100))
    serial_number: Mapped[str | None] = mapped_column(String(100))
    installation_date: Mapped[date | None] = mapped_column(Date)
    machine_status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False)
    machine_location: Mapped[str | None] = mapped_column(String(150))
    remarks: Mapped[str | None] = mapped_column(Text)


class ServiceContract(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "svc_contracts"
    __table_args__ = (UniqueConstraint("company_id", "contract_number", name="uq_svc_contract_number"),)

    company_id: Mapped[uuid.UUID] = _uuid_fk("companies.id", nullable=False, index=True)
    contract_number: Mapped[str] = mapped_column(String(50), nullable=False)
    #: The agreement's own reference, as printed (e.g. JEZ-TGR.-0026).
    reference: Mapped[str | None] = mapped_column(String(100))
    contract_date: Mapped[date] = mapped_column(Date, nullable=False)
    customer_id: Mapped[uuid.UUID] = _uuid_fk("business_partners.id", nullable=False, index=True)
    contract_type: Mapped[str] = mapped_column(String(40), default="MAINTENANCE", nullable=False)
    #: Where the equipment is, as the agreement names it (e.g. Cutting Division).
    division: Mapped[str | None] = mapped_column(String(150))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    billing_frequency: Mapped[str] = mapped_column(String(20), default="MONTHLY", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    #: What the customer pays each billing period.
    charge_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    tax_applicable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tax_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=0, nullable=False)
    #: "payable ... without any tax deductions", as the agreement words it.
    without_tax_deduction: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    response_hours: Mapped[int | None] = mapped_column(Integer)
    #: Who provides spare parts and lubrication: Customer or Jezseem Traders.
    spare_parts_by: Mapped[str | None] = mapped_column(String(30))
    #: The agreement's Service Coverage points, one per line.
    service_coverage: Mapped[str | None] = mapped_column(Text)
    #: Anything else the agreement says, one point per line.
    additional_terms: Mapped[str | None] = mapped_column(Text)
    contract_status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    contract_owner: Mapped[str | None] = mapped_column(String(150))
    remarks: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["ServiceContractLine"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan", order_by="ServiceContractLine.line_number")


class ServiceContractLine(UUIDPKMixin, Base):
    """One piece of equipment (or a kind of equipment) the contract covers."""
    __tablename__ = "svc_contract_lines"

    contract_id: Mapped[uuid.UUID] = _uuid_fk("svc_contracts.id", nullable=False, index=True)
    line_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    customer_machine_id: Mapped[uuid.UUID | None] = _uuid_fk("svc_customer_machines.id", index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    service_type: Mapped[str | None] = mapped_column(String(40))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=1, nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)

    contract: Mapped["ServiceContract"] = relationship(back_populates="lines")


class ServiceInvoice(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "svc_invoices"
    __table_args__ = (UniqueConstraint("company_id", "invoice_number", name="uq_svc_invoice_number"),)

    company_id: Mapped[uuid.UUID] = _uuid_fk("companies.id", nullable=False, index=True)
    branch_id: Mapped[uuid.UUID | None] = _uuid_fk("branches.id", index=True)
    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    customer_id: Mapped[uuid.UUID] = _uuid_fk("business_partners.id", nullable=False, index=True)
    contract_id: Mapped[uuid.UUID | None] = _uuid_fk("svc_contracts.id", index=True)
    service_type: Mapped[str] = mapped_column(String(40), default="Maintenance", nullable=False)
    #: The contract period this invoice bills, when it bills one.
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    customer_po_number: Mapped[str | None] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    payment_terms: Mapped[str | None] = mapped_column(String(255))
    remarks: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="Draft", nullable=False, index=True)

    # Worked out on save from the lines; never accepted from the client.
    excluding_tax_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    sales_tax_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    net_receivable: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    journal_entry_id: Mapped[uuid.UUID | None] = _uuid_fk("journal_entries.id")
    posted_by: Mapped[uuid.UUID | None] = _uuid_fk("users.id")
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[uuid.UUID | None] = _uuid_fk("users.id")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["ServiceInvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="ServiceInvoiceLine.line_number")


class ServiceInvoiceLine(UUIDPKMixin, Base):
    __tablename__ = "svc_invoice_lines"

    invoice_id: Mapped[uuid.UUID] = _uuid_fk("svc_invoices.id", nullable=False, index=True)
    line_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    customer_machine_id: Mapped[uuid.UUID | None] = _uuid_fk("svc_customer_machines.id", index=True)
    calibration_report_id: Mapped[uuid.UUID | None] = _uuid_fk("svc_calibration_reports.id", index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=1, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0, nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=0, nullable=False)
    tax_percent: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=0, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

    invoice: Mapped["ServiceInvoice"] = relationship(back_populates="lines")


class CalibrationDefinition(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "svc_calibration_definitions"

    company_id: Mapped[uuid.UUID] = _uuid_fk("companies.id", nullable=False, index=True)
    machine_definition_id: Mapped[uuid.UUID] = _uuid_fk("svc_machine_definitions.id", nullable=False, index=True)
    definition_name: Mapped[str] = mapped_column(String(200), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    validity_days: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    default_temperature: Mapped[str | None] = mapped_column(String(100))
    default_relative_humidity: Mapped[str | None] = mapped_column(String(100))
    default_main_voltage: Mapped[str | None] = mapped_column(String(100))
    default_main_frequency: Mapped[str | None] = mapped_column(String(100))
    default_noise_level: Mapped[str | None] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    standard_comments: Mapped[str | None] = mapped_column(Text)
    standard_note: Mapped[str | None] = mapped_column(Text)

    tests: Mapped[list["CalibrationTest"]] = relationship(
        back_populates="definition", cascade="all, delete-orphan", order_by="CalibrationTest.seq")


class CalibrationTest(UUIDPKMixin, Base):
    __tablename__ = "svc_calibration_tests"

    definition_id: Mapped[uuid.UUID] = _uuid_fk("svc_calibration_definitions.id", nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    test_title: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_result: Mapped[str | None] = mapped_column(String(255))
    unit: Mapped[str | None] = mapped_column(String(50))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)

    definition: Mapped["CalibrationDefinition"] = relationship(back_populates="tests")


class CalibrationReport(UUIDPKMixin, AuditMixin, Base):
    __tablename__ = "svc_calibration_reports"
    __table_args__ = (UniqueConstraint("company_id", "certificate_number", name="uq_svc_certificate_number"),)

    company_id: Mapped[uuid.UUID] = _uuid_fk("companies.id", nullable=False, index=True)
    certificate_number: Mapped[str] = mapped_column(String(80), nullable=False)
    customer_id: Mapped[uuid.UUID] = _uuid_fk("business_partners.id", nullable=False, index=True)
    customer_machine_id: Mapped[uuid.UUID] = _uuid_fk("svc_customer_machines.id", nullable=False, index=True)
    calibration_definition_id: Mapped[uuid.UUID] = _uuid_fk("svc_calibration_definitions.id", nullable=False)
    contract_id: Mapped[uuid.UUID | None] = _uuid_fk("svc_contracts.id", index=True)
    contract_line_id: Mapped[uuid.UUID | None] = _uuid_fk("svc_contract_lines.id")
    calibration_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    next_calibration_date: Mapped[date | None] = mapped_column(Date)
    technician_name: Mapped[str | None] = mapped_column(String(150))
    overall_result: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    report_status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    temperature: Mapped[str | None] = mapped_column(String(100))
    relative_humidity: Mapped[str | None] = mapped_column(String(100))
    main_voltage: Mapped[str | None] = mapped_column(String(100))
    main_frequency: Mapped[str | None] = mapped_column(String(100))
    noise_level: Mapped[str | None] = mapped_column(String(100))
    comments: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)

    results: Mapped[list["CalibrationResult"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", order_by="CalibrationResult.seq")


class CalibrationResult(UUIDPKMixin, Base):
    """One test of the definition, as found on the day."""
    __tablename__ = "svc_calibration_results"

    report_id: Mapped[uuid.UUID] = _uuid_fk("svc_calibration_reports.id", nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    test_title: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_result: Mapped[str | None] = mapped_column(String(255))
    unit: Mapped[str | None] = mapped_column(String(50))
    initial_reading: Mapped[str | None] = mapped_column(String(100))
    observed: Mapped[str | None] = mapped_column(String(100))
    uncertainty: Mapped[str | None] = mapped_column(String(100))
    passed: Mapped[bool | None] = mapped_column(Boolean)
    remarks: Mapped[str | None] = mapped_column(Text)

    report: Mapped["CalibrationReport"] = relationship(back_populates="results")


import app.finance.models  # noqa: E402,F401
import app.partners.models  # noqa: E402,F401
