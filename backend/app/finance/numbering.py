"""
Finance document numbering: JV-000001, BPV-000001, …

Configuration lives in `document_series`, one row per document type. Counters
live in the existing `document_sequences` table, keyed by company, fiscal
scope, document type and, for a per-branch series, branch. The counter row is
locked FOR UPDATE, so two users saving at the same moment queue rather than
receive the same number. The unique constraint on journal numbers backs this
up if anything ever went around the lock.

Resetting each fiscal year is the default. The fiscal scope is then the
year's name ("2026-27"), otherwise "ALL". Journal numbers are unique per
company and financial year, which is what makes a yearly restart safe.
"""

import re
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.companies.models import Branch, FinancialYear
from app.finance.errors import FinanceError
from app.finance.models import DocumentSeries

#: (doc_type, name, prefix). The spec's list plus OB for opening batches.
DEFAULT_SERIES = [
    ("JV", "Journal Voucher", "JV"),
    ("SI", "Sales Invoice", "SI"),
    ("PI", "Purchase Invoice", "PI"),
    ("RV", "Receipt Voucher", "RV"),
    ("PV", "Payment Voucher", "PV"),
    ("BRV", "Bank Receipt Voucher", "BRV"),
    ("BPV", "Bank Payment Voucher", "BPV"),
    ("CN", "Credit Note", "CN"),
    ("DN", "Debit Note", "DN"),
    ("OB", "Opening Balance Batch", "OB"),
]

TOKENS = {"prefix", "seq", "fy", "branch"}


def install_default_series(db: Session, company_id: uuid.UUID, user_id: uuid.UUID | None = None) -> int:
    existing = set(db.scalars(
        select(DocumentSeries.doc_type).where(DocumentSeries.company_id == company_id)).all())
    added = 0
    for doc_type, name, prefix in DEFAULT_SERIES:
        if doc_type in existing:
            continue
        db.add(DocumentSeries(company_id=company_id, doc_type=doc_type, name=name,
                              prefix=prefix, padding=6, format="{prefix}-{seq}",
                              reset_each_fiscal_year=True, per_branch=False,
                              created_by=user_id))
        added += 1
    return added


def validate_series(series: DocumentSeries) -> None:
    tokens = set(re.findall(r"\{(\w+)\}", series.format or ""))
    unknown = tokens - TOKENS
    if unknown:
        raise FinanceError(f"Unknown numbering token(s): {', '.join(sorted(unknown))}. "
                           "Use {prefix}, {seq}, {fy} and {branch}.")
    if "seq" not in tokens:
        raise FinanceError("The number format must contain {seq}.")
    if series.per_branch and "branch" not in tokens:
        raise FinanceError("A per-branch series must include {branch} in its format, "
                           "or two branches would issue the same number.")
    if not 1 <= series.padding <= 12:
        raise FinanceError("Padding must be between 1 and 12 digits.")


def render(series: DocumentSeries, number: int, fy_name: str, branch_code: str | None) -> str:
    return series.format.format(
        prefix=series.prefix,
        seq=str(number).zfill(series.padding),
        fy=fy_name,
        branch=branch_code or "",
    )


def _scope(series: DocumentSeries, fy: FinancialYear) -> str:
    return fy.name if series.reset_each_fiscal_year else "ALL"


def _series(db: Session, company_id: uuid.UUID, doc_type: str) -> DocumentSeries:
    series = db.scalar(select(DocumentSeries).where(
        DocumentSeries.company_id == company_id, DocumentSeries.doc_type == doc_type))
    if series is None or not series.is_active:
        raise FinanceError(f"No active numbering series for {doc_type}. "
                           "Set one up under Finance Settings.")
    return series


def allocate(db: Session, company_id: uuid.UUID, doc_type: str, fy: FinancialYear,
             branch_id: uuid.UUID | None = None) -> str:
    """Take the next number. Must run inside the caller's transaction."""
    series = _series(db, company_id, doc_type)
    branch = None
    if series.per_branch:
        if branch_id is None:
            raise FinanceError(f"{series.name} is numbered per branch; choose a branch.")
        branch = db.get(Branch, branch_id)
    scope_branch = branch.id if branch else None
    scope = _scope(series, fy)

    # Create the counter if it is missing without racing another request,
    # then lock it. ON CONFLICT names the expression index's columns.
    db.execute(text("""
        insert into document_sequences (id, company_id, branch_id, fiscal_year, doc_type, last_number)
        values (:id, :company, :branch, :scope, :doc_type, 0)
        on conflict (company_id, fiscal_year, doc_type,
                     coalesce(branch_id, '00000000-0000-0000-0000-000000000000'::uuid))
        do nothing
    """), {"id": uuid.uuid4(), "company": company_id, "branch": scope_branch,
           "scope": scope, "doc_type": doc_type})
    number = db.execute(text("""
        update document_sequences set last_number = last_number + 1
        where company_id = :company and fiscal_year = :scope and doc_type = :doc_type
          and branch_id is not distinct from :branch
        returning last_number
    """), {"company": company_id, "scope": scope, "doc_type": doc_type,
           "branch": scope_branch}).scalar_one()
    return render(series, number, fy.name, branch.code if branch else None)


def peek(db: Session, series: DocumentSeries, fy: FinancialYear | None,
         branch_code: str | None = None) -> str | None:
    """What the next number would be, without taking it. For the settings screen."""
    if fy is None:
        return None
    last = db.execute(text("""
        select coalesce(max(last_number), 0) from document_sequences
        where company_id = :company and fiscal_year = :scope and doc_type = :doc_type
    """), {"company": series.company_id, "scope": _scope(series, fy),
           "doc_type": series.doc_type}).scalar_one()
    return render(series, last + 1, fy.name, branch_code or ("HO" if series.per_branch else None))
