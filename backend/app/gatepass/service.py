"""
Gate pass rules.

A gate pass is the note that travels with goods through the gate. An outward
pass records stock physically leaving — a delivery, a machine going out for
repair, something sent free of charge — and an inward pass records goods
arriving or coming back against an earlier outward pass.

That makes it a stock document, not paperwork: approving an outward pass takes
the goods off the location they left from, and approving an inward pass puts
them back. This is why it exists alongside the sales order, which prices and
invoices the same movement — plenty of gate passes carry no sale at all.
"""

import uuid
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status as http
from sqlalchemy import BigInteger, func, select
from sqlalchemy.orm import Session

from app.common.calculations import LineInput, calculate_document
from app.common.numbering import next_dated_number
from app.gatepass.models import INWARD, OUTWARD, GatePass, GatePassLine
from app.inventory import stock
from app.inventory.models import InventoryItem, ItemLocation

# Only these moves are allowed. "Approved" is the point at which stock moves,
# so it is deliberately one-way from Draft.
TRANSITIONS = {
    "Draft": {"Approved", "Cancelled"},
    "Approved": {"Closed", "Cancelled"},
    "Closed": set(),
    "Cancelled": set(),
}

# Statuses at which the pass has moved stock.
POSTED_STATUSES = {"Approved", "Closed"}


def check_transition(current: str, target: str) -> None:
    if current == target:
        return
    allowed = TRANSITIONS.get(current, set())
    if target not in allowed:
        allowed_text = ", ".join(sorted(allowed)) or "nothing — this pass is final"
        raise HTTPException(
            http.HTTP_400_BAD_REQUEST,
            f"A gate pass with status '{current}' cannot move to '{target}'. "
            f"Allowed: {allowed_text}.",
        )


def highest_on_date(db: Session, company_id: uuid.UUID, pass_type: str, on_date: date) -> int:
    """The largest counter already used for that day, so a new pass continues
    rather than colliding."""
    scope = on_date.strftime("%Y%m%d")
    highest = db.scalar(
        select(func.max(
            func.cast(func.substr(GatePass.doc_number, len(scope) + 1), BigInteger)
        )).where(
            GatePass.company_id == company_id,
            GatePass.pass_type == pass_type,
            GatePass.doc_number.op("~")(f"^{scope}[0-9]+$"),
        )
    )
    return int(highest or 0)


def allocate_number(db: Session, company_id: uuid.UUID, pass_type: str, on_date: date) -> str:
    """GP numbers follow the same dated scheme as sales orders — 202604141 is
    the first pass of 14 April 2026."""
    return next_dated_number(
        db, company_id, f"gate_pass_{pass_type}", on_date,
        continue_from=highest_on_date(db, company_id, pass_type, on_date),
    )


def resolve_location(db: Session, company_id: uuid.UUID, name: str | None) -> uuid.UUID | None:
    """The Item Location matching the pass's location text, if any."""
    if not name or not name.strip():
        return None
    return db.scalar(
        select(ItemLocation.id).where(
            ItemLocation.company_id == company_id,
            func.lower(func.trim(ItemLocation.location)) == name.strip().lower(),
        )
    )


def apply_lines(db: Session, gate_pass: GatePass, lines: list[dict]) -> None:
    """Replace the pass's lines and recompute its totals.

    A gate pass often carries no prices at all — goods out on loan, a warranty
    replacement — so zero money is normal and not an error. The item count and
    any values that are present are still computed here rather than trusted.
    """
    if not lines:
        raise HTTPException(http.HTTP_400_BAD_REQUEST, "Add at least one item.")

    totals = calculate_document([
        LineInput(
            quantity=Decimal(str(line.get("quantity") or 0)),
            unit_price=Decimal(str(line.get("unit_price") or 0)),
        )
        for line in lines
    ])

    rebuilt: list[GatePassLine] = []
    for index, (raw, computed) in enumerate(zip(lines, totals.lines), start=1):
        item = None
        if raw.get("item_id"):
            item = db.get(InventoryItem, uuid.UUID(raw["item_id"]))
            if item is None:
                raise HTTPException(
                    http.HTTP_400_BAD_REQUEST,
                    f"Line {index}: the selected product no longer exists.")

        description = (raw.get("description") or (item.description if item else "")).strip()
        if not description:
            raise HTTPException(http.HTTP_400_BAD_REQUEST,
                                f"Line {index}: description is required.")

        rebuilt.append(GatePassLine(
            line_number=index,
            item_id=item.id if item else None,
            item_code=raw.get("item_code") or (item.item_code if item else None),
            description=description,
            uom=raw.get("uom") or (item.uom if item else None),
            hs_code=raw.get("hs_code"),
            remarks=raw.get("remarks"),
            reference_line_id=uuid.UUID(str(raw["reference_line_id"])) if raw.get("reference_line_id") else None,
            quantity=Decimal(str(raw.get("quantity") or 0)),
            unit_price=Decimal(str(raw.get("unit_price") or 0)),
            gross_amount=computed.gross_amount,
            discount_amount=computed.discount_amount,
            taxable_amount=computed.taxable_amount,
            tax_amount=computed.tax_amount,
            net_amount=computed.net_amount,
        ))

    gate_pass.lines = rebuilt
    gate_pass.excluding_tax_value = totals.excluding_tax_value
    gate_pass.sales_tax_value = totals.sales_tax_value
    gate_pass.gross_amount = totals.gross_amount
    gate_pass.discount_amount = totals.discount_total
    gate_pass.total_amount = totals.net_receivable
    gate_pass.total_items = len(rebuilt)


def post_stock(db: Session, gate_pass: GatePass, user_id: uuid.UUID) -> int:
    """Move the stock this pass represents.

    Outward takes goods off the location they left from; inward puts them
    back. Written in the caller's transaction so the movement and the status
    change commit together.
    """
    location_id = resolve_location(db, gate_pass.company_id, gate_pass.location)
    direction = stock.OUT if gate_pass.pass_type == OUTWARD else stock.IN

    written = 0
    for line in gate_pass.lines:
        if line.item_id is None:
            continue
        stock.post_movement(
            db,
            company_id=gate_pass.company_id,
            item_id=line.item_id,
            direction=direction,
            quantity=line.quantity,
            source_type=f"gate_pass_{gate_pass.pass_type}",
            source_id=gate_pass.id,
            source_number=gate_pass.doc_number,
            entry_date=gate_pass.doc_date,
            unit_cost=line.unit_price,
            user_id=user_id,
            location_id=location_id,
        )
        written += 1
    return written


def require_reference(db: Session, company_id: uuid.UUID, reference_id: str) -> GatePass:
    """The outward pass an inward pass settles."""
    outward = db.get(GatePass, uuid.UUID(str(reference_id)))
    if outward is None or outward.company_id != company_id:
        raise HTTPException(http.HTTP_404_NOT_FOUND, "That outward gate pass no longer exists.")
    if outward.pass_type != OUTWARD:
        raise HTTPException(
            http.HTTP_400_BAD_REQUEST,
            "An inward pass can only reference an outward gate pass.")
    return outward


# ---------------------------------------------------------------- returns
#
# A returnable outward pass (goods out on loan, for repair, for a demo) is
# settled by inward passes raised against it. Each inward line points at the
# outward line it returns, the outward line keeps the running total returned,
# and the outward pass closes itself once everything is back.

RETURNABLE_TYPES = {"returnable", "repair"}
ZERO = Decimal("0")


def is_returnable(gate_pass: GatePass) -> bool:
    return (gate_pass.issue_type or "").strip().lower() in RETURNABLE_TYPES


def pending(line: GatePassLine) -> Decimal:
    return max(Decimal(line.quantity or 0) - Decimal(line.returned_quantity or 0), ZERO)


def return_status(gate_pass: GatePass) -> str | None:
    """For an outward pass: how much of it has come back."""
    if gate_pass.pass_type.lower() != OUTWARD:
        return None
    sent = sum((Decimal(l.quantity or 0) for l in gate_pass.lines), ZERO)
    back = sum((Decimal(l.returned_quantity or 0) for l in gate_pass.lines), ZERO)
    if back <= 0:
        return "Pending return" if is_returnable(gate_pass) else None
    return "Fully returned" if back >= sent else "Partly returned"


def check_return_lines(db: Session, inward: GatePass, outward: GatePass | None) -> None:
    """Every line of an inward pass that names an outward line must belong to
    the referenced outward pass and may not bring back more than is still out."""
    if outward is None:
        if any(l.reference_line_id for l in inward.lines):
            raise HTTPException(http.HTTP_400_BAD_REQUEST,
                                "Choose the outward gate pass these goods are returning against.")
        return
    own = {l.id: l for l in outward.lines}
    asked: dict[uuid.UUID, Decimal] = {}
    for line in inward.lines:
        if line.reference_line_id is None:
            continue
        if line.reference_line_id not in own:
            raise HTTPException(http.HTTP_400_BAD_REQUEST,
                                f"'{line.description}' is not on outward pass {outward.doc_number}.")
        asked[line.reference_line_id] = asked.get(line.reference_line_id, ZERO) + Decimal(line.quantity)
    over = [f"{own[i].description}: {_n(q)} returning, {_n(pending(own[i]))} still out"
            for i, q in asked.items() if q > pending(own[i])]
    if over:
        raise HTTPException(http.HTTP_400_BAD_REQUEST,
                            f"More is coming back than went out on {outward.doc_number}. " + "; ".join(over) + ".")


def approve(db: Session, gate_pass: GatePass, user_id: uuid.UUID) -> None:
    """Send the pass through the gate: move the stock, and for an inward
    return count it against the outward pass."""
    from app.inventory import availability
    if gate_pass.pass_type.lower() == OUTWARD:
        availability.check(db, gate_pass.company_id, availability.quantities(gate_pass.lines), recheck_all=True)
        if not gate_pass.party_id:
            raise HTTPException(http.HTTP_400_BAD_REQUEST, "Choose the party the goods are going to.")
    outward = db.get(GatePass, gate_pass.reference_gate_pass_id) if gate_pass.reference_gate_pass_id else None
    if outward is not None:
        check_return_lines(db, gate_pass, outward)
    post_stock(db, gate_pass, user_id)
    gate_pass.is_approved = True
    gate_pass.status = "Approved"
    if outward is not None:
        _apply_returns(db, gate_pass, outward, sign=1)


def cancel(db: Session, gate_pass: GatePass) -> None:
    """Undo an approved pass: put the stock back and, for an inward return,
    take it off the outward pass again."""
    if gate_pass.pass_type.lower() == OUTWARD:
        returns = db.scalar(select(GatePass).where(
            GatePass.reference_gate_pass_id == gate_pass.id, GatePass.status.in_(list(POSTED_STATUSES))))
        if returns is not None:
            raise HTTPException(http.HTTP_400_BAD_REQUEST,
                                f"Goods have come back against this pass on inward pass {returns.doc_number}. "
                                "Cancel that first.")
    stock.reverse_movements(db, f"gate_pass_{gate_pass.pass_type.lower()}", gate_pass.id)
    gate_pass.is_approved = False
    outward = db.get(GatePass, gate_pass.reference_gate_pass_id) if gate_pass.reference_gate_pass_id else None
    if outward is not None and gate_pass.status in POSTED_STATUSES:
        _apply_returns(db, gate_pass, outward, sign=-1)
    gate_pass.status = "Cancelled"


def _apply_returns(db: Session, inward: GatePass, outward: GatePass, sign: int) -> None:
    own = {l.id: l for l in outward.lines}
    for line in inward.lines:
        target = own.get(line.reference_line_id)
        if target is not None:
            target.returned_quantity = max(Decimal(target.returned_quantity or 0) + sign * Decimal(line.quantity), ZERO)
    everything_back = all(pending(l) == 0 for l in outward.lines)
    if everything_back and outward.status == "Approved":
        outward.status = "Closed"
    elif not everything_back and outward.status == "Closed":
        outward.status = "Approved"      # a return was cancelled: the pass is open again


def _n(value: Decimal) -> str:
    text = f"{Decimal(value):f}"
    return text.rstrip("0").rstrip(".") if "." in text else text