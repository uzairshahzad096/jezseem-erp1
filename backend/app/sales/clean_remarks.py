"""
One-off repair: take the importer's bookkeeping out of the Remarks column.

The import wrote its own trail into Remarks, so the listing shows

    Legacy Report ID: 4493 | Legacy Quotation No: 1153

where the user expects to see what someone actually typed on the document.
Where a real remark existed it was prefixed with the same trail:

    FBR | Legacy Report ID: 4472 | Legacy Quotation No: 1461

    python -m app.sales.clean_remarks            # report only
    python -m app.sales.clean_remarks --apply     # write the changes

Nothing is thrown away. "Legacy Quotation No" is the only record of which
quotation a sales order came from, and it is currently held as prose that
nothing can query. Before the text is stripped it is resolved to the real
quotation and written to `source_document_id`, which is the column that
relationship belongs in — so the link survives, and the conversion guards
start protecting these documents too.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.sales.models import QUOTATION, SALES_ORDER, SalesDocument

# Registers the tables the sales foreign keys point at.
from app.companies.models import Branch, Company, FinancialYear  # noqa: F401
from app.inventory.models import InventoryItem  # noqa: F401
from app.partners.models import BusinessPartner  # noqa: F401
from app.users.models import User  # noqa: F401

BACKUP_DIR = Path(__file__).resolve().parents[3] / "data" / "backups"

# Segments the importer added. Matched whole, so a remark that merely mentions
# one of these words is left alone.
NOISE = [
    re.compile(r"^Legacy Report ID:\s*\d+$", re.I),
    re.compile(r"^Legacy Quotation No:\s*\d+$", re.I),
    re.compile(r"^\[?Source quotation no:\s*\d+\]?$", re.I),
]

QUOTATION_REF = re.compile(r"(?:Legacy Quotation No|Source quotation no):\s*(\d+)", re.I)


def clean(remarks: str) -> str | None:
    """What the user actually wrote, or None if that was nothing."""
    kept = [
        part.strip() for part in remarks.split("|")
        if part.strip() and not any(p.match(part.strip()) for p in NOISE)
    ]
    return " | ".join(kept) or None


def run(db: Session, apply: bool) -> None:
    documents = list(db.scalars(
        select(SalesDocument).where(SalesDocument.remarks.is_not(None))
    ).all())

    # Quotation number -> id, for resolving the reference held in the text.
    quotations = {
        (row.company_id, row.doc_number): row.id
        for row in db.execute(
            select(SalesDocument.company_id, SalesDocument.doc_number, SalesDocument.id)
            .where(SalesDocument.doc_type == QUOTATION)
        ).all()
    }

    changes, links = [], []
    for doc in documents:
        if doc.doc_type == SALES_ORDER and doc.source_document_id is None:
            match = QUOTATION_REF.search(doc.remarks)
            if match:
                source = quotations.get((doc.company_id, match.group(1)))
                if source:
                    links.append((doc, source))

        cleaned = clean(doc.remarks)
        if cleaned != doc.remarks:
            changes.append((doc, doc.remarks, cleaned))

    print(f"{'APPLYING' if apply else 'DRY RUN - no changes will be written'}\n")
    print(f"  documents with remarks        : {len(documents):,}")
    print(f"  remarks to rewrite            : {len(changes):,}")
    print(f"    ...becoming empty (cleared) : {sum(1 for _, _, c in changes if c is None):,}")
    print(f"  source_document_id to set     : {len(links):,}")

    print("\n  sample:")
    for doc, before, after in changes[:6]:
        print(f"\n    {doc.doc_type} {doc.doc_number}")
        print(f"      before: {before[:74]}")
        print(f"      after : {after if after is not None else '(cleared)'}")

    if apply:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = BACKUP_DIR / f"remarks-before-clean-{stamp}.json"
        path.write_text(json.dumps([
            {"id": str(d.id), "doc_type": d.doc_type, "doc_number": d.doc_number,
             "before": before, "after": after}
            for d, before, after in changes
        ], indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  originals saved to : {path}")

        for doc, source_id in links:
            doc.source_document_id = source_id
        for doc, _, after in changes:
            doc.remarks = after
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
