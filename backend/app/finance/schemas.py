"""Request bodies for the finance API. Amounts are Decimal end to end; a
number sent as a string ("1234.50") is read exactly, never through a float."""

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.finance.models import CONTROL_TYPES


class AccountIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    account_type_id: uuid.UUID
    account_group_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    normal_balance: str | None = None
    is_postable: bool = True
    is_control_account: bool = False
    control_type: str | None = None
    allow_manual_posting: bool | None = None
    is_active: bool = True
    currency: str | None = None
    description: str | None = None

    @field_validator("normal_balance")
    @classmethod
    def _balance(cls, value):
        if value and value not in ("DEBIT", "CREDIT"):
            raise ValueError("normal_balance must be DEBIT or CREDIT")
        return value or None

    @field_validator("control_type")
    @classmethod
    def _control(cls, value):
        if value and value not in CONTROL_TYPES:
            raise ValueError(f"control_type must be one of {', '.join(CONTROL_TYPES)}")
        return value or None

    def data(self) -> dict:
        values = self.model_dump()
        if values["allow_manual_posting"] is None:
            values["allow_manual_posting"] = not values["is_control_account"]
        return values


class AccountGroupIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=150)
    account_type_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    sort_order: int = 0
    is_active: bool = True


class CostCenterIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=150)
    parent_id: uuid.UUID | None = None
    is_active: bool = True


class JournalLineIn(BaseModel):
    account_id: uuid.UUID
    description: str | None = None
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    customer_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    inventory_item_id: uuid.UUID | None = None
    cost_center_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None


class JournalIn(BaseModel):
    journal_date: date
    journal_type: str = "MANUAL"
    description: str | None = None
    reference: str | None = Field(default=None, max_length=100)
    branch_id: uuid.UUID | None = None
    lines: list[JournalLineIn] = Field(min_length=2)


class ReasonIn(BaseModel):
    reason: str | None = None


class ReverseIn(BaseModel):
    reversal_date: date
    reason: str


class FinancialYearIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    start_date: date
    end_date: date
    make_current: bool = False


class SeriesIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    prefix: str = Field(min_length=1, max_length=20)
    padding: int = Field(6, ge=1, le=12)
    format: str = Field("{prefix}-{seq}", max_length=60)
    reset_each_fiscal_year: bool = True
    per_branch: bool = False
    is_active: bool = True


class PostingRuleIn(BaseModel):
    account_id: uuid.UUID | None = None
    is_active: bool = True


class PostingPreviewIn(BaseModel):
    event_code: str
    journal_date: date | None = None
    amounts: dict[str, Decimal]
    customer_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None


class OpeningBatchIn(BaseModel):
    financial_year_id: uuid.UUID
    cutover_date: date
    branch_id: uuid.UUID | None = None
    source_document: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class ReconciliationEntryIn(BaseModel):
    category: str
    legacy_balance: Decimal | None = None
    explanation: str | None = None


class ReconciliationIn(BaseModel):
    entries: list[ReconciliationEntryIn]
