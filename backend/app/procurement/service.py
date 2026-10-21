"""
Procurement rules: availability, workflow, allocation, and posting.

The router validates shapes and this module decides what may happen. Three
things are worth reading before the rest:

`availability` answers "do we actually need to buy this?" — and separates
stock we hold, stock another warehouse holds, stock on order and stock in
transit, because each of those is a different answer to the requirement.

`allocate` spreads import costs over goods. The arithmetic is simple; the
care is in the rounding, which must leave the allocated amounts summing to
the charge exactly, or a landed cost quietly stops equalling its parts.

`post_receipt` is the only function in the module that moves stock. Purchase
orders, shipments and goods in transit deliberately do not.
"""

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from fastapi import HTTPException, status as http
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.common.calculations import LineInput, calculate_document, money
from app.common.currency import normalise as normalise_currency
from app.inventory import stock
from app.inventory.models import InventoryItem, ItemLocation
from app.partners.models import BusinessPartner
from app.procurement import models as m
from app.sales.models import SALES_ORDER, SalesDocument, SalesDocumentLine

ZERO = Decimal("0")
QTY = Decimal("0.0001")


def qty(value) -> Decimal:
    """Quantities carry four decimals, like the ledger."""
    if value is None:
        return ZERO
    return Decimal(str(value)).quantize(QTY, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------- workflow

#: Spec section 9. A requirement is only offered to procurement once
#: approved, and only closes when what was ordered has been received.
IHO_TRANSITIONS: dict[str, set[str]] = {
    "Draft": {"Submitted", "Cancelled"},
    "Submitted": {"Pending Approval", "Approved", "Rejected", "Draft"},
    "Pending Approval": {"Approved", "Rejected", "Draft"},
    "Approved": {"Pending Procurement", "Cancelled"},
    "Pending Procurement": {"Partially Ordered", "Fully Ordered", "Cancelled"},
    "Partially Ordered": {"Fully Ordered", "Partially Received", "Cancelled"},
    "Fully Ordered": {"Partially Received", "Fully Received", "Cancelled"},
    "Partially Received": {"Fully Received", "Closed"},
    "Fully Received": {"Closed"},
    "Rejected": {"Draft"},
    "Closed": set(),
    "Cancelled": set(),
}

#: Spec section 40.
PO_TRANSITIONS: dict[str, set[str]] = {
    "Draft": {"Pending Approval", "Approved", "Cancelled"},
    "Pending Approval": {"Approved", "Draft", "Cancelled"},
    # Sent to the supplier, then acknowledged by them (Import PO template);
    # receiving or shipping can start from any of these.
    "Approved": {"Sent", "Open", "Cancelled"},
    "Sent": {"Acknowledged", "Partially Received", "Fully Received", "Cancelled", "Closed"},
    "Acknowledged": {"Partially Received", "Fully Received", "Cancelled", "Closed"},
    "Open": {"Sent", "Partially Received", "Fully Received", "Cancelled", "Closed"},
    "Partially Received": {"Fully Received", "Closed", "Cancelled"},
    "Fully Received": {"Partially Invoiced", "Fully Invoiced", "Closed"},
    "Partially Invoiced": {"Fully Invoiced", "Closed"},
    "Fully Invoiced": {"Closed"},
    "Closed": set(),
    "Cancelled": set(),
}

#: Spec section 41. Where the paperwork has got to.
SHIPMENT_TRANSITIONS: dict[str, set[str]] = {
    "Draft": {"Booked", "Cancelled"},
    "Booked": {"Shipped", "Cancelled"},
    "Shipped": {"In Transit", "Arrived", "Cancelled"},
    "In Transit": {"Arrived", "Cancelled"},
    "Arrived": {"Customs Pending", "Customs Cleared"},
    "Customs Pending": {"Customs Cleared"},
    "Customs Cleared": {"Warehouse Pending", "Partially Received", "Fully Received"},
    "Warehouse Pending": {"Partially Received", "Fully Received"},
    "Partially Received": {"Fully Received", "Closed"},
    "Fully Received": {"Closed"},
    "Closed": set(),
    "Cancelled": set(),
}

#: Spec section 42. Only a posted landed cost affects valuation.
LANDED_COST_TRANSITIONS: dict[str, set[str]] = {
    "Draft": {"Cost Entry", "Cancelled"},
    "Cost Entry": {"Pending Approval", "Approved", "Draft", "Cancelled"},
    "Pending Approval": {"Approved", "Cost Entry", "Cancelled"},
    "Approved": {"Posted", "Cancelled"},
    "Posted": set(),
    "Cancelled": set(),
}

GRN_TRANSITIONS: dict[str, set[str]] = {
    "Draft": {"Posted", "Cancelled"},
    # Cancelling a posted receipt is the controlled reversal of section 47:
    # it writes opposite stock movements rather than deleting history, which
    # is why it is allowed here and editing is not.
    "Posted": {"Closed", "Cancelled"},
    "Closed": set(),
    "Cancelled": set(),
}

#: Where a requirement may be met from without buying anything.
_NON_PURCHASE_SOURCES = {"Existing Stock", "Internal Transfer", "Production"}

#: Shipment states in which the goods are in flight. Re-exported from the
#: models so callers have one name for it; these are `transit_status` values,
#: not document statuses, which is the distinction that matters here.
IN_TRANSIT_STATES = m.TRANSIT_IN_FLIGHT

#: Purchase orders that can still deliver something.
OPEN_PO_STATES = ("Approved", "Open", "Partially Received")


def check_transition(table: dict[str, set[str]], current: str, target: str, what: str) -> None:
    if current == target:
        return
    allowed = table.get(current)
    if allowed is None:
        raise HTTPException(http.HTTP_400_BAD_REQUEST,
                            f"{what} has an unrecognised status {current!r}.")
    if target not in allowed:
        raise HTTPException(
            http.HTTP_400_BAD_REQUEST,
            f"A {what} that is {current!r} cannot become {target!r}. "
            f"Allowed: {', '.join(sorted(allowed)) or 'nothing — it is final'}.",
        )


# ----------------------------------------------------------- availability

def _on_hand(db: Session, company_id: uuid.UUID, item_id: uuid.UUID,
             warehouse_id: uuid.UUID | None = None) -> Decimal:
    """Ledger balance, optionally for one warehouse. The ledger is the only
    source of a stock figure (see app.inventory.stock)."""
    e = stock.StockLedgerEntry
    stmt = select(func.coalesce(func.sum(
        case((e.direction == stock.IN, e.quantity), else_=-e.quantity)), 0)
    ).where(e.company_id == company_id, e.item_id == item_id)
    if warehouse_id is not None:
        stmt = stmt.where(e.location_id == warehouse_id)
    return qty(db.scalar(stmt) or 0)


def _reserved(db: Session, company_id: uuid.UUID, item_id: uuid.UUID) -> Decimal:
    """Committed to a customer but not yet shipped.

    A posted sales order has already taken its stock out of the ledger, so
    counting it again would double it. What is genuinely reserved is the
    unposted demand: orders written and agreed, whose goods are still on the
    shelf and must not be promised to anybody else.
    """
    return qty(db.scalar(
        select(func.coalesce(func.sum(
            SalesDocumentLine.quantity - SalesDocumentLine.delivered_quantity), 0))
        .join(SalesDocument, SalesDocument.id == SalesDocumentLine.document_id)
        .where(
            SalesDocument.company_id == company_id,
            SalesDocument.doc_type == SALES_ORDER,
            SalesDocument.status.in_(("Draft", "Pending Approval", "Approved")),
            SalesDocumentLine.item_id == item_id,
        )
    ) or 0)


def _on_order(db: Session, company_id: uuid.UUID, item_id: uuid.UUID) -> Decimal:
    """Ordered from a supplier and not yet on its way.

    Deliberately excludes what has shipped: those goods are counted by
    `_in_transit`, and adding both would promise the same carton twice.
    """
    line, order = m.PurchaseOrderLine, m.PurchaseOrder
    return qty(db.scalar(
        select(func.coalesce(func.sum(
            line.quantity - line.received_quantity - line.shipped_quantity), 0))
        .join(order, order.id == line.purchase_order_id)
        .where(order.company_id == company_id,
               order.status.in_(OPEN_PO_STATES),
               line.item_id == item_id)
    ) or 0)


def _in_transit(db: Session, company_id: uuid.UUID, item_id: uuid.UUID) -> Decimal:
    """Shipped by the supplier, not yet received into a warehouse.

    Real stock that the company owns and cannot pick from — which is why the
    ledger knows nothing about it (spec sections 20 and 50).
    """
    line, ship = m.ImportShipmentLine, m.ImportShipment
    return qty(db.scalar(
        select(func.coalesce(func.sum(line.shipped_quantity - line.received_quantity), 0))
        .join(ship, ship.id == line.shipment_id)
        .where(ship.company_id == company_id,
               ship.transit_status.in_(IN_TRANSIT_STATES),
               line.item_id == item_id)
    ) or 0)


def availability(db: Session, company_id: uuid.UUID, item_id: uuid.UUID,
                 warehouse_id: uuid.UUID | None = None) -> dict:
    """The stock picture behind a requirement (spec section 7).

    `shortfall` is the number that matters: what is still missing once
    everything already held, ordered or afloat has been counted. A
    requirement whose shortfall is zero does not need a purchase order, and
    saying so here is cheaper than finding out after one is raised.
    """
    item = db.get(InventoryItem, item_id) if item_id else None
    total = _on_hand(db, company_id, item_id)
    here = _on_hand(db, company_id, item_id, warehouse_id) if warehouse_id else total
    reserved = _reserved(db, company_id, item_id)
    on_order = _on_order(db, company_id, item_id)
    transit = _in_transit(db, company_id, item_id)

    return {
        "item_id": str(item_id),
        "item_code": item.item_code if item else None,
        "description": item.description if item else None,
        "uom": item.uom if item else None,
        "stock_on_hand": float(here),
        "reserved_stock": float(reserved),
        "available_stock": float(here - reserved),
        "stock_other_warehouses": float(total - here),
        "stock_on_order": float(on_order),
        "goods_in_transit": float(transit),
        "expected_stock": float(here - reserved + on_order + transit),
        "reorder_level": float(item.re_order_qty) if item and item.re_order_qty else None,
        "min_level": float(item.min_level) if item and item.min_level else None,
        "max_level": float(item.max_level) if item and item.max_level else None,
    }


def shortfall(picture: dict, required: Decimal) -> Decimal:
    """What still has to be procured, given a stock picture."""
    expected = Decimal(str(picture["expected_stock"]))
    return max(ZERO, qty(required) - expected)


def transfer_candidates(db: Session, company_id: uuid.UUID, item_id: uuid.UUID,
                        exclude_warehouse_id: uuid.UUID | None,
                        needed: Decimal) -> list[dict]:
    """Warehouses holding this item that could supply it instead (section 8).

    Offered before a purchase order because moving stock the company already
    owns is cheaper than buying more of it.
    """
    e = stock.StockLedgerEntry
    rows = db.execute(
        select(ItemLocation.id, ItemLocation.location, func.coalesce(func.sum(
            case((e.direction == stock.IN, e.quantity), else_=-e.quantity)), 0))
        .join(e, e.location_id == ItemLocation.id)
        .where(e.company_id == company_id, e.item_id == item_id)
        .group_by(ItemLocation.id, ItemLocation.location)
        .having(func.coalesce(func.sum(
            case((e.direction == stock.IN, e.quantity), else_=-e.quantity)), 0) > 0)
    ).all()

    return sorted(
        [
            {
                "warehouse_id": str(wid),
                "warehouse": name,
                "available": float(qty(balance)),
                "can_cover": qty(balance) >= qty(needed),
            }
            for wid, name, balance in rows
            if wid != exclude_warehouse_id
        ],
        key=lambda r: -r["available"],
    )


# ------------------------------------------------------------------- totals

def _line_inputs(lines: Iterable[dict]) -> list[LineInput]:
    return [
        LineInput(
            quantity=Decimal(str(line.get("quantity") or 0)),
            unit_price=Decimal(str(line.get("unit_price") or 0)),
            discount_percent=Decimal(str(line.get("discount_percent") or 0)),
            tax_percent=Decimal(str(line.get("tax_percent") or 0)),
        )
        for line in lines
    ]


def apply_po_lines(db: Session, order: m.PurchaseOrder, raw_lines: list[dict],
                   freight, document_discount, extra_charges=ZERO) -> None:
    """Replace an order's lines and recompute every figure on it.

    Totals sent by the client are ignored, as everywhere else in this ERP:
    the server recalculates from quantity, price, discount and tax, and its
    answer is what is stored.
    """
    if not raw_lines:
        raise HTTPException(http.HTTP_400_BAD_REQUEST, "Add at least one product line.")

    # Packing / handling, insurance and other agreed charges are added to the
    # total with the freight (Import PO template: Commercial Value Summary).
    totals = calculate_document(
        _line_inputs(raw_lines),
        freight_amount=Decimal(str(freight or 0)) + Decimal(str(extra_charges or 0)),
        document_discount=Decimal(str(document_discount or 0)),
    )

    # What has already happened to these lines must survive an edit, or a
    # receipted order would forget it had been received.
    previous = {line.id: line for line in order.lines}

    new_lines: list[m.PurchaseOrderLine] = []
    for index, (raw, computed) in enumerate(zip(raw_lines, totals.lines), start=1):
        item = None
        if raw.get("item_id"):
            item = db.get(InventoryItem, uuid.UUID(str(raw["item_id"])))
            if item is None:
                raise HTTPException(http.HTTP_400_BAD_REQUEST,
                                    f"Line {index}: that product no longer exists.")

        description = (raw.get("description") or (item.description if item else "")).strip()
        if not description:
            raise HTTPException(http.HTTP_400_BAD_REQUEST,
                                f"Line {index}: a description is required.")
        if Decimal(str(raw.get("quantity") or 0)) <= 0:
            raise HTTPException(http.HTTP_400_BAD_REQUEST,
                                f"Line {index}: quantity must be more than zero.")

        kept = previous.get(uuid.UUID(str(raw["id"]))) if raw.get("id") else None
        if kept is not None:
            received = kept.received_quantity
            shipped = kept.shipped_quantity
            if Decimal(str(raw["quantity"])) < received:
                raise HTTPException(
                    http.HTTP_400_BAD_REQUEST,
                    f"Line {index}: {received} has already been received, so the "
                    f"quantity cannot be cut to {raw['quantity']}.",
                )
        else:
            received = shipped = ZERO

        new_lines.append(m.PurchaseOrderLine(
            id=kept.id if kept else uuid.uuid4(),
            line_number=index,
            in_house_order_line_id=(
                uuid.UUID(str(raw["in_house_order_line_id"]))
                if raw.get("in_house_order_line_id") else None),
            item_id=item.id if item else None,
            item_code=raw.get("item_code") or (item.item_code if item else None),
            description=description,
            uom=raw.get("uom") or (item.uom if item else None),
            hs_code=raw.get("hs_code"),
            origin_country=raw.get("origin_country"),
            quantity=qty(raw.get("quantity")),
            free_quantity=qty(raw.get("free_quantity")),
            shipped_quantity=shipped,
            received_quantity=received,
            unit_price=Decimal(str(raw.get("unit_price") or 0)),
            discount_percent=Decimal(str(raw.get("discount_percent") or 0)),
            tax_percent=Decimal(str(raw.get("tax_percent") or 0)),
            gross_amount=computed.gross_amount,
            discount_amount=computed.discount_amount,
            taxable_amount=computed.taxable_amount,
            tax_amount=computed.tax_amount,
            net_amount=computed.net_amount,
            unit_weight=_maybe(raw.get("unit_weight")),
            unit_volume=_maybe(raw.get("unit_volume")),
            warehouse_id=_maybe_uuid(raw.get("warehouse_id")),
            required_date=raw.get("required_date"),
            remarks=raw.get("remarks"),
        ))

    order.lines = new_lines
    order.excluding_tax_value = totals.excluding_tax_value
    order.sales_tax_value = totals.sales_tax_value
    order.gross_amount = totals.gross_amount
    order.discount_amount = totals.discount_total
    order.freight_amount = money(Decimal(str(freight or 0)))
    order.net_payable = totals.net_receivable
    order.net_payable_base = money(totals.net_receivable * (order.exchange_rate or Decimal("1")))
    order.total_items = len(new_lines)


def _maybe(value) -> Decimal | None:
    return None if value in (None, "") else Decimal(str(value))


def _maybe_uuid(value) -> uuid.UUID | None:
    return None if value in (None, "") else uuid.UUID(str(value))


# --------------------------------------------------- requirement -> purchase

def outstanding_requirements(db: Session, order: m.InHouseOrder) -> list[dict]:
    """What is left to buy on an approved requirement (spec section 10).

    Lines already met in full, and lines being met by a transfer or from
    production, are reported with nothing outstanding — the purchase-order
    builder should not offer them.
    """
    rows = []
    for line in order.lines:
        approved = line.approved_quantity or line.requested_quantity
        buying = line.fulfilment_source not in _NON_PURCHASE_SOURCES
        remaining = max(ZERO, approved - line.ordered_quantity) if buying else ZERO
        rows.append({
            "line_id": str(line.id),
            "item_id": str(line.item_id) if line.item_id else None,
            "item_code": line.item_code,
            "description": line.description,
            "uom": line.uom,
            "requested_quantity": float(line.requested_quantity),
            "approved_quantity": float(approved),
            "ordered_quantity": float(line.ordered_quantity),
            "received_quantity": float(line.received_quantity),
            "outstanding_quantity": float(remaining),
            "fulfilment_source": line.fulfilment_source,
            "required_date": line.required_date,
        })
    return rows


def claim_requirement(db: Session, order: m.PurchaseOrder) -> None:
    """Add this order's quantities to the requirement lines it satisfies, and
    move the requirement's status on.

    Called after the order's lines are settled. Over-ordering a requirement
    is refused here rather than discovered later in a report.
    """
    if not order.in_house_order_id:
        return
    iho = db.get(m.InHouseOrder, order.in_house_order_id)
    if iho is None:
        return

    for line in order.lines:
        if not line.in_house_order_line_id:
            continue
        target = db.get(m.InHouseOrderLine, line.in_house_order_line_id)
        if target is None:
            continue
        approved = target.approved_quantity or target.requested_quantity
        if target.ordered_quantity + line.quantity > approved:
            raise HTTPException(
                http.HTTP_400_BAD_REQUEST,
                f"{target.description[:40]}: {approved} was approved and "
                f"{target.ordered_quantity} is already on order, so {line.quantity} "
                "more cannot be ordered.",
            )
        target.ordered_quantity = qty(target.ordered_quantity + line.quantity)

    refresh_requirement_status(db, iho)


def release_requirement(db: Session, order: m.PurchaseOrder) -> None:
    """Give back the quantities an order had claimed — on cancellation, or
    before its lines are replaced by an edit."""
    if not order.in_house_order_id:
        return
    for line in order.lines:
        if not line.in_house_order_line_id:
            continue
        target = db.get(m.InHouseOrderLine, line.in_house_order_line_id)
        if target is not None:
            target.ordered_quantity = max(ZERO, qty(target.ordered_quantity - line.quantity))
    iho = db.get(m.InHouseOrder, order.in_house_order_id)
    if iho is not None:
        refresh_requirement_status(db, iho)


def refresh_requirement_status(db: Session, iho: m.InHouseOrder) -> None:
    """Derive a requirement's status from its lines.

    The status is a summary of the quantities, never typed by hand, so it
    cannot disagree with them (spec section 39).
    """
    if iho.status in ("Draft", "Submitted", "Pending Approval",
                      "Rejected", "Cancelled", "Closed"):
        return

    buying = [l for l in iho.lines if l.fulfilment_source not in _NON_PURCHASE_SOURCES]
    if not buying:
        iho.status = "Fully Received"
        return

    def approved_of(line):
        return line.approved_quantity or line.requested_quantity

    ordered = all(l.ordered_quantity >= approved_of(l) for l in buying)
    any_ordered = any(l.ordered_quantity > 0 for l in buying)
    received = all(l.received_quantity >= approved_of(l) for l in buying)
    any_received = any(l.received_quantity > 0 for l in buying)

    if received:
        iho.status = "Fully Received"
    elif any_received:
        iho.status = "Partially Received"
    elif ordered:
        iho.status = "Fully Ordered"
    elif any_ordered:
        iho.status = "Partially Ordered"
    else:
        iho.status = "Pending Procurement"


def refresh_po_status(db: Session, order: m.PurchaseOrder) -> None:
    """Derive a purchase order's receipt status from its lines."""
    if order.status in ("Draft", "Pending Approval", "Cancelled", "Closed"):
        return
    if not order.lines:
        return
    full = all(l.received_quantity >= l.quantity for l in order.lines)
    some = any(l.received_quantity > 0 for l in order.lines)
    if full:
        order.status = "Fully Received"
        order.po_status = "Closed"
    elif some:
        order.status = "Partially Received"
    elif order.status == "Approved":
        order.status = "Open"


def refresh_shipment_status(db: Session, shipment: m.ImportShipment) -> None:
    if shipment.status in ("Draft", "Cancelled", "Closed"):
        return
    if not shipment.lines:
        return
    full = all(l.received_quantity >= l.shipped_quantity for l in shipment.lines)
    some = any(l.received_quantity > 0 for l in shipment.lines)
    if full:
        shipment.status = "Fully Received"
        shipment.transit_status = "Warehouse Received"
    elif some:
        shipment.status = "Partially Received"


# ----------------------------------------------------------- landed costing

#: Which column on a landed cost item each cost group rolls up into.
_GROUP_COLUMN = {
    "Freight": "freight_cost",
    "Insurance": "insurance_cost",
    "Customs": "customs_cost",
    "Tax": "tax_cost",
    "Port": "port_cost",
    "Clearing": "clearing_cost",
    "Bank": "bank_cost",
    "Other": "other_cost",
}


def _basis(item: m.LandedCostItem, method: str) -> Decimal:
    """One item's share of whatever the charge is spread by."""
    if method == "Quantity":
        return qty(item.quantity)
    if method == "Weight":
        return qty(item.total_weight or 0)
    if method == "Volume":
        return qty(item.total_volume or 0)
    if method in ("Percentage", "Manual"):
        return Decimal(str(item.manual_share_percent or 0))
    return Decimal(str(item.purchase_cost_base or 0))  # Value, the default


def allocate(charge_amount: Decimal, items: list[m.LandedCostItem],
             method: str) -> list[tuple[m.LandedCostItem, Decimal, Decimal, Decimal]]:
    """Spread one charge across the goods.

    Returns (item, amount, its basis, the total basis) per item, so the
    voucher can record not just the split but the reason for it.

    Two things this gets right that a naive loop does not. Rounding residue
    is given to the largest share rather than dropped, so the parts always
    sum back to the charge — otherwise a landed cost slowly stops equalling
    its components. And a basis that totals zero (no weights captured, say)
    falls back to an even split instead of dividing by zero, because a real
    cost still has to land somewhere.
    """
    amount = money(charge_amount)
    if not items or amount == 0:
        return [(item, Decimal("0.00"), ZERO, ZERO) for item in items]

    bases = [_basis(item, method) for item in items]
    total = sum(bases, ZERO)

    if total <= 0:
        # Nothing to weight by: split evenly and say so by reporting a basis
        # of one each, which is exactly what was used.
        bases = [Decimal("1")] * len(items)
        total = Decimal(str(len(items)))

    split: list[tuple[m.LandedCostItem, Decimal, Decimal, Decimal]] = []
    running = Decimal("0.00")
    for item, basis in zip(items, bases):
        share = money(amount * basis / total)
        split.append((item, share, basis, total))
        running += share

    residue = amount - running
    if residue != 0:
        # To the biggest share, where it is proportionally least visible.
        largest = max(range(len(split)), key=lambda i: split[i][1])
        item, share, basis, tot = split[largest]
        split[largest] = (item, money(share + residue), basis, tot)
    return split


def cost_landed(db: Session, voucher: m.LandedCost) -> None:
    """Work out the landed cost of every item on the voucher.

    Clears any previous allocation first, so re-costing after a charge is
    corrected produces a clean answer rather than adding to the old one.
    """
    items = list(voucher.items)
    if not items:
        raise HTTPException(http.HTTP_400_BAD_REQUEST,
                            "Add the goods this costing covers before costing it.")

    # Every allocation points at the charge that produced it, so the charges
    # must have ids before anything is allocated. A charge built in Python
    # has none until it reaches the database, so flush first rather than
    # relying on the caller having done it.
    db.flush()

    rate = voucher.exchange_rate or Decimal("1")
    for item in items:
        item.purchase_cost = money(item.quantity * item.unit_price)
        item.purchase_cost_base = money(item.purchase_cost * rate)
        for column in _GROUP_COLUMN.values():
            setattr(item, column, Decimal("0.00"))
        item.allocations = []

    for charge in voucher.charges:
        charge.currency = normalise_currency(charge.currency)
        charge.amount_base = money(
            Decimal(str(charge.amount or 0)) * (charge.exchange_rate or Decimal("1")))
        if not charge.is_inventoriable:
            # An expensed charge is recorded and reported, but it does not
            # become part of what the stock is worth.
            continue

        method = charge.allocation_method or voucher.allocation_method or "Value"
        column = _GROUP_COLUMN.get(charge.cost_group, "other_cost")

        for item, share, basis, total in allocate(charge.amount_base, items, method):
            setattr(item, column, money(getattr(item, column) + share))
            item.allocations.append(m.LandedCostAllocation(
                charge_id=charge.id,
                cost_group=charge.cost_group,
                allocation_method=method,
                basis_value=qty(basis),
                basis_total=qty(total),
                amount=share,
            ))

    for index, item in enumerate(items, start=1):
        item.line_number = index
        item.additional_cost = money(sum(
            (getattr(item, column) for column in _GROUP_COLUMN.values()), Decimal("0.00")))
        item.total_landed_cost = money(item.purchase_cost_base + item.additional_cost)
        item.unit_landed_cost = (
            (item.total_landed_cost / item.quantity).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP)
            if item.quantity > 0 else Decimal("0.0000")
        )

    voucher.purchase_cost_base = money(sum(
        (i.purchase_cost_base for i in items), Decimal("0.00")))
    voucher.additional_cost_base = money(sum(
        (i.additional_cost for i in items), Decimal("0.00")))
    voucher.total_landed_cost = money(sum(
        (i.total_landed_cost for i in items), Decimal("0.00")))
    voucher.total_quantity = qty(sum((i.quantity for i in items), ZERO))
    voucher.total_items = len(items)


def landed_unit_costs(db: Session, landed_cost_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    """Unit landed cost per product, for a receipt to take its costs from."""
    rows = db.execute(
        select(m.LandedCostItem.item_id, m.LandedCostItem.unit_landed_cost)
        .where(m.LandedCostItem.landed_cost_id == landed_cost_id,
               m.LandedCostItem.item_id.is_not(None))
    ).all()
    return {item_id: cost for item_id, cost in rows}


# ------------------------------------------------------------------ receipt

def resolve_warehouse(db: Session, company_id: uuid.UUID,
                      warehouse_id: uuid.UUID | None) -> uuid.UUID | None:
    if warehouse_id is None:
        return None
    location = db.get(ItemLocation, warehouse_id)
    if location is None or location.company_id != company_id:
        raise HTTPException(http.HTTP_400_BAD_REQUEST, "Choose a warehouse that exists.")
    return location.id


def check_receipt(db: Session, grn: m.MaterialReceivingNote) -> None:
    """Refuse a receipt that claims more than is owed.

    Checked against the order line (or the shipment line, for an import),
    which is the only place that knows what is still outstanding. Without
    this, a mistyped quantity becomes stock that was never bought.
    """
    for line in grn.lines:
        if line.received_quantity <= 0:
            raise HTTPException(
                http.HTTP_400_BAD_REQUEST,
                f"{line.description[:40]}: a receipt of zero is not a receipt. "
                "Remove the line instead.")
        if line.accepted_quantity > line.received_quantity:
            raise HTTPException(
                http.HTTP_400_BAD_REQUEST,
                f"{line.description[:40]}: {line.accepted_quantity} accepted is more than the "
                f"{line.received_quantity} received.")

        if line.shipment_line_id:
            source = db.get(m.ImportShipmentLine, line.shipment_line_id)
            ordered, already, what = (
                source.shipped_quantity, source.received_quantity, "shipped")
        elif line.purchase_order_line_id:
            source = db.get(m.PurchaseOrderLine, line.purchase_order_line_id)
            ordered, already, what = (source.quantity, source.received_quantity, "ordered")
        else:
            continue  # a free-standing receipt, with nothing to check against

        if source is None:
            raise HTTPException(http.HTTP_400_BAD_REQUEST,
                                f"{line.description[:40]}: its source line has gone.")
        # Excess may be received and recorded on the note, but only what is
        # owed can be accepted into stock (GRN template: Short / Excess).
        if already + line.accepted_quantity > ordered:
            raise HTTPException(
                http.HTTP_400_BAD_REQUEST,
                f"{line.description[:40]}: {ordered} was {what} and {already} is already "
                f"accepted, so accepting {line.accepted_quantity} more would over-receive it by "
                f"{qty(already + line.accepted_quantity - ordered)}. Record the excess as received "
                "with condition Excess, and accept only what is owed.",
            )


def post_receipt(db: Session, grn: m.MaterialReceivingNote, user_id: uuid.UUID | None) -> int:
    """Take the goods into stock. The only function here that moves stock.

    Posting does four things, and they belong together in one transaction:
    writes the ledger entries, rolls the received quantities up the chain
    (order line, shipment line, requirement line), refreshes the statuses
    that are derived from those quantities, and stamps the note as posted so
    it cannot happen twice.

    The cost each unit enters stock at is the landed unit cost when this is
    an import receipt with a posted costing, and the purchase price
    otherwise — which is why costing is done before the goods are taken in.
    """
    if grn.is_posted:
        raise HTTPException(http.HTTP_400_BAD_REQUEST,
                            f"{grn.doc_number} has already been posted.")

    check_receipt(db, grn)
    waiting = [l.description[:40] for l in grn.lines if (l.condition or "") == "Under Inspection"]
    if waiting:
        raise HTTPException(
            http.HTTP_400_BAD_REQUEST,
            "Still under inspection: " + "; ".join(waiting) + ". Only verified, accepted quantities "
            "go into stock — finish the inspection and set each line's condition first.")

    unit_costs: dict[uuid.UUID, Decimal] = {}
    if grn.landed_cost_id:
        voucher = db.get(m.LandedCost, grn.landed_cost_id)
        if voucher is None:
            raise HTTPException(http.HTTP_400_BAD_REQUEST, "That landed costing has gone.")
        if not voucher.is_posted:
            raise HTTPException(
                http.HTTP_400_BAD_REQUEST,
                f"Landed costing {voucher.doc_number} is {voucher.status!r}. Post it "
                "first, or the goods come into stock at the wrong cost.")
        unit_costs = landed_unit_costs(db, voucher.id)

    written = 0
    touched_orders: set[uuid.UUID] = set()
    touched_shipments: set[uuid.UUID] = set()
    touched_requirements: set[uuid.UUID] = set()

    for line in grn.lines:
        warehouse_id = line.warehouse_id or grn.warehouse_id

        unit_cost = None
        if line.item_id and line.item_id in unit_costs:
            unit_cost = unit_costs[line.item_id]
        elif line.unit_price:
            unit_cost = money(Decimal(str(line.unit_price)) * (grn.exchange_rate or Decimal("1")))
        line.unit_cost_base = Decimal(str(unit_cost or 0))

        if line.item_id and line.accepted_quantity > 0:
            stock.post_movement(
                db,
                company_id=grn.company_id,
                item_id=line.item_id,
                direction=stock.IN,
                quantity=line.accepted_quantity,
                source_type="goods_receipt",
                source_id=grn.id,
                source_number=grn.doc_number,
                entry_date=grn.doc_date,
                unit_cost=unit_cost,
                user_id=user_id,
                location_id=warehouse_id,
                remarks=f"Goods receipt {grn.doc_number}",
            )
            written += 1

        if line.purchase_order_line_id:
            po_line = db.get(m.PurchaseOrderLine, line.purchase_order_line_id)
            if po_line is not None:
                po_line.received_quantity = qty(
                    po_line.received_quantity + line.accepted_quantity)
                touched_orders.add(po_line.purchase_order_id)
                if po_line.in_house_order_line_id:
                    iho_line = db.get(m.InHouseOrderLine, po_line.in_house_order_line_id)
                    if iho_line is not None:
                        iho_line.received_quantity = qty(
                            iho_line.received_quantity + line.accepted_quantity)
                        touched_requirements.add(iho_line.in_house_order_id)

        if line.shipment_line_id:
            ship_line = db.get(m.ImportShipmentLine, line.shipment_line_id)
            if ship_line is not None:
                ship_line.received_quantity = qty(
                    ship_line.received_quantity + line.accepted_quantity)
                touched_shipments.add(ship_line.shipment_id)

    for order_id in touched_orders:
        order = db.get(m.PurchaseOrder, order_id)
        if order is not None:
            refresh_po_status(db, order)
    for shipment_id in touched_shipments:
        shipment = db.get(m.ImportShipment, shipment_id)
        if shipment is not None:
            refresh_shipment_status(db, shipment)
    for iho_id in touched_requirements:
        iho = db.get(m.InHouseOrder, iho_id)
        if iho is not None:
            refresh_requirement_status(db, iho)

    grn.is_posted = True
    grn.status = "Posted"
    grn.posted_at = date.today()
    grn.posted_by = user_id
    return written


def reverse_receipt(db: Session, grn: m.MaterialReceivingNote,
                    user_id: uuid.UUID | None) -> int:
    """Undo a posted receipt with opposite entries, not by deletion.

    Section 47: a posted transaction is not editable, and history is not
    rewritten. The goods leave stock again by a movement that says why, and
    the quantities come back off the chain.
    """
    if not grn.is_posted:
        raise HTTPException(http.HTTP_400_BAD_REQUEST,
                            f"{grn.doc_number} is not posted, so there is nothing to reverse.")

    written = 0
    for line in grn.lines:
        if line.item_id and line.accepted_quantity > 0:
            stock.post_movement(
                db,
                company_id=grn.company_id,
                item_id=line.item_id,
                direction=stock.OUT,
                quantity=line.accepted_quantity,
                source_type="goods_receipt_reversal",
                source_id=grn.id,
                source_number=grn.doc_number,
                entry_date=date.today(),
                unit_cost=line.unit_cost_base or None,
                user_id=user_id,
                location_id=line.warehouse_id or grn.warehouse_id,
                remarks=f"Reversal of goods receipt {grn.doc_number}",
            )
            written += 1

        if line.purchase_order_line_id:
            po_line = db.get(m.PurchaseOrderLine, line.purchase_order_line_id)
            if po_line is not None:
                po_line.received_quantity = max(
                    ZERO, qty(po_line.received_quantity - line.accepted_quantity))
                if po_line.in_house_order_line_id:
                    iho_line = db.get(m.InHouseOrderLine, po_line.in_house_order_line_id)
                    if iho_line is not None:
                        iho_line.received_quantity = max(
                            ZERO, qty(iho_line.received_quantity - line.accepted_quantity))
        if line.shipment_line_id:
            ship_line = db.get(m.ImportShipmentLine, line.shipment_line_id)
            if ship_line is not None:
                ship_line.received_quantity = max(
                    ZERO, qty(ship_line.received_quantity - line.accepted_quantity))

    grn.is_posted = False
    grn.status = "Cancelled"
    return written


# ------------------------------------------------------------- housekeeping

def require_supplier(db: Session, company_id: uuid.UUID, supplier_id: str) -> BusinessPartner:
    partner = db.get(BusinessPartner, uuid.UUID(str(supplier_id)))
    if partner is None or partner.company_id != company_id:
        raise HTTPException(http.HTTP_400_BAD_REQUEST, "Choose a supplier that exists.")
    if not partner.is_supplier:
        raise HTTPException(
            http.HTTP_400_BAD_REQUEST,
            f"'{partner.name}' is not marked as a supplier. Tick Supplier on the "
            "account first, so purchases cannot be raised on a customer by mistake.")
    return partner


def default_charge_types(company_id: uuid.UUID) -> list[m.LandedCostChargeType]:
    """The import costs a Pakistani importer normally meets (spec section 26).

    A starting point only: they are rows, so a company edits, retires or adds
    to them. Rates are left blank on purpose — section 48 requires that no
    duty or tax rate be hard-coded, and a wrong default is worse than none.
    """
    seed = [
        ("Ocean Freight", "Freight", "Weight"),
        ("Air Freight", "Freight", "Weight"),
        ("Inland Freight", "Freight", "Weight"),
        ("Marine Insurance", "Insurance", "Value"),
        ("Customs Duty", "Customs", "Value"),
        ("Regulatory Duty", "Customs", "Value"),
        ("Additional Customs Duty", "Customs", "Value"),
        ("Sales Tax", "Tax", "Value"),
        ("Additional Sales Tax", "Tax", "Value"),
        ("Federal Excise Duty", "Tax", "Value"),
        ("Withholding Tax", "Tax", "Value"),
        ("Port Charges", "Port", "Quantity"),
        ("Terminal Handling", "Port", "Quantity"),
        ("Container Charges", "Port", "Quantity"),
        ("Examination Charges", "Port", "Quantity"),
        ("Clearing Agent Charges", "Clearing", "Value"),
        ("Documentation Charges", "Clearing", "Value"),
        ("LC Charges", "Bank", "Value"),
        ("Bank Charges", "Bank", "Value"),
        ("SWIFT Charges", "Bank", "Value"),
        ("Remittance Charges", "Bank", "Value"),
        ("Demurrage", "Other", "Quantity"),
        ("Detention", "Other", "Quantity"),
        ("Other Import Costs", "Other", "Value"),
    ]
    return [
        m.LandedCostChargeType(
            company_id=company_id, name=name, cost_group=group,
            default_allocation=allocation, sort_order=index * 10,
            # Demurrage and detention are penalties for delay, not part of
            # what the goods are worth; most policies expense them.
            is_inventoriable=name not in ("Demurrage", "Detention"),
        )
        for index, (name, group, allocation) in enumerate(seed)
    ]
