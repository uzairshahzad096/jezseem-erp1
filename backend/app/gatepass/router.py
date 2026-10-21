"""Outward and Inward Gate Pass endpoints.

Both pass types share one set of handlers, built per type the same way the
sales module builds quotations and orders, so the two screens cannot drift
apart.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status as http
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import require_permission
from app.core.database import get_db
from app.gatepass import service
from app.gatepass.models import INWARD, OUTWARD, GatePass, GatePassLine
from app.gatepass.schemas import GatePassIn, GatePassStatusIn
from app.inventory import availability
from app.inventory.models import ItemLocation
from app.inventory.router import active_company_id
from app.partners.models import BusinessPartner
from app.users.models import User

router = APIRouter(prefix="/gate-passes", tags=["gate passes"])


def _item_text(db: Session, pass_ids: list[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    """The goods on each pass, joined for the listing's Total Items Desc
    column — one query for the page rather than one per row."""
    if not pass_ids:
        return {}
    rows = db.execute(
        select(GatePassLine.gate_pass_id, GatePassLine.description)
        .where(GatePassLine.gate_pass_id.in_(pass_ids))
        .order_by(GatePassLine.gate_pass_id, GatePassLine.line_number)
    ).all()
    grouped: dict[uuid.UUID, list[str]] = {}
    for pass_id, description in rows:
        if description:
            grouped.setdefault(pass_id, []).append(description)
    return {pass_id: " , ".join(v) for pass_id, v in grouped.items()}


def _summary(gp: GatePass, parties: dict, item_text: str | None = None,
             reference_number: str | None = None) -> dict:
    party = parties.get(gp.party_id)
    return {
        "id": str(gp.id),
        "doc_number": gp.doc_number,
        "doc_date": gp.doc_date,
        "pass_type": gp.pass_type,
        "party_id": str(gp.party_id) if gp.party_id else None,
        "party_name": party.name if party else None,
        "party_address": party.address if party else None,
        "vehicle_number": gp.vehicle_number,
        "driver": gp.driver,
        "issue_type": gp.issue_type,
        "issue_to": gp.issue_to,
        "location": gp.location,
        "dc_number": gp.dc_number,
        "challan_number": gp.challan_number,
        "container_number": gp.container_number,
        "po_number": gp.po_number,
        "reference_number": gp.reference_number,
        # Falls back to the party's registrations when the pass has none of
        # its own, which is what gets printed.
        "ntn": gp.ntn or (party.ntn if party else None),
        "gst_number": gp.gst_number or (party.stn if party else None),
        "status": gp.status,
        "is_approved": gp.is_approved,
        "currency": gp.currency,
        "excluding_tax_value": float(gp.excluding_tax_value),
        "sales_tax_value": float(gp.sales_tax_value),
        "gross_amount": float(gp.gross_amount),
        "discount_amount": float(gp.discount_amount),
        "freight_amount": float(gp.freight_amount),
        "total_amount": float(gp.total_amount),
        "payment_status": gp.payment_status,
        "payment_reference": gp.payment_reference,
        "total_items": gp.total_items,
        "item_description": item_text,
        "remarks": gp.remarks,
        "reference_gate_pass_id": (
            str(gp.reference_gate_pass_id) if gp.reference_gate_pass_id else None),
        "reference_gate_pass_number": reference_number,
        "total_quantity": float(sum((line.quantity for line in gp.lines), 0))
        if gp.lines else 0.0,
        "expected_return_date": gp.expected_return_date,
        "returnable": service.is_returnable(gp),
        "return_status": service.return_status(gp),
        "returned_quantity": float(sum((line.returned_quantity for line in gp.lines), 0))
        if gp.lines else 0.0,
        "pending_quantity": float(sum((service.pending(line) for line in gp.lines), 0))
        if gp.lines else 0.0,
    }


def _detail(db: Session, gp: GatePass) -> dict:
    party = db.get(BusinessPartner, gp.party_id) if gp.party_id else None
    reference = db.get(GatePass, gp.reference_gate_pass_id) if gp.reference_gate_pass_id else None
    data = _summary(
        gp,
        {gp.party_id: party} if party else {},
        " , ".join(line.description for line in gp.lines if line.description) or None,
        reference.doc_number if reference else None,
    )
    data["lines"] = [
        {
            "id": str(line.id),
            "line_number": line.line_number,
            "item_id": str(line.item_id) if line.item_id else None,
            "item_code": line.item_code,
            "description": line.description,
            "uom": line.uom,
            "hs_code": line.hs_code,
            "quantity": float(line.quantity),
            "returned_quantity": float(line.returned_quantity),
            "pending_quantity": float(service.pending(line)),
            "reference_line_id": str(line.reference_line_id) if line.reference_line_id else None,
            "unit_price": float(line.unit_price),
            "net_amount": float(line.net_amount),
            "remarks": line.remarks,
        }
        for line in gp.lines
    ]
    return data


def _list(pass_type: str, permission: str):
    def handler(
        search: str | None = None,
        status_filter: list[str] = Query(default=[], alias="status"),
        party_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        sort: str = "doc_date",
        direction: str = "desc",
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=5000),
        db: Session = Depends(get_db),
        user: User = Depends(require_permission(permission)),
    ):
        company_id = active_company_id(db)
        # Matched case-insensitively: data loaded straight into the table has
        # arrived as 'OUTWARD' before, and an exact match meant the rows were
        # present but invisible with no error to explain it.
        stmt = select(GatePass).where(
            GatePass.company_id == company_id,
            func.lower(GatePass.pass_type) == pass_type,
        )
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(
                GatePass.doc_number.ilike(like),
                GatePass.remarks.ilike(like),
                GatePass.vehicle_number.ilike(like),
                GatePass.dc_number.ilike(like),
                GatePass.reference_number.ilike(like),
                GatePass.lines.any(GatePassLine.description.ilike(like)),
            ))
        if status_filter:
            stmt = stmt.where(GatePass.status.in_(status_filter))
        if party_id:
            stmt = stmt.where(GatePass.party_id == party_id)
        if date_from:
            stmt = stmt.where(GatePass.doc_date >= date_from)
        if date_to:
            stmt = stmt.where(GatePass.doc_date <= date_to)

        sortable = {
            "doc_date": GatePass.doc_date, "doc_number": GatePass.doc_number,
            "status": GatePass.status, "total_items": GatePass.total_items,
        }
        column = sortable.get(sort, GatePass.doc_date)
        stmt = stmt.order_by(column.desc() if direction == "desc" else column.asc())

        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = list(db.scalars(
            stmt.options(selectinload(GatePass.lines))
            .offset((page - 1) * page_size).limit(page_size)
        ).all())

        parties = {p.id: p for p in db.scalars(
            select(BusinessPartner).where(
                BusinessPartner.id.in_([r.party_id for r in rows if r.party_id])
            )).all()} if rows else {}
        texts = _item_text(db, [r.id for r in rows])
        reference_ids = [r.reference_gate_pass_id for r in rows if r.reference_gate_pass_id]
        references = dict(db.execute(
            select(GatePass.id, GatePass.doc_number).where(GatePass.id.in_(reference_ids))
        ).all()) if reference_ids else {}

        return {
            "items": [
                _summary(r, parties, texts.get(r.id),
                         references.get(r.reference_gate_pass_id))
                for r in rows
            ],
            "total": total, "page": page, "page_size": page_size,
        }

    return handler


def _owned(db: Session, pass_id: uuid.UUID, pass_type: str) -> GatePass:
    gp = db.scalar(
        select(GatePass)
        .options(selectinload(GatePass.lines))
        .where(
            GatePass.id == pass_id,
            func.lower(GatePass.pass_type) == pass_type,
            GatePass.company_id == active_company_id(db),
        )
    )
    if gp is None:
        raise HTTPException(404, "Gate pass not found.")
    return gp


def _get_one(pass_type: str, permission: str):
    def handler(
        pass_id: uuid.UUID,
        db: Session = Depends(get_db),
        user: User = Depends(require_permission(permission)),
    ):
        return _detail(db, _owned(db, pass_id, pass_type))

    return handler


def _create(pass_type: str, permission: str):
    def handler(
        payload: GatePassIn,
        db: Session = Depends(get_db),
        user: User = Depends(require_permission(permission)),
    ):
        company_id = active_company_id(db)

        reference = None
        if pass_type == INWARD and payload.reference_gate_pass_id:
            reference = service.require_reference(
                db, company_id, payload.reference_gate_pass_id)

        if pass_type == OUTWARD:
            availability.check(db, company_id, availability.quantities([l.model_dump() for l in payload.lines]))

        gp = GatePass(
            company_id=company_id,
            pass_type=pass_type,
            doc_number=service.allocate_number(db, company_id, pass_type, payload.doc_date),
            doc_date=payload.doc_date,
            party_id=uuid.UUID(payload.party_id) if payload.party_id else None,
            reference_gate_pass_id=reference.id if reference else None,
            vehicle_number=payload.vehicle_number,
            driver=payload.driver,
            issue_type=payload.issue_type,
            issue_to=payload.issue_to,
            location=payload.location,
            challan_number=payload.challan_number,
            dc_number=payload.dc_number,
            container_number=payload.container_number,
            po_number=payload.po_number,
            reference_number=payload.reference_number,
            ntn=payload.ntn,
            gst_number=payload.gst_number,
            currency=payload.currency,
            payment_status=payload.payment_status,
            payment_reference=payload.payment_reference,
            remarks=payload.remarks,
            expected_return_date=payload.expected_return_date,
            # Saved as a draft; "Approved" below sends it through the gate in
            # the same step, so stock always moves when a pass is approved.
            status="Draft",
            created_by=user.id,
        )
        service.apply_lines(db, gp, [l.model_dump() for l in payload.lines])
        service.check_return_lines(db, gp, reference)
        db.add(gp)
        db.flush()
        if payload.status == "Approved":
            service.approve(db, gp, user.id)
        db.commit()
        db.refresh(gp)
        return _detail(db, gp)

    return handler


def _update(pass_type: str, permission: str):
    def handler(
        pass_id: uuid.UUID,
        payload: GatePassIn,
        db: Session = Depends(get_db),
        user: User = Depends(require_permission(permission)),
    ):
        gp = _owned(db, pass_id, pass_type)
        if gp.status in ("Closed", "Cancelled"):
            raise HTTPException(
                400, f"This pass is '{gp.status}' and can no longer be edited.")
        if gp.status in service.POSTED_STATUSES:
            raise HTTPException(
                400,
                "An approved gate pass has already moved stock. Cancel it and raise a "
                "new one rather than editing what went through the gate.",
            )

        if pass_type == OUTWARD:
            availability.check(db, gp.company_id, availability.quantities([l.model_dump() for l in payload.lines]),
                               availability.quantities(gp.lines))

        for field in ("vehicle_number", "driver", "issue_type", "issue_to", "location",
                      "challan_number", "dc_number", "container_number", "po_number",
                      "reference_number", "ntn", "gst_number", "currency",
                      "payment_status", "payment_reference", "remarks"):
            setattr(gp, field, getattr(payload, field))
        gp.doc_date = payload.doc_date
        gp.party_id = uuid.UUID(payload.party_id) if payload.party_id else None
        gp.expected_return_date = payload.expected_return_date
        reference = None
        if pass_type == INWARD and payload.reference_gate_pass_id:
            reference = service.require_reference(db, gp.company_id, payload.reference_gate_pass_id)
        gp.reference_gate_pass_id = reference.id if reference else None
        gp.updated_by = user.id

        service.apply_lines(db, gp, [l.model_dump() for l in payload.lines])
        service.check_return_lines(db, gp, reference)
        db.flush()
        if payload.status == "Approved":
            service.approve(db, gp, user.id)
        db.commit()
        db.refresh(gp)
        return _detail(db, gp)

    return handler


def _set_status(pass_type: str, permission: str):
    def handler(
        pass_id: uuid.UUID,
        payload: GatePassStatusIn,
        db: Session = Depends(get_db),
        user: User = Depends(require_permission(permission)),
    ):
        gp = _owned(db, pass_id, pass_type)
        service.check_transition(gp.status, payload.status)

        # Approving is what sends the goods through the gate, so that is when
        # the stock moves — in the same transaction as the status change.
        if payload.status == "Approved" and gp.status not in service.POSTED_STATUSES:
            service.approve(db, gp, user.id)
        # Cancelling an approved pass puts the goods back where they were.
        elif payload.status == "Cancelled" and gp.status in service.POSTED_STATUSES:
            service.cancel(db, gp)
        else:
            gp.status = payload.status
        gp.updated_by = user.id
        db.commit()
        return {"id": str(gp.id), "status": gp.status, "is_approved": gp.is_approved}

    return handler


def _delete(pass_type: str, permission: str):
    def handler(
        pass_id: uuid.UUID,
        db: Session = Depends(get_db),
        user: User = Depends(require_permission(permission)),
    ):
        gp = _owned(db, pass_id, pass_type)
        if gp.status in service.POSTED_STATUSES:
            raise HTTPException(
                400,
                "This pass has moved stock. Cancel it instead, which reverses the "
                "movement and keeps the record of what went out.",
            )
        settled_by = db.scalar(
            select(GatePass).where(GatePass.reference_gate_pass_id == gp.id))
        if settled_by:
            raise HTTPException(
                http.HTTP_409_CONFLICT,
                f"Inward pass {settled_by.doc_number} references this one. "
                "Delete that first if it really should go.",
            )
        db.delete(gp)
        db.commit()

    return handler


@router.get("/outward/open")
def open_outward_passes(
    search: str | None = None,
    party_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.gate_passes.view")),
):
    """Approved outward passes an inward pass can be raised against.

    Only approved ones: a draft has not gone through the gate, so nothing has
    left to come back.
    """
    company_id = active_company_id(db)
    stmt = select(GatePass).where(
        GatePass.company_id == company_id,
        func.lower(GatePass.pass_type) == OUTWARD,
        GatePass.status == "Approved",
    )
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(
            GatePass.doc_number.ilike(like), GatePass.remarks.ilike(like)))
    if party_id:
        stmt = stmt.where(GatePass.party_id == party_id)

    # Only passes with something still out: a fully returned one has nothing
    # left to come back against.
    rows = [r for r in db.scalars(
        stmt.options(selectinload(GatePass.lines))
        .order_by(GatePass.doc_date.desc()).limit(200)).all()
        if any(service.pending(line) > 0 for line in r.lines)][:100]
    parties = {p.id: p for p in db.scalars(
        select(BusinessPartner).where(
            BusinessPartner.id.in_([r.party_id for r in rows if r.party_id])
        )).all()} if rows else {}
    texts = _item_text(db, [r.id for r in rows])
    return {"items": [_summary(r, parties, texts.get(r.id)) for r in rows]}


@router.get("/outward/{pass_id}/returnable")
def outward_returnable(
    pass_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.gate_passes.view")),
):
    """An outward pass as an inward return starts from it: its party and
    references, and each item with how many went out, came back and are still out."""
    gp = _owned(db, pass_id, OUTWARD)
    if gp.status not in service.POSTED_STATUSES:
        raise HTTPException(400, f"Outward pass {gp.doc_number} has not been approved, so nothing has gone out.")
    return _detail(db, gp)


@router.get("/locations")
def gate_pass_locations(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("inventory.gate_passes.view")),
):
    """Item Locations, for the Location picker on the pass form."""
    rows = db.scalars(
        select(ItemLocation)
        .where(ItemLocation.company_id == active_company_id(db))
        .order_by(ItemLocation.location)
    ).all()
    return {"items": [{"id": str(r.id), "location": r.location} for r in rows]}


# ---------------- Outward ----------------
router.add_api_route("/outward", _list(OUTWARD, "inventory.gate_passes.view"), methods=["GET"])
router.add_api_route("/outward/{pass_id}", _get_one(OUTWARD, "inventory.gate_passes.view"),
                     methods=["GET"])
router.add_api_route("/outward", _create(OUTWARD, "inventory.gate_passes.create"),
                     methods=["POST"], status_code=http.HTTP_201_CREATED)
router.add_api_route("/outward/{pass_id}", _update(OUTWARD, "inventory.gate_passes.edit"),
                     methods=["PUT"])
router.add_api_route("/outward/{pass_id}/status",
                     _set_status(OUTWARD, "inventory.gate_passes.approve"), methods=["POST"])
router.add_api_route("/outward/{pass_id}", _delete(OUTWARD, "inventory.gate_passes.delete"),
                     methods=["DELETE"], status_code=http.HTTP_204_NO_CONTENT)

# ---------------- Inward ----------------
router.add_api_route("/inward", _list(INWARD, "inventory.gate_passes.view"), methods=["GET"])
router.add_api_route("/inward/{pass_id}", _get_one(INWARD, "inventory.gate_passes.view"),
                     methods=["GET"])
router.add_api_route("/inward", _create(INWARD, "inventory.gate_passes.create"),
                     methods=["POST"], status_code=http.HTTP_201_CREATED)
router.add_api_route("/inward/{pass_id}", _update(INWARD, "inventory.gate_passes.edit"),
                     methods=["PUT"])
router.add_api_route("/inward/{pass_id}/status",
                     _set_status(INWARD, "inventory.gate_passes.approve"), methods=["POST"])
router.add_api_route("/inward/{pass_id}", _delete(INWARD, "inventory.gate_passes.delete"),
                     methods=["DELETE"], status_code=http.HTTP_204_NO_CONTENT)
