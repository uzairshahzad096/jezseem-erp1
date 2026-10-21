"""
One-off repair: move quotations created before the numbering fix onto the end
of the imported series.

The document counter started at zero, so the first quotations entered in this
system were numbered 1 and 2 — restarting a series that the imported records
had already run up to 1579. `app.sales.service.allocate_number` now seeds the
counter from the highest number in use, so new quotations continue correctly;
this fixes the ones issued before that.

    python -m app.sales.renumber_quotations            # report only
    python -m app.sales.renumber_quotations --apply     # write the changes

Only quotations created in the application are touched — imported records keep
the numbers they arrived with, whatever they are. Renumbering is by creation
order, so the oldest gets the lowest new number.

Note this changes a business reference. If one of these quotations has already
been sent to a customer, they hold paperwork quoting the old number.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import BigInteger, func, select
from sqlalchemy.orm import Session

from app.common.numbering import DocumentSequence
from app.core.database import SessionLocal
from app.sales.models import QUOTATION, SalesDocument

# Registers the tables the sales foreign keys point at.
from app.companies.models import Branch, Company, FinancialYear  # noqa: F401
from app.inventory.models import InventoryItem  # noqa: F401
from app.partners.models import BusinessPartner  # noqa: F401
from app.users.models import User  # noqa: F401

BACKUP_DIR = Path(__file__).resolve().parents[3] / "data" / "backups"
NUMERIC = "^[0-9]+$"


def _max_number(db: Session, only_imported: bool) -> int:
    stmt = select(func.max(func.cast(SalesDocument.doc_number, BigInteger))).where(
        SalesDocument.doc_type == QUOTATION,
        SalesDocument.doc_number.op("~")(NUMERIC),
    )
    if only_imported:
        stmt = stmt.where(SalesDocument.created_by.is_(None))
    return int(db.scalar(stmt) or 0)


def find_misnumbered(db: Session) -> list[SalesDocument]:
    """Quotations entered in the app that sit inside the imported range."""
    imported_max = _max_number(db, only_imported=True)
    if not imported_max:
        return []
    return list(
        db.scalars(
            select(SalesDocument)
            .where(
                SalesDocument.doc_type == QUOTATION,
                SalesDocument.created_by.is_not(None),
                SalesDocument.doc_number.op("~")(NUMERIC),
                func.cast(SalesDocument.doc_number, BigInteger) <= imported_max,
            )
            .order_by(SalesDocument.created_at)
        ).all()
    )


def write_backup(documents: list[SalesDocument], mapping: dict) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"quotations-before-renumber-{stamp}.json"
    path.write_text(json.dumps([
        {
            "id": str(d.id),
            "old_doc_number": d.doc_number,
            "new_doc_number": mapping[d.id],
            "doc_date": str(d.doc_date),
            "status": d.status,
            "net_receivable": str(d.net_receivable),
        }
        for d in documents
    ], indent=2), encoding="utf-8")
    return path


def run(db: Session, apply: bool) -> None:
    documents = find_misnumbered(db)
    if not documents:
        print("Nothing to renumber — every quotation already sits above the imported series.")
        return

    highest = _max_number(db, only_imported=False)
    mapping = {d.id: str(highest + i) for i, d in enumerate(documents, start=1)}
    last = highest + len(documents)

    print(f"{'APPLYING' if apply else 'DRY RUN - no changes will be written'}\n")
    print(f"  imported series ends at : {_max_number(db, only_imported=True)}")
    print(f"  highest number in use   : {highest}")
    print(f"  quotations to renumber  : {len(documents)}\n")

    for d in documents:
        print(f"    {d.doc_number:>6}  ->  {mapping[d.id]:>6}   "
              f"{d.doc_date}  {d.status:<9} {d.net_receivable}")

    if apply:
        print(f"\n  originals saved to : {write_backup(documents, mapping)}")
        for d in documents:
            d.doc_number = mapping[d.id]

        # Carry the counter past the numbers just handed out, so the next
        # quotation does not land on one of them.
        for row in db.scalars(
            select(DocumentSequence).where(DocumentSequence.doc_type == QUOTATION)
        ).all():
            if row.last_number < last:
                row.last_number = last

        db.commit()
        print(f"\nCommitted. The next new quotation will be {last + 1}.")
    else:
        db.rollback()
        print(f"\n  the next new quotation would then be {last + 1}")
        print("\nNothing written. Re-run with --apply to commit these changes.")


if __name__ == "__main__":
    session = SessionLocal()
    try:
        run(session, apply="--apply" in sys.argv)
    finally:
        session.close()
