"""
Import customers and contacts from the legacy Contacts Grid export.

    python -m app.partners.import_legacy

Reads data/partners/Contacts_Grid.xlsx. The export is a *contacts* list, so
one partner is created per distinct Account and each row becomes a contact
under it. Idempotent — partners match on name, contacts on name within a
partner.
"""

import argparse
import sys
import uuid
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.companies.models import Company
from app.core.database import SessionLocal
from app.partners.models import BusinessPartner, PartnerContact

DEFAULT_FILE = Path(__file__).resolve().parents[3] / "data" / "partners" / "Contacts_Grid.xlsx"


def clean(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() != "none" else None


def slug_code(name: str, taken: set[str]) -> str:
    """Short stable code from the account name, e.g. KAMAL TEXTILE -> KAMTEX."""
    letters = "".join(c for c in name.upper() if c.isalnum())
    base = (letters[:8] or "PARTNER")
    code = base
    n = 1
    while code in taken:
        n += 1
        code = f"{base[:6]}{n:02d}"
    taken.add(code)
    return code


def main() -> None:
    parser = argparse.ArgumentParser(description="Import partners from the contacts export.")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    args = parser.parse_args()

    if not args.file.exists():
        print(f"ERROR: {args.file} not found.", file=sys.stderr)
        raise SystemExit(1)

    from openpyxl import load_workbook

    wb = load_workbook(args.file, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = ws.iter_rows(values_only=True)
    header = [clean(h) or f"col{i}" for i, h in enumerate(next(rows))]
    idx = {h.upper(): i for i, h in enumerate(header)}

    def cell(row, name):
        i = idx.get(name.upper())
        return clean(row[i]) if i is not None and i < len(row) else None

    db: Session = SessionLocal()
    counts = Counter()
    try:
        company = db.scalar(select(Company).order_by(Company.created_at).limit(1))
        if company is None:
            print("ERROR: no company. Run: python -m app.core.seed", file=sys.stderr)
            raise SystemExit(1)

        partners = {
            p.name.upper(): p
            for p in db.scalars(
                select(BusinessPartner).where(BusinessPartner.company_id == company.id))
        }
        taken_codes = {p.code for p in partners.values()}

        for row in rows:
            if not any(c is not None for c in row):
                continue
            account = cell(row, "Account")
            contact_name = cell(row, "Contact")
            if not account:
                counts["skipped (no account)"] += 1
                continue

            partner = partners.get(account.upper())
            if partner is None:
                partner = BusinessPartner(
                    id=uuid.uuid4(),
                    company_id=company.id,
                    code=slug_code(account, taken_codes),
                    name=account,
                    is_customer=True,
                    territory=cell(row, "Account Territory"),
                    address=cell(row, "Address"),
                    phone=cell(row, "Phone"),
                    cell=cell(row, "Cell"),
                    email=cell(row, "Email"),
                )
                db.add(partner)
                db.flush()
                partners[account.upper()] = partner
                counts["partners imported"] += 1

            if contact_name:
                exists = db.scalar(
                    select(PartnerContact).where(
                        PartnerContact.partner_id == partner.id,
                        PartnerContact.contact_name == contact_name,
                    )
                )
                if exists:
                    counts["contacts already present"] += 1
                else:
                    db.add(PartnerContact(
                        id=uuid.uuid4(),
                        company_id=company.id,
                        partner_id=partner.id,
                        contact_name=contact_name,
                        title=cell(row, "Title"),
                        email=cell(row, "Email"),
                        phone=cell(row, "Phone"),
                        cell=cell(row, "Cell"),
                        description=cell(row, "Description"),
                    ))
                    counts["contacts imported"] += 1

        db.commit()

        print("\n" + "=" * 56)
        print("  PARTNER IMPORT REPORT")
        print("=" * 56)
        for key, value in sorted(counts.items()):
            print(f"  {key:<32} {value:>6}")
        print("=" * 56 + "\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
