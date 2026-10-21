"""
One-off repair: move sales orders onto the dated reference format.

Orders created before the numbering change carry the placeholder prefix form
(SO2600001). The old ERP numbers them YYYYMMDD followed by a counter that
restarts each day — 202609221 is the first order of 22 September 2026 — and
`app.sales.service.allocate_number` now issues them that way. This fixes the
ones issued before that.

    python -m app.sales.renumber_orders            # report only
    python -m app.sales.renumber_orders --apply     # write the changes

Each order is renumbered against its own document date, and the counter
starts above any number already used on that date, so nothing collides with
an imported order. Orders that already carry a dated reference are left alone.

Note this changes a business reference: the order number is the Invoice #
printed on a delivery note. If one of these has been sent out, the recipient
holds paperwork quoting the old number.
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.sales.models import SALES_ORDER, SalesDocument
from app.sales.service import highest_on_date

# Registers the tables the sales foreign keys point at.
from app.companies.models import Branch, Company, FinancialYear  # noqa: F401
from app.inventory.models import InventoryItem  # noqa: F401
from app.partners.models import BusinessPartner  # noqa: F401
from app.users.models import User  # noqa: F401

BACKUP_DIR = Path(__file__).resolve().parents[3] / "data" / "backups"

# Only the placeholder form this codebase used to generate (SO2600001). An
# imported reference like "1812025" or "202501181-02" is a real number from
# the old ERP that exists on paperwork, so it is left exactly as it arrived
# even though it does not match the new pattern.
PLACEHOLDER = re.compile(r"^SO\d+$")


def find_misnumbered(db: Session) -> list[SalesDocument]:
    """Orders still carrying a placeholder reference."""
    return [
        d for d in db.scalars(
            select(SalesDocument)
            .where(SalesDocument.doc_type == SALES_ORDER)
            .order_by(SalesDocument.doc_date, SalesDocument.created_at)
        ).all()
        if PLACEHOLDER.match(d.doc_number or "")
    ]


def run(db: Session, apply: bool) -> None:
    documents = find_misnumbered(db)
    if not documents:
        print("Nothing to renumber — every sales order already uses the dated format.")
        return

    # One counter per date, seeded above whatever that date already holds.
    counters: dict[str, int] = {}
    mapping: dict = {}
    for doc in documents:
        scope = doc.doc_date.strftime("%Y%m%d")
        if scope not in counters:
            counters[scope] = highest_on_date(db, doc.company_id, SALES_ORDER, doc.doc_date)
        counters[scope] += 1
        mapping[doc.id] = f"{scope}{counters[scope]}"

    print(f"{'APPLYING' if apply else 'DRY RUN - no changes will be written'}\n")
    print(f"  sales orders to renumber : {len(documents)}\n")
    for doc in documents:
        print(f"    {doc.doc_number:>12}  ->  {mapping[doc.id]:>12}   "
              f"{doc.doc_date}  {doc.status:<10} {doc.net_receivable}")

    clashes = defaultdict(int)
    for value in mapping.values():
        clashes[value] += 1
    duplicated = [v for v, n in clashes.items() if n > 1]
    if duplicated:
        print(f"\n  REFUSING: these new numbers are not unique: {duplicated}")
        db.rollback()
        return

    if apply:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = BACKUP_DIR / f"orders-before-renumber-{stamp}.json"
        path.write_text(json.dumps([
            {"id": str(d.id), "old_doc_number": d.doc_number,
             "new_doc_number": mapping[d.id], "doc_date": str(d.doc_date),
             "status": d.status}
            for d in documents
        ], indent=2), encoding="utf-8")
        print(f"\n  originals saved to : {path}")

        for doc in documents:
            doc.doc_number = mapping[doc.id]
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
