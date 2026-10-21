"""
One-off repair: bring uploaded gate passes onto the values the app uses.

The uploaded rows carry `pass_type = 'OUTWARD'` and `status = 'Posted'`. The
application filters on `pass_type = 'outward'` (the OUTWARD constant in
models.py) and uses the Draft/Approved/Closed/Cancelled vocabulary, so the
rows were in the table but matched nothing and the screen showed none of them.

    python -m app.gatepass.normalise            # report only
    python -m app.gatepass.normalise --apply     # write the changes

'Posted' becomes 'Approved' because it means the same thing on a gate pass —
the goods went through the gate. `is_approved` is set to match, which is the
flag the column mapping carries.

No stock is posted. These are historical passes whose movements already
happened in the old system; writing ledger entries now would double-count
against whatever opening balances get loaded.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.gatepass.models import INWARD, OUTWARD, GatePass

# Registers the tables the gate pass foreign keys point at.
from app.companies.models import Branch, Company, FinancialYear  # noqa: F401
from app.inventory.models import InventoryItem, ItemLocation  # noqa: F401
from app.partners.models import BusinessPartner  # noqa: F401
from app.sales.models import SalesDocument  # noqa: F401
from app.users.models import User  # noqa: F401

BACKUP_DIR = Path(__file__).resolve().parents[3] / "data" / "backups"

PASS_TYPES = {"outward": OUTWARD, "inward": INWARD}

# How the uploaded vocabulary maps onto the app's.
STATUSES = {
    "posted": "Approved",
    "approved": "Approved",
    "draft": "Draft",
    "closed": "Closed",
    "cancelled": "Cancelled",
    "canceled": "Cancelled",
}


def plan(db: Session) -> list[dict]:
    changes = []
    for gp in db.scalars(select(GatePass).order_by(GatePass.doc_date)).all():
        pass_type = PASS_TYPES.get((gp.pass_type or "").strip().lower())
        status = STATUSES.get((gp.status or "").strip().lower())

        new_type = pass_type if pass_type and pass_type != gp.pass_type else None
        new_status = status if status and status != gp.status else None
        # Approved passes should carry the flag the mapping calls Is Approved.
        target_flag = (status or gp.status) == "Approved"
        new_flag = target_flag if target_flag != gp.is_approved else None

        if new_type or new_status or new_flag is not None:
            changes.append({
                "id": str(gp.id), "doc_number": gp.doc_number,
                "pass_type": (gp.pass_type, new_type),
                "status": (gp.status, new_status),
                "is_approved": (gp.is_approved, new_flag),
                "_row": gp,
            })
    return changes


def run(db: Session, apply: bool) -> None:
    changes = plan(db)
    if not changes:
        print("Nothing to normalise — every gate pass already uses the app's values.")
        return

    print(f"{'APPLYING' if apply else 'DRY RUN - no changes will be written'}\n")
    print(f"  gate passes to update : {len(changes)}\n")

    def summarise(field: str) -> None:
        counts: dict = {}
        for c in changes:
            before, after = c[field]
            if after is not None:
                counts[f"{before!r} -> {after!r}"] = counts.get(f"{before!r} -> {after!r}", 0) + 1
        for text, n in sorted(counts.items()):
            print(f"    {field:12} {text:34} {n}")

    summarise("pass_type")
    summarise("status")
    summarise("is_approved")

    print("\n  first three:")
    for c in changes[:3]:
        print(f"    {c['doc_number']}: type {c['pass_type'][0]!r}"
              f"{'' if c['pass_type'][1] is None else ' -> ' + repr(c['pass_type'][1])}"
              f", status {c['status'][0]!r}"
              f"{'' if c['status'][1] is None else ' -> ' + repr(c['status'][1])}")

    if apply:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = BACKUP_DIR / f"gate-passes-before-normalise-{stamp}.json"
        path.write_text(json.dumps([
            {k: v for k, v in c.items() if k != "_row"} for c in changes
        ], indent=2, default=str), encoding="utf-8")
        print(f"\n  originals saved to : {path}")

        for c in changes:
            gp = c["_row"]
            if c["pass_type"][1]:
                gp.pass_type = c["pass_type"][1]
            if c["status"][1]:
                gp.status = c["status"][1]
            if c["is_approved"][1] is not None:
                gp.is_approved = c["is_approved"][1]
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
