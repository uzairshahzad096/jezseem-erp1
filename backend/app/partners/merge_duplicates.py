"""
One-off repair: collapse duplicate customer records onto the ledger account.

Each customer arrived in this database more than once:

    111112000025  AL-ABBAS FABRICS (PVT) LTD.   address, NTN, cell   <- ledger
    111112000372  AL-ABBAS FABRICS (PVT) LTD.   address only
    AEXZ          AL-ABBAS FABRICS (PVT) LTD.   nothing

The 12-digit codes are the ledger accounts and carry the details an invoice
needs. The short codes are bare rows created when the quotations were loaded,
holding a name and nothing else — and it is those that the documents point at.
That is why the Bill To block on a printed quotation shows a customer name
with no address, NTN or STN, even though the data is sitting in the next row.

This keeps the richest row in each name group, moves every document and
contact onto it, fills any gap in it from the rows being removed, and deletes
the leftovers.

    python -m app.partners.merge_duplicates            # report only
    python -m app.partners.merge_duplicates --apply     # write the changes

Grouping is by exact name within a company. Two genuinely different customers
sharing a name character-for-character would be merged, so the dry run prints
the groups for checking first.
"""

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.partners.models import BusinessPartner, PartnerContact  # noqa: F401

# Registers the tables whose foreign keys point at business_partners.
from app.companies.models import Branch, Company, FinancialYear  # noqa: F401
from app.gatepass.models import GatePass  # noqa: F401
from app.inventory.models import InventoryItem  # noqa: F401
from app.procurement.models import PurchaseOrder  # noqa: F401
from app.sales.models import SalesDocument  # noqa: F401
from app.users.models import User  # noqa: F401

BACKUP_DIR = Path(__file__).resolve().parents[3] / "data" / "backups"

# Everything that references a partner, as (table, column). Repointed before
# the duplicate row is deleted so no foreign key is ever left dangling.
REFERENCES = [
    ("sales_documents", "customer_id"),
    ("gate_passes", "party_id"),
    ("purchase_orders", "supplier_id"),
    ("partner_contacts", "partner_id"),
]

# Fields worth keeping. Used both to score a row and to fill the survivor's
# gaps from the rows being merged into it.
DETAIL_FIELDS = [
    "address", "city", "territory", "ntn", "stn",
    "phone", "cell", "email", "payment_terms",
]


def score(partner: BusinessPartner) -> tuple:
    """How complete a row is. Ranked by populated detail fields, then by a
    longer code — the 12-digit ledger account beats the short stub — then by
    age, so the result does not depend on row order."""
    filled = sum(1 for f in DETAIL_FIELDS if (getattr(partner, f) or "").strip())
    return (filled, len(partner.code or ""), -(partner.created_at.timestamp()
                                               if partner.created_at else 0))


def groups(db: Session) -> list[list[BusinessPartner]]:
    """Name groups holding more than one row, richest row first."""
    by_name: dict[tuple, list[BusinessPartner]] = defaultdict(list)
    for partner in db.scalars(select(BusinessPartner)).all():
        by_name[(partner.company_id, partner.name.strip())].append(partner)

    out = []
    for members in by_name.values():
        if len(members) > 1:
            out.append(sorted(members, key=score, reverse=True))
    return sorted(out, key=lambda g: g[0].name)


def reference_counts(db: Session, partner_id) -> dict[str, int]:
    counts = {}
    for table, column in REFERENCES:
        counts[table] = db.execute(
            text(f"select count(*) from {table} where {column} = :pid"),
            {"pid": partner_id},
        ).scalar() or 0
    return counts


def write_backup(db: Session, plan: list[tuple]) -> Path:
    """Record every row about to be deleted, with what pointed at it."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"partners-before-merge-{stamp}.json"

    payload = []
    for survivor, duplicates in plan:
        payload.append({
            "kept": {"id": str(survivor.id), "code": survivor.code, "name": survivor.name},
            "removed": [
                {
                    "id": str(d.id),
                    "code": d.code,
                    "name": d.name,
                    **{f: getattr(d, f) for f in DETAIL_FIELDS},
                    "references": reference_counts(db, d.id),
                }
                for d in duplicates
            ],
        })
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def run(db: Session, apply: bool) -> None:
    all_groups = groups(db)
    if not all_groups:
        print("No duplicate customer names found.")
        return

    plan = [(g[0], g[1:]) for g in all_groups]

    print(f"{'APPLYING' if apply else 'DRY RUN - no changes will be written'}\n")

    if apply:
        print(f"  originals saved to : {write_backup(db, plan)}\n")

    moved = defaultdict(int)
    gaps_filled = 0
    removed = 0

    for survivor, duplicates in plan:
        for duplicate in duplicates:
            # Take anything the survivor is missing before dropping the row.
            for field in DETAIL_FIELDS:
                if not (getattr(survivor, field) or "").strip():
                    value = (getattr(duplicate, field) or "").strip()
                    if value:
                        if apply:
                            setattr(survivor, field, value)
                        gaps_filled += 1

            # A partner that is a supplier in one row and a customer in another
            # is both; losing either flag would hide it from a picker.
            if apply:
                survivor.is_customer = survivor.is_customer or duplicate.is_customer
                survivor.is_supplier = survivor.is_supplier or duplicate.is_supplier

            for table, column in REFERENCES:
                count = db.execute(
                    text(f"select count(*) from {table} where {column} = :pid"),
                    {"pid": duplicate.id},
                ).scalar() or 0
                if not count:
                    continue
                moved[table] += count
                if apply:
                    db.execute(
                        text(f"update {table} set {column} = :keep where {column} = :drop"),
                        {"keep": survivor.id, "drop": duplicate.id},
                    )

            removed += 1
            if apply:
                db.delete(duplicate)

    print(f"  duplicate names          : {len(plan):,}")
    print(f"  rows to remove           : {removed:,}")
    print(f"  blank fields filled in   : {gaps_filled:,}")
    for table, _ in REFERENCES:
        print(f"  {table:24} repointed : {moved[table]:,}")

    print("\n  three groups, richest row first (kept row marked >):")
    for survivor, duplicates in all_groups and plan[:3]:
        print(f"\n    {survivor.name[:60]}")
        for partner in [survivor, *duplicates]:
            mark = ">" if partner is survivor else " "
            bits = ", ".join(
                f"{f}={getattr(partner, f)[:28]}"
                for f in DETAIL_FIELDS if (getattr(partner, f) or "").strip()
            ) or "no details"
            print(f"      {mark} {partner.code:14} {bits}")

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
