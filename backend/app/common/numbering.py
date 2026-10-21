"""
Document reference numbers.

Each document type has its own sequence, scoped to company and financial
year, allocated inside the caller's transaction so two users saving at the
same moment cannot receive the same number.

REQUIRES BUSINESS CONFIRMATION: the exact format used by the current ERP.
The legacy exports show mixed conventions â€” quotations are plain integers
("1", "32"), sales orders look like "202609201" and purchase orders like
"10-26". Until each is confirmed, the pattern below is configurable per
document type and nothing is silently assumed.
"""

import uuid
from datetime import date

from sqlalchemy import ForeignKey, Index, Integer, String, select, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base


class DocumentSequence(Base):
    """One counter per (company, financial year, document type), and per
    branch where a finance series numbers each branch separately."""

    __tablename__ = "document_sequences"
    __table_args__ = (
        Index(
            "uq_sequence_scope_branch", "company_id", "fiscal_year", "doc_type",
            text("coalesce(branch_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    #: Null for every counter except a per-branch finance series.
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=True
    )
    fiscal_year: Mapped[str] = mapped_column(String(20), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    last_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


def next_number(
    db: Session,
    company_id: uuid.UUID,
    doc_type: str,
    fiscal_year: str,
    prefix: str = "",
    continue_from: int = 0,
) -> str:
    """Allocate the next reference for a document type.

    Uses SELECT ... FOR UPDATE so concurrent saves queue rather than collide.
    Must be called inside a transaction that the caller commits.

    `continue_from` is the highest number already in use. A counter starting at
    zero would hand out numbers that the imported documents already carry, so a
    brand-new counter starts above them instead, and an existing counter is
    pulled up if history has since overtaken it.
    """
    row = db.scalar(
        select(DocumentSequence)
        .where(
            DocumentSequence.company_id == company_id,
            DocumentSequence.fiscal_year == fiscal_year,
            DocumentSequence.doc_type == doc_type,
            DocumentSequence.branch_id.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        row = DocumentSequence(
            company_id=company_id, fiscal_year=fiscal_year, doc_type=doc_type,
            last_number=continue_from,
        )
        db.add(row)
        db.flush()
    elif continue_from > row.last_number:
        row.last_number = continue_from

    row.last_number += 1
    year_part = fiscal_year.split("-")[0][-2:] if "-" in fiscal_year else str(date.today().year)[-2:]
    return f"{prefix}{year_part}{row.last_number:05d}" if prefix else str(row.last_number)


def next_dated_number(
    db: Session,
    company_id: uuid.UUID,
    doc_type: str,
    on_date: date,
    continue_from: int = 0,
) -> str:
    """A reference of the form YYYYMMDD + a counter that restarts each day.

    This is how the old ERP numbers sales orders: 202609221 is the first
    document of 22 September 2026, 202609222 the second. The counter is scoped
    to the date rather than the financial year, so it is stored against the
    date string and locked the same way â€” two users saving on the same day
    queue instead of colliding.
    """
    scope = on_date.strftime("%Y%m%d")
    row = db.scalar(
        select(DocumentSequence)
        .where(
            DocumentSequence.company_id == company_id,
            DocumentSequence.fiscal_year == scope,
            DocumentSequence.doc_type == doc_type,
            DocumentSequence.branch_id.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        row = DocumentSequence(
            company_id=company_id, fiscal_year=scope, doc_type=doc_type,
            last_number=continue_from,
        )
        db.add(row)
        db.flush()
    elif continue_from > row.last_number:
        row.last_number = continue_from

    row.last_number += 1
    return f"{scope}{row.last_number}"
