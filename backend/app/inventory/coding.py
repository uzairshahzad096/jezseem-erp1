"""Allocating the 12-digit product code.

Every one of the 4,980 imported products follows the same shape, so a new
product keeps it rather than inventing a second scheme:

    1112        1002        0261
    └ sub       └ family    └ the product's number within that family
      category    block

  * the first four digits are the sub category's own `sub_code` (1111, 1112,
    1311 …), which every sub category already has;
  * the next four identify the Product Family within that sub category, in
    the order the families were first used — 1001, 1002, 1003 …;
  * the last four count the products in that family, from 0001.

The block for a family is discovered from the products already filed under
it, so the legacy numbering is preserved exactly. A family nobody has filed
a product under yet is given the next free block in its sub category.

Nothing here reads a counter table: the codes themselves are the record, and
deriving the next one from them cannot drift out of step with reality.
"""

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.inventory.models import (
    InventoryItem, InventorySubCategory, InventorySubDetailCategory,
)

CODE = re.compile(r"^\d{12}$")
FIRST_BLOCK = "1001"


def _prefix(db: Session, sub_category_id: uuid.UUID) -> str:
    """The sub category's four-digit code, which opens every product code
    filed under it."""
    sub = db.get(InventorySubCategory, sub_category_id)
    if sub is None or not (sub.sub_code or "").strip():
        raise ValueError(
            "This sub category has no code of its own, so a product code "
            "cannot be built from it. Give it one on Inventory Sub Category."
        )
    return sub.sub_code.strip()


def _block_for_family(
    db: Session, company_id: uuid.UUID, prefix: str, family_id: uuid.UUID | None
) -> str:
    """The four digits in the middle: which family block to file this under.

    Taken from the products already in that family — that is what the block
    means, and reading it back is what keeps a new product in the same run as
    its neighbours. A family with no products yet takes the next free block.
    """
    if family_id is not None:
        # One expression object, used in both the select list and the GROUP BY:
        # written out twice they carry different bind parameters, and Postgres
        # will not match them to each other.
        block = func.substr(InventoryItem.item_code, 5, 4)
        # A handful of legacy families have a stray product in a neighbouring
        # block, so the block holding most of them is the one to continue.
        used = db.scalar(
            select(block)
            .where(
                InventoryItem.company_id == company_id,
                InventoryItem.sub_detail_category_id == family_id,
                InventoryItem.item_code.op("~")(r"^\d{12}$"),
                func.substr(InventoryItem.item_code, 1, 4) == prefix,
            )
            .group_by(block)
            .order_by(func.count().desc(), block)
            .limit(1)
        )
        if used:
            return used

    # No family, or a family whose first product this is: take the block after
    # the highest one in use under this sub category.
    highest = db.scalar(
        select(func.max(func.substr(InventoryItem.item_code, 5, 4))).where(
            InventoryItem.company_id == company_id,
            InventoryItem.item_code.op("~")(r"^\d{12}$"),
            func.substr(InventoryItem.item_code, 1, 4) == prefix,
        )
    )
    if not highest:
        return FIRST_BLOCK
    return f"{int(highest) + 1:04d}"


def next_item_code(
    db: Session,
    company_id: uuid.UUID,
    sub_category_id: uuid.UUID | str,
    family_id: uuid.UUID | str | None = None,
) -> str:
    """The code the next product in this category would be given.

    Safe to call for a preview: it only reads. The create endpoint calls it
    again at the moment of insert and retries on a clash, so two people
    looking at the same preview still end up with different products.
    """
    sub_category_id = _as_uuid(sub_category_id)
    family_id = _as_uuid(family_id)

    prefix = _prefix(db, sub_category_id)
    block = _block_for_family(db, company_id, prefix, family_id)

    highest = db.scalar(
        select(func.max(func.substr(InventoryItem.item_code, 9, 4))).where(
            InventoryItem.company_id == company_id,
            InventoryItem.item_code.op("~")(r"^\d{12}$"),
            func.substr(InventoryItem.item_code, 1, 8) == f"{prefix}{block}",
        )
    )
    serial = int(highest) + 1 if highest else 1
    if serial > 9999:
        raise ValueError(
            f"Block {prefix}{block} is full — 9,999 products are already "
            "filed under it. Add a new Product Family to start a fresh block."
        )
    return f"{prefix}{block}{serial:04d}"


def family_of(db: Session, family_id: uuid.UUID | str | None) -> InventorySubDetailCategory | None:
    family_id = _as_uuid(family_id)
    return db.get(InventorySubDetailCategory, family_id) if family_id else None


def _as_uuid(value) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
