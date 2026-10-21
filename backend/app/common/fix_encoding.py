"""
One-off repair: undo mis-decoded text from the legacy imports.

The exports were read as Windows-1252 when their bytes were really UTF-8, so
every non-ASCII character arrived as the Latin letters its bytes happen to
spell. An Arabic comma (U+060C, bytes D8 8C) became "OE-with-stroke"; an
en dash became three characters; a degree sign became two.

    Marzipura Narwala Road[ØŒ] Faisalabad     <- stored
    Marzipura Narwala Road[،] Faisalabad      <- meant

    python -m app.common.fix_encoding            # report only
    python -m app.common.fix_encoding --apply     # write the changes

The repair is the exact inverse of the damage: encode the stored text back to
Windows-1252 bytes and decode those as UTF-8. A value is only rewritten when
that round trip succeeds cleanly and actually changes something, so text that
was always correct is left alone.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal

BACKUP_DIR = Path(__file__).resolve().parents[3] / "data" / "backups"

# Every imported free-text column, by table.
TARGETS: dict[str, list[str]] = {
    "business_partners": ["name", "address", "city", "territory", "ntn", "stn",
                          "phone", "cell", "email", "payment_terms"],
    "partner_contacts": ["contact_name", "title", "email", "description"],
    "inventory_items": ["description", "new_description", "short_name",
                        "composition", "market_name", "origin_country"],
    "sales_document_lines": ["description", "item_code", "uom"],
    "sales_documents": ["remarks", "payment_terms", "demand_number"],
    "main_products": ["description", "remarks"],
    "inventory_sub_categories": ["description", "remarks"],
    "inventory_sub_detail_categories": ["description", "remarks"],
}


def repair(value: str) -> str | None:
    """The corrected text, or None when the value needs no repair.

    Round-tripping only succeeds on genuinely mis-decoded text: a correct
    string either fails to encode as Windows-1252 or fails to decode as UTF-8,
    and is left untouched.
    """
    try:
        fixed = value.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    return fixed if fixed != value else None


def find(db: Session) -> list[dict]:
    found = []
    for table, columns in TARGETS.items():
        rows = db.execute(text(f"select id, {', '.join(columns)} from {table}")).fetchall()
        for row in rows:
            for column, value in zip(columns, row[1:]):
                if not isinstance(value, str) or not value:
                    continue
                fixed = repair(value)
                if fixed is not None:
                    found.append({"table": table, "id": str(row[0]), "column": column,
                                  "before": value, "after": fixed})
    return found


def run(db: Session, apply: bool) -> None:
    found = find(db)
    if not found:
        print("No mis-decoded text found.")
        return

    print(f"{'APPLYING' if apply else 'DRY RUN - no changes will be written'}\n")

    by_table: dict[str, int] = {}
    for hit in found:
        by_table[hit["table"]] = by_table.get(hit["table"], 0) + 1
    for table, count in sorted(by_table.items()):
        print(f"  {table:34} {count:4} field(s)")
    print(f"  {'total':34} {len(found):4}")

    print("\n  sample of what changes:")
    for hit in found[:6]:
        print(f"\n    {hit['table']}.{hit['column']}")
        print("      before:", ascii(hit["before"][:66]))
        print("      after :", ascii(hit["after"][:66]))

    if apply:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = BACKUP_DIR / f"text-before-encoding-fix-{stamp}.json"
        path.write_text(json.dumps(found, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  originals saved to : {path}")

        for hit in found:
            db.execute(
                text(f"update {hit['table']} set {hit['column']} = :val where id = :id"),
                {"val": hit["after"], "id": hit["id"]},
            )
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
