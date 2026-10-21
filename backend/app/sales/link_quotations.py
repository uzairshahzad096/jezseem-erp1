"""
Repair after the sales-order import: show and link each order's quotation.

The import wrote the old ERP's "Quotation No#" into `sales_documents.
quotation_number` exactly as Excel delivered it, as a float ("1633.0"). It
left `source_document_id` empty, and that link is what the Product Sale Order
listing reads, so the Quotation No# column showed nothing.

    python -m app.sales.link_quotations            # report only
    python -m app.sales.link_quotations --apply    # write the changes

1. "1633.0" becomes "1633".
2. The order is linked to its quotation when exactly one candidate fits:
   same number and same customer. The old ERP restarts quotation numbers
   each year, so when the customer has several quotations with that number,
   the latest one dated on or before the order is taken.
3. Orders with no safe match keep the number as text, so the listing still
   shows it; they are listed for checking instead of being guessed at.

Existing links are never overwritten. Originals are saved to data/backups/.
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
from app.sales.models import QUOTATION, SALES_ORDER, SalesDocument

# Registers the tables the sales foreign keys point at.
from app.companies.models import Branch, Company, FinancialYear  # noqa: F401
from app.inventory.models import InventoryItem  # noqa: F401
from app.partners.models import BusinessPartner  # noqa: F401
from app.users.models import User  # noqa: F401

BACKUP_DIR = Path(__file__).resolve().parents[3] / "data" / "backups"
FLOAT_TAIL = re.compile(r"\.0+$")


def normalise(value: str | None) -> str | None:
    """'1633.0' -> '1633'; blank -> None; anything else trimmed."""
    text = (value or "").strip()
    return FLOAT_TAIL.sub("", text) or None


def run(db: Session, apply: bool) -> None:
    orders = list(db.scalars(select(SalesDocument).where(SalesDocument.doc_type == SALES_ORDER)))

    quotations = defaultdict(list)  # (company, number) -> [(date, customer, id)]
    for q in db.execute(select(SalesDocument.company_id, SalesDocument.doc_number, SalesDocument.doc_date,
                               SalesDocument.customer_id, SalesDocument.id)
                        .where(SalesDocument.doc_type == QUOTATION)):
        quotations[(q.company_id, q.doc_number)].append(q)

    renamed, links, unmatched = [], [], []
    for order in orders:
        number = normalise(order.quotation_number)
        if number != order.quotation_number:
            renamed.append((order, order.quotation_number, number))
        if not number or order.source_document_id is not None:
            continue
        candidates = [q for q in quotations.get((order.company_id, number), [])
                      if q.customer_id == order.customer_id]
        if len(candidates) > 1:
            earlier = [q for q in candidates if q.doc_date <= order.doc_date]
            candidates = [max(earlier, key=lambda q: q.doc_date)] if earlier else candidates
        if len(candidates) == 1:
            links.append((order, candidates[0].id, number))
        else:
            reason = ("no quotation with this number" if not quotations.get((order.company_id, number))
                      else "number exists only for another customer" if not candidates
                      else "several quotations, none dated before the order")
            unmatched.append((order, number, reason))

    print(f"{'APPLYING' if apply else 'DRY RUN - no changes will be written'}\n")
    print(f"  sales orders                    : {len(orders):,}")
    print(f"  quotation numbers to clean      : {len(renamed):,}   (e.g. '1633.0' -> '1633')")
    print(f"  orders to link to a quotation   : {len(links):,}")
    print(f"  orders shown by number only     : {len(unmatched):,}")
    for reason in sorted({r for _, _, r in unmatched}):
        print(f"    {sum(1 for _, _, r in unmatched if r == reason):>4}  {reason}")
    if unmatched:
        print("\n  not linked (check these against the old ERP):")
        for order, number, reason in unmatched[:60]:
            print(f"    SO {order.doc_number}  {order.doc_date}  quotation {number}  - {reason}")

    if not apply:
        db.rollback()
        print("\nNothing written. Re-run with --apply to commit these changes.")
        return

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"sale-order-quotations-before-link-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps([
        {"id": str(o.id), "doc_number": o.doc_number, "quotation_number": o.quotation_number,
         "source_document_id": str(o.source_document_id) if o.source_document_id else None}
        for o in orders], indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  originals saved to : {path}")

    for order, _, number in renamed:
        order.quotation_number = number
    for order, quotation_id, _ in links:
        order.source_document_id = quotation_id
    db.commit()
    print("\nCommitted.")


if __name__ == "__main__":
    session = SessionLocal()
    try:
        run(session, apply="--apply" in sys.argv)
    finally:
        session.close()
