"""
One-off repair: split concatenated product descriptions into separate lines.

The legacy quotation data was loaded from the old ERP's *listing grid*, whose
"Detail Items" column already joins every product on a document into one
string with " , " between them. The loader stored that string as a single
document line, so a quotation for six products arrived as one line naming all
six — and printed that way, one long row instead of six.

This splits those lines apart, so each product becomes its own line and the
PDF itemises the way the supplied Quotation does.

    python -m app.sales.split_lines              # report only, changes nothing
    python -m app.sales.split_lines --apply      # write the changes

Only " , " (space-comma-space) is treated as a separator, because that is
exactly what the grid put between products. A bare comma inside a single
product name — "Faisalabad, Pakistan" — is left alone, which is why the rule
is not simply "split on commas".

What is deliberately NOT touched:

- Money. Every one of these lines carries a zero price, because the grid the
  data came from has no price column. Splitting a zero into six zeros changes
  nothing, and this script does not invent figures. Prices still need the
  detail-level export.
- item_id. None of these lines is linked to a product, and which of the six
  names maps to which inventory item cannot be decided safely here. The parts
  are stored as description-only lines, exactly as they arrived.
"""

import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import SessionLocal
from app.sales.models import SalesDocument, SalesDocumentLine

# Importing these registers every table the sales foreign keys point at. The
# running app pulls them in through app.main; a standalone script does not, and
# without them SQLAlchemy cannot resolve "branches.id" when it flushes.
from app.companies.models import Branch, Company, FinancialYear  # noqa: F401
from app.inventory.models import InventoryItem  # noqa: F401
from app.partners.models import BusinessPartner  # noqa: F401
from app.users.models import User  # noqa: F401

SEPARATOR = " , "

# Where --apply writes the original rows before changing anything. This is a
# one-way edit to live records, so the previous state is captured first.
BACKUP_DIR = Path(__file__).resolve().parents[3] / "data" / "backups"


def write_backup(documents: list[SalesDocument]) -> Path:
    """Save the current lines of every affected document, so the split can be
    undone by hand if the result is not what was wanted."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"sales-lines-before-split-{stamp}.json"

    payload = [
        {
            "document_id": str(document.id),
            "doc_type": document.doc_type,
            "doc_number": document.doc_number,
            "total_items": document.total_items,
            "lines": [
                {
                    "id": str(line.id),
                    "line_number": line.line_number,
                    "description": line.description,
                    "uom": line.uom,
                    "quantity": str(line.quantity),
                    "unit_price": str(line.unit_price),
                    "tax_percent": str(line.tax_percent),
                    "currency": line.currency,
                }
                for line in sorted(document.lines, key=lambda l: l.line_number or 0)
            ],
        }
        for document in documents
    ]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def split_description(text: str) -> list[str]:
    """The individual product names inside one concatenated description."""
    parts = [p.strip() for p in text.split(SEPARATOR)]
    return [p for p in parts if p]


def find_candidates(db: Session) -> list[SalesDocument]:
    """Documents holding at least one line with a concatenated description."""
    doc_ids = db.scalars(
        select(SalesDocumentLine.document_id)
        .where(SalesDocumentLine.description.contains(SEPARATOR))
        .distinct()
    ).all()
    if not doc_ids:
        return []
    return list(
        db.scalars(
            select(SalesDocument)
            .options(selectinload(SalesDocument.lines))
            .where(SalesDocument.id.in_(doc_ids))
            .order_by(SalesDocument.doc_number)
        ).all()
    )


def rebuild_lines(document: SalesDocument) -> list[SalesDocumentLine]:
    """The document's lines with concatenated ones expanded in place.

    Order is preserved: a split line's parts occupy the position the original
    held, and everything is renumbered from 1 afterwards.
    """
    rebuilt: list[SalesDocumentLine] = []

    for line in sorted(document.lines, key=lambda l: l.line_number or 0):
        if not line.description or SEPARATOR not in line.description:
            rebuilt.append(line)
            continue

        parts = split_description(line.description)
        if len(parts) < 2:
            rebuilt.append(line)
            continue

        # Reuse the original row for the first product so its id survives —
        # anything referring to that line keeps pointing at something real.
        line.description = parts[0]
        rebuilt.append(line)

        for part in parts[1:]:
            rebuilt.append(SalesDocumentLine(
                description=part,
                item_id=None,
                item_code=None,
                uom=line.uom,
                hs_code=None,
                quantity=Decimal("1"),
                unit_price=Decimal("0"),
                currency=line.currency,
                discount_percent=Decimal("0"),
                tax_percent=line.tax_percent,
                gross_amount=Decimal("0"),
                discount_amount=Decimal("0"),
                taxable_amount=Decimal("0"),
                tax_amount=Decimal("0"),
                net_amount=Decimal("0"),
            ))

    for position, line in enumerate(rebuilt, start=1):
        line.line_number = position
    return rebuilt


def run(db: Session, apply: bool) -> None:
    documents = find_candidates(db)
    if not documents:
        print("Nothing to split — no line contains a concatenated description.")
        return

    print(f"{'APPLYING' if apply else 'DRY RUN - no changes will be written'}\n")

    if apply:
        backup = write_backup(documents)
        print(f"  originals saved to : {backup}\n")

    lines_before = 0
    lines_after = 0
    # rebuild_lines edits the first part's description in place, so it must be
    # called once per document and the result kept — calling it again would
    # find nothing left to split.
    plan: list[tuple[SalesDocument, list[SalesDocumentLine]]] = []
    for document in documents:
        before = len(document.lines)
        rebuilt = rebuild_lines(document)
        lines_before += before
        lines_after += len(rebuilt)
        plan.append((document, rebuilt))

        if apply:
            document.lines = rebuilt
            document.total_items = len(rebuilt)

    print(f"  quotations/orders affected : {len(documents):,}")
    print(f"  lines before               : {lines_before:,}")
    print(f"  lines after                : {lines_after:,}")
    print(f"  net new lines              : {lines_after - lines_before:,}")

    # Show the documents that actually gained the most lines, not the first
    # few alphabetically — those are the ones worth eyeballing.
    biggest = sorted(plan, key=lambda pair: -len(pair[1]))[:3]
    print("\n  largest three splits:")
    for document, rebuilt in biggest:
        print(f"\n    {document.doc_type} {document.doc_number} "
              f"({document.doc_date}) -> {len(rebuilt)} lines")
        for line in sorted(rebuilt, key=lambda l: l.line_number or 0):
            text = line.description or ""
            print(f"      {line.line_number}. {text[:78]}")

    if apply:
        db.commit()
        print("\nCommitted.")
    else:
        db.rollback()
        print("\nNothing written. Re-run with --apply to commit these changes.")


if __name__ == "__main__":
    session = SessionLocal()
    try:
        run(session, apply="--apply" in sys.argv)
    finally:
        session.close()
