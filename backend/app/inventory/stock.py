"""
Stock ledger.

Spec section 9: "Inventory movements must create a proper stock ledger."
Spec section 21 rule 11: "Inventory transactions must be atomic."

Current stock is never stored as a mutable number on the item. It is the sum
of ledger entries, so every change has a document behind it and the figure
can always be explained. `InventoryItem.opening_stock` holds only the balance
imported from the old ERP and is added as a single opening entry.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, Text, case, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.common.mixins import UUIDPKMixin
from app.core.database import Base

# Movement directions
IN = "in"
OUT = "out"


class StockLedgerEntry(UUIDPKMixin, Base):
    """One immutable movement. Corrections are new entries, never edits —
    spec section 9: never modify historical transactions without a trail."""

    __tablename__ = "stock_ledger_entries"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_items.id"), nullable=False, index=True
    )
    # Where the movement happened. Nullable: movements from before locations
    # were tracked, and documents naming a location that is not in the Item
    # Locations list, still post — they just count as unassigned.
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("item_locations.id"), index=True
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    # What caused the movement, so any balance can be traced to its document.
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    source_number: Mapped[str | None] = mapped_column(String(50))
    remarks: Mapped[str | None] = mapped_column(Text)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


def post_movement(
    db: Session,
    *,
    company_id: uuid.UUID,
    item_id: uuid.UUID,
    direction: str,
    quantity: Decimal,
    source_type: str,
    source_id: uuid.UUID | None = None,
    source_number: str | None = None,
    entry_date: date | None = None,
    unit_cost: Decimal | None = None,
    user_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    remarks: str | None = None,
) -> StockLedgerEntry:
    """Add a ledger entry. The caller commits, so a document and its stock
    movements succeed or fail together."""
    entry = StockLedgerEntry(
        company_id=company_id,
        item_id=item_id,
        entry_date=entry_date or date.today(),
        direction=direction,
        quantity=Decimal(str(abs(Decimal(str(quantity))))),
        unit_cost=unit_cost,
        source_type=source_type,
        source_id=source_id,
        source_number=source_number,
        location_id=location_id,
        remarks=remarks,
        created_by=user_id,
    )
    db.add(entry)
    return entry


def reverse_movements(db: Session, source_type: str, source_id: uuid.UUID) -> int:
    """Cancel a document's effect by writing opposite entries rather than
    deleting the originals, so history stays intact."""
    entries = db.scalars(
        select(StockLedgerEntry).where(
            StockLedgerEntry.source_type == source_type,
            StockLedgerEntry.source_id == source_id,
        )
    ).all()
    for e in entries:
        db.add(StockLedgerEntry(
            company_id=e.company_id, item_id=e.item_id, entry_date=date.today(),
            direction=OUT if e.direction == IN else IN, quantity=e.quantity,
            source_type=f"{source_type}_reversal", source_id=source_id,
            source_number=e.source_number, remarks="Reversal",
            # A reversal must return the stock to where it left from.
            location_id=e.location_id,
        ))
    return len(entries)


def stock_balance(db: Session, company_id: uuid.UUID, item_id: uuid.UUID) -> Decimal:
    """Current quantity for one item."""
    total_in = db.scalar(
        select(func.coalesce(func.sum(StockLedgerEntry.quantity), 0)).where(
            StockLedgerEntry.company_id == company_id,
            StockLedgerEntry.item_id == item_id,
            StockLedgerEntry.direction == IN,
        )
    ) or Decimal("0")
    total_out = db.scalar(
        select(func.coalesce(func.sum(StockLedgerEntry.quantity), 0)).where(
            StockLedgerEntry.company_id == company_id,
            StockLedgerEntry.item_id == item_id,
            StockLedgerEntry.direction == OUT,
        )
    ) or Decimal("0")
    return Decimal(str(total_in)) - Decimal(str(total_out))


def stock_balance_at(db: Session, company_id: uuid.UUID, item_id: uuid.UUID,
                     location_id: uuid.UUID | None) -> Decimal:
    """One item's quantity at one location."""
    total = db.scalar(
        select(func.coalesce(func.sum(
            case((StockLedgerEntry.direction == IN, StockLedgerEntry.quantity),
                 else_=-StockLedgerEntry.quantity)
        ), 0)).where(
            StockLedgerEntry.company_id == company_id,
            StockLedgerEntry.item_id == item_id,
            StockLedgerEntry.location_id.is_(None) if location_id is None
            else StockLedgerEntry.location_id == location_id,
        )
    )
    return Decimal(str(total or 0))


def stock_balances_by_location(
    db: Session, company_id: uuid.UUID, location_id: uuid.UUID | None = None
) -> dict[tuple[uuid.UUID, uuid.UUID | None], Decimal]:
    """Balances keyed by (item, location).

    Passing a location narrows it to that one, which is what the Product Stock
    report does when a location is chosen.
    """
    stmt = (
        select(
            StockLedgerEntry.item_id,
            StockLedgerEntry.location_id,
            func.sum(case((StockLedgerEntry.direction == IN, StockLedgerEntry.quantity),
                          else_=-StockLedgerEntry.quantity)),
        )
        .where(StockLedgerEntry.company_id == company_id)
        .group_by(StockLedgerEntry.item_id, StockLedgerEntry.location_id)
    )
    if location_id is not None:
        stmt = stmt.where(StockLedgerEntry.location_id == location_id)
    return {(item, loc): Decimal(str(qty or 0)) for item, loc, qty in db.execute(stmt).all()}


def stock_balances(db: Session, company_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    """Balances for every item in one query — used by the stock report and
    the product listing, which would otherwise issue a query per row."""
    rows = db.execute(
        select(
            StockLedgerEntry.item_id,
            func.sum(
                case(
                    (StockLedgerEntry.direction == IN, StockLedgerEntry.quantity),
                    else_=-StockLedgerEntry.quantity,
                )
            ),
        )
        .where(StockLedgerEntry.company_id == company_id)
        .group_by(StockLedgerEntry.item_id)
    ).all()
    return {item_id: Decimal(str(qty or 0)) for item_id, qty in rows}
