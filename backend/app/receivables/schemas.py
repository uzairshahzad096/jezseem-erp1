"""Request bodies for sales invoices, notes, receipts and AR setup.
Amounts are Decimal end to end."""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.receivables.models import CREDIT_POLICIES, PAYMENT_METHOD_KINDS, TAX_TYPES


class DocLineIn(BaseModel):
    item_id: uuid.UUID | None = None
    item_code: str | None = None
    description: str | None = None
    uom: str | None = None
    hs_code: str | None = None
    lot_number: str | None = None
    rack_name: str | None = None
    quantity: Decimal
    unit_price: Decimal = Decimal("0")
    discount_percent: Decimal = Decimal("0")
    tax_code_id: uuid.UUID | None = None
    source_line_id: uuid.UUID | None = None
    gate_pass_line_id: uuid.UUID | None = None


class DocumentIn(BaseModel):
    customer_id: uuid.UUID
    doc_date: date
    branch_id: uuid.UUID | None = None
    payment_term_id: uuid.UUID | None = None
    due_date: date | None = None
    billing_address: str | None = None
    shipping_address: str | None = None
    currency: str = "PKR"
    exchange_rate: Decimal = Decimal("1")
    tax_inclusive: bool = False
    is_cash_sale: bool = False
    cash_account_id: uuid.UUID | None = None
    freight_amount: Decimal = Decimal("0")
    document_discount: Decimal = Decimal("0")
    customer_po_number: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=150)
    remarks: str | None = None
    source_document_id: uuid.UUID | None = None
    quotation_id: uuid.UUID | None = None
    gate_pass_id: uuid.UUID | None = None
    reason_code: str | None = Field(default=None, max_length=30)
    reason: str | None = None
    lines: list[DocLineIn] = Field(min_length=1)


class ReasonIn(BaseModel):
    reason: str | None = None


class AllocationIn(BaseModel):
    item_id: uuid.UUID
    amount: Decimal


class ReceiptIn(BaseModel):
    customer_id: uuid.UUID
    receipt_date: date
    branch_id: uuid.UUID | None = None
    payment_method_id: uuid.UUID
    deposit_account_id: uuid.UUID | None = None
    amount: Decimal
    #: Tax the customer withheld, included in `amount`.
    wht_amount: Decimal = Decimal("0")
    currency: str = "PKR"
    exchange_rate: Decimal = Decimal("1")
    reference: str | None = Field(default=None, max_length=100)
    cheque_number: str | None = Field(default=None, max_length=50)
    cheque_date: date | None = None
    bank_name: str | None = Field(default=None, max_length=150)
    notes: str | None = None
    allocations: list[AllocationIn] = []


class AllocateIn(BaseModel):
    allocations: list[AllocationIn] = Field(min_length=1)
    allocation_date: date | None = None


class CreditAllocateIn(BaseModel):
    """Allocate an unapplied credit note or opening credit/advance."""
    from_item_id: uuid.UUID
    to_item_id: uuid.UUID
    amount: Decimal
    allocation_date: date | None = None


class PaymentTermIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=100)
    days: int = Field(0, ge=0, le=3650)
    is_cash: bool = False
    is_active: bool = True
    sort_order: int = 0


class PaymentMethodIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=100)
    kind: str
    requires_reference: bool = False
    default_account_id: uuid.UUID | None = None
    is_active: bool = True
    sort_order: int = 0

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in PAYMENT_METHOD_KINDS:
            raise ValueError(f"kind must be one of {', '.join(PAYMENT_METHOD_KINDS)}")
        return v


class TaxCodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=100)
    tax_type: str
    rate: Decimal = Decimal("0")
    output_account_id: uuid.UUID | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    is_active: bool = True
    description: str | None = None

    @field_validator("tax_type")
    @classmethod
    def _type(cls, v):
        if v not in TAX_TYPES:
            raise ValueError(f"tax_type must be one of {', '.join(TAX_TYPES)}")
        return v


class ARSettingsIn(BaseModel):
    credit_limit_policy: str
    sales_order_cutoff_date: date | None = None
    allow_quotation_invoice: bool = False
    default_payment_term_id: uuid.UUID | None = None
    aging_buckets: str = "30,60,90,120"

    @field_validator("credit_limit_policy")
    @classmethod
    def _policy(cls, v):
        if v not in CREDIT_POLICIES:
            raise ValueError(f"credit_limit_policy must be one of {', '.join(CREDIT_POLICIES)}")
        return v

    @field_validator("aging_buckets")
    @classmethod
    def _buckets(cls, v):
        parts = [p.strip() for p in v.split(",") if p.strip()]
        if not parts or not all(p.isdigit() and int(p) > 0 for p in parts):
            raise ValueError("aging_buckets must be positive day counts, e.g. 30,60,90,120")
        return ",".join(str(x) for x in sorted({int(p) for p in parts}))


class CustomerCreditIn(BaseModel):
    credit_limit: Decimal | None = None
    default_payment_term_id: uuid.UUID | None = None
