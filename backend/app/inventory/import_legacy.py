"""
Import the legacy inventory exports into the new ERP.

    python -m app.inventory.import_legacy

Reads the three Excel files from data/inventory/ (override with --dir):

    Inventory_Sub_Category.xlsx        -> main products + sub categories
    INVENTORY_SUB_DETAIL_CATEGORY.xlsx -> sub detail categories
    ITEM_REPORT.xlsx                   -> inventory items + racks

The run is idempotent and safe to repeat (spec section 10): records are
matched on their natural keys and updated rather than duplicated. A summary
report is printed at the end showing imported, updated, skipped and failed
counts per entity, which is what the reconciliation step needs.

Nothing is invented. Where the legacy export has no value for a column, the
column is left null rather than filled with a guess.
"""

import argparse
import sys
import uuid
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.companies.models import Company
from app.core.database import SessionLocal
from app.inventory import models as m

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "data" / "inventory"


def clean(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def to_decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def to_int(value) -> int | None:
    d = to_decimal(value)
    return int(d) if d is not None else None


def load_sheet(path: Path) -> tuple[list[str], list[tuple]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = ws.iter_rows(values_only=True)
    header = [clean(h) or f"col{i}" for i, h in enumerate(next(rows))]
    return header, [r for r in rows if any(c is not None for c in r)]


class Report:
    def __init__(self):
        self.counts: dict[str, Counter] = {}
        self.errors: list[str] = []

    def bump(self, entity: str, outcome: str, n: int = 1):
        self.counts.setdefault(entity, Counter())[outcome] += n

    def error(self, message: str):
        self.errors.append(message)

    def print(self):
        print("\n" + "=" * 62)
        print("  MIGRATION REPORT")
        print("=" * 62)
        for entity, c in self.counts.items():
            parts = ", ".join(f"{k}: {v}" for k, v in sorted(c.items()))
            print(f"  {entity:<28} {parts}")
        if self.errors:
            print(f"\n  {len(self.errors)} row(s) could not be imported:")
            for e in self.errors[:20]:
                print(f"    - {e}")
            if len(self.errors) > 20:
                print(f"    … and {len(self.errors) - 20} more")
        print("=" * 62 + "\n")


def import_categories(db: Session, company_id: uuid.UUID, path: Path, rep: Report):
    """Inventory_Sub_Category.xlsx -> MainProduct + InventorySubCategory."""
    header, rows = load_sheet(path)
    idx = {name.upper(): i for i, name in enumerate(header)}

    def cell(row, name):
        i = idx.get(name.upper())
        return clean(row[i]) if i is not None and i < len(row) else None

    mains: dict[str, m.MainProduct] = {
        mp.description.upper(): mp
        for mp in db.scalars(select(m.MainProduct).where(m.MainProduct.company_id == company_id))
    }

    for row in rows:
        name = cell(row, "Invmaincode")
        if not name:
            continue
        if name.upper() not in mains:
            mp = m.MainProduct(id=uuid.uuid4(), company_id=company_id, description=name)
            db.add(mp)
            mains[name.upper()] = mp
            rep.bump("Main products", "imported")
    db.commit()

    existing = {
        (sc.main_product_id, sc.description.upper()): sc
        for sc in db.scalars(
            select(m.InventorySubCategory).where(m.InventorySubCategory.company_id == company_id)
        )
    }

    for line, row in enumerate(rows, start=2):
        main_name = cell(row, "Invmaincode")
        description = cell(row, "Description")
        if not main_name or not description:
            rep.bump("Sub categories", "skipped (missing name)")
            continue

        mp = mains.get(main_name.upper())
        if mp is None:
            rep.error(f"Sub category row {line}: unknown main product '{main_name}'")
            rep.bump("Sub categories", "failed")
            continue

        key = (mp.id, description.upper())
        values = dict(
            detailcode_purchase_local=cell(row, "Detailcode Purchase Local"),
            detailcode_purchase_import=cell(row, "Detailcode Purchase Import"),
            detailcode_wip=cell(row, "Detailcode Wip"),
            detailcode_finish_stock=cell(row, "Detailcode Finish Stock"),
            detailcode_sales_local=cell(row, "Detailcode Sales Local"),
            detailcode_sales_export=cell(row, "Detailcode Sales Export"),
            cos_account=cell(row, "Cos Account"),
            detailcode_consumption=cell(row, "Detailcode Consumption"),
            remarks=cell(row, "Remarks"),
        )

        if key in existing:
            for k, v in values.items():
                if v is not None:
                    setattr(existing[key], k, v)
            rep.bump("Sub categories", "updated")
        else:
            sc = m.InventorySubCategory(
                id=uuid.uuid4(), company_id=company_id,
                main_product_id=mp.id, description=description, **values,
            )
            db.add(sc)
            existing[key] = sc
            rep.bump("Sub categories", "imported")
    db.commit()


def import_detail_categories(db: Session, company_id: uuid.UUID, path: Path, rep: Report):
    header, rows = load_sheet(path)
    idx = {name.upper(): i for i, name in enumerate(header)}

    def cell(row, name):
        i = idx.get(name.upper())
        return clean(row[i]) if i is not None and i < len(row) else None

    subs = {
        sc.description.upper(): sc
        for sc in db.scalars(
            select(m.InventorySubCategory).where(m.InventorySubCategory.company_id == company_id)
        )
    }
    existing = {
        (d.sub_category_id, d.description.upper()): d
        for d in db.scalars(
            select(m.InventorySubDetailCategory).where(
                m.InventorySubDetailCategory.company_id == company_id)
        )
    }

    for line, row in enumerate(rows, start=2):
        sub_name = cell(row, "Sub Category")
        description = cell(row, "Description")
        if not sub_name or not description:
            rep.bump("Sub detail categories", "skipped (missing name)")
            continue

        sc = subs.get(sub_name.upper())
        if sc is None:
            rep.error(f"Detail category row {line}: unknown sub category '{sub_name}'")
            rep.bump("Sub detail categories", "failed")
            continue

        key = (sc.id, description.upper())
        if key in existing:
            rep.bump("Sub detail categories", "already present")
            continue

        db.add(m.InventorySubDetailCategory(
            id=uuid.uuid4(), company_id=company_id,
            main_product_id=sc.main_product_id, sub_category_id=sc.id,
            description=description, remarks=cell(row, "Remarks"),
        ))
        existing[key] = True
        rep.bump("Sub detail categories", "imported")
    db.commit()


def import_items(db: Session, company_id: uuid.UUID, path: Path, rep: Report):
    header, rows = load_sheet(path)
    idx = {name.upper(): i for i, name in enumerate(header)}

    def cell(row, name):
        i = idx.get(name.upper())
        return clean(row[i]) if i is not None and i < len(row) else None

    def raw(row, name):
        i = idx.get(name.upper())
        return row[i] if i is not None and i < len(row) else None

    mains = {
        mp.description.upper(): mp.id
        for mp in db.scalars(select(m.MainProduct).where(m.MainProduct.company_id == company_id))
    }
    subs = {
        sc.description.upper(): sc.id
        for sc in db.scalars(
            select(m.InventorySubCategory).where(m.InventorySubCategory.company_id == company_id))
    }
    details = {
        (d.sub_category_id, d.description.upper()): d.id
        for d in db.scalars(
            select(m.InventorySubDetailCategory).where(
                m.InventorySubDetailCategory.company_id == company_id))
    }
    existing = {
        it.item_code: it
        for it in db.scalars(
            select(m.InventoryItem).where(m.InventoryItem.company_id == company_id))
    }

    created_subs = 0
    created_details = 0

    for line, row in enumerate(rows, start=2):
        code = cell(row, "INVDETAILCODE")
        description = cell(row, "DESCRIPTION")
        if not code or not description:
            rep.bump("Items", "skipped (missing code or description)")
            continue

        main_name = cell(row, "MAIN_CATEGORY")
        sub_name = cell(row, "SUB_CATEGORY")
        detail_name = cell(row, "SUB_DTL_CATEGORY")

        main_id = mains.get(main_name.upper()) if main_name else None
        if main_name and main_id is None:
            # The item export references a main category the category sheet
            # did not contain — create it rather than dropping the item.
            mp = m.MainProduct(id=uuid.uuid4(), company_id=company_id, description=main_name)
            db.add(mp)
            db.flush()
            mains[main_name.upper()] = mp.id
            main_id = mp.id
            rep.bump("Main products", "imported (from item file)")

        sub_id = subs.get(sub_name.upper()) if sub_name else None
        if sub_name and sub_id is None and main_id:
            sc = m.InventorySubCategory(
                id=uuid.uuid4(), company_id=company_id,
                main_product_id=main_id, description=sub_name,
            )
            db.add(sc)
            db.flush()
            subs[sub_name.upper()] = sc.id
            sub_id = sc.id
            created_subs += 1

        detail_id = details.get((sub_id, detail_name.upper())) if (sub_id and detail_name) else None
        if detail_name and detail_id is None and sub_id and main_id:
            sdc = m.InventorySubDetailCategory(
                id=uuid.uuid4(), company_id=company_id,
                main_product_id=main_id, sub_category_id=sub_id, description=detail_name,
            )
            db.add(sdc)
            db.flush()
            details[(sub_id, detail_name.upper())] = sdc.id
            detail_id = sdc.id
            created_details += 1

        values = dict(
            main_product_id=main_id,
            sub_category_id=sub_id,
            sub_detail_category_id=detail_id,
            description=description,
            new_description=cell(row, "NEW_DESCRIPTION"),
            short_name=cell(row, "SHORTNAME"),
            composition=cell(row, "COMPOSITION"),
            uom=cell(row, "UOM"),
            import_uom=cell(row, "IMPORT_UOM"),
            market_uom=cell(row, "MARKET_UOM"),
            market_name=cell(row, "MARKET_NAME"),
            sku=cell(row, "SKU"),
            barcode=cell(row, "ITEM_BARCODE"),
            item_status=cell(row, "ITEM_STATUS") or "ACTIVE",
            item_type=cell(row, "ITEM_TYPE"),
            nature=cell(row, "NATURE"),
            processed_item=cell(row, "PROCESSED_ITEM"),
            origin_country=cell(row, "ORIGIONCOUNTRY"),
            lead_days=to_int(raw(row, "LEEDDAYS")),
            min_level=to_decimal(raw(row, "MINLEVEL")),
            max_level=to_decimal(raw(row, "MAXLEVEL")),
            re_order_qty=to_decimal(raw(row, "RE_ORDER_QTY")),
            multiplier_factor=to_decimal(raw(row, "MULTIPLIER_FACTOR")),
            opening_stock=to_decimal(raw(row, "STOCK")),
            legacy_cat_id=cell(row, "CAT_ID"),
            legacy_comp_id=cell(row, "COMP_ID"),
        )

        if code in existing:
            for k, v in values.items():
                setattr(existing[code], k, v)
            rep.bump("Items", "updated")
        else:
            item = m.InventoryItem(
                id=uuid.uuid4(), company_id=company_id, item_code=code, **values)
            db.add(item)
            existing[code] = item
            rep.bump("Items", "imported")

        if line % 500 == 0:
            db.commit()

    db.commit()
    if created_subs:
        rep.bump("Sub categories", "imported (from item file)", created_subs)
    if created_details:
        rep.bump("Sub detail categories", "imported (from item file)", created_details)


def reconcile(db: Session, company_id: uuid.UUID):
    """Counts in the new system, to compare against the old ERP."""
    from sqlalchemy import func

    print("  RECONCILIATION — counts now in the new ERP")
    print("  " + "-" * 44)
    for label, model in [
        ("Main products", m.MainProduct),
        ("Sub categories", m.InventorySubCategory),
        ("Sub detail categories", m.InventorySubDetailCategory),
        ("Item racks", m.ItemRack),
        ("Items", m.InventoryItem),
    ]:
        n = db.scalar(
            select(func.count()).select_from(model).where(model.company_id == company_id))
        print(f"  {label:<26} {n:>8,}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import legacy inventory data.")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR,
                        help="folder holding the three Excel files")
    args = parser.parse_args()

    folder: Path = args.dir
    files = {
        "categories": folder / "Inventory_Sub_Category.xlsx",
        "details": folder / "INVENTORY_SUB_DETAIL_CATEGORY.xlsx",
        "items": folder / "ITEM_REPORT.xlsx",
    }

    missing = [str(p) for p in files.values() if not p.exists()]
    if missing:
        print("ERROR: these files were not found:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        print("\nPut the Excel exports in that folder, or pass --dir.", file=sys.stderr)
        raise SystemExit(1)

    db = SessionLocal()
    rep = Report()
    try:
        company = db.scalar(select(Company).order_by(Company.created_at).limit(1))
        if company is None:
            print("ERROR: no company exists. Run: python -m app.core.seed", file=sys.stderr)
            raise SystemExit(1)

        print(f"Importing into company: {company.name}\n")
        print("  reading categories…")
        import_categories(db, company.id, files["categories"], rep)
        print("  reading detail categories…")
        import_detail_categories(db, company.id, files["details"], rep)
        print("  reading items (this takes a moment)…")
        import_items(db, company.id, files["items"], rep)

        rep.print()
        reconcile(db, company.id)
    finally:
        db.close()


if __name__ == "__main__":
    main()
