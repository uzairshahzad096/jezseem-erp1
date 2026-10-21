"""
Writing to the audit trail.

Callers pass an `AuditContext` — who is acting, from where — and describe the
change. The record joins the caller's transaction, so an action and its audit
entry commit or roll back together: there is never a posted journal without
its "post" record, nor a record of a post that did not happen.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.auth.dependencies import get_current_user
from app.users.models import User


@dataclass
class AuditContext:
    user_id: uuid.UUID | None
    username: str | None
    ip_address: str | None = None
    user_agent: str | None = None

    @classmethod
    def for_user(cls, user: User | None) -> "AuditContext":
        return cls(user_id=user.id if user else None, username=user.username if user else None)


def request_context(request: Request, user: User = Depends(get_current_user)) -> AuditContext:
    """FastAPI dependency: the caller plus their IP and browser."""
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (
        request.client.host if request.client else None)
    return AuditContext(
        user_id=user.id, username=user.username, ip_address=ip,
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
    )


def _jsonable(value: Any) -> Any:
    """Values as JSON can hold them. Money stays exact as a string rather
    than turning into a float that could print a different figure."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def snapshot(obj: Any, fields: list[str] | None = None) -> dict:
    """The column values of an ORM row, for old/new values."""
    columns = fields or [c.key for c in obj.__table__.columns]
    return {name: _jsonable(getattr(obj, name, None)) for name in columns}


def record(
    db: Session,
    ctx: AuditContext | None,
    *,
    action: str,
    module: str,
    entity: str | None = None,
    entity_id: Any = None,
    company_id: uuid.UUID | None = None,
    old_values: dict | None = None,
    new_values: dict | None = None,
    reason: str | None = None,
) -> AuditLog:
    """Add one audit entry to the caller's transaction."""
    entry = AuditLog(
        company_id=company_id,
        user_id=ctx.user_id if ctx else None,
        username=ctx.username if ctx else None,
        ip_address=ctx.ip_address if ctx else None,
        user_agent=ctx.user_agent if ctx else None,
        action=action,
        module=module,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        old_values=_jsonable(old_values) if old_values is not None else None,
        new_values=_jsonable(new_values) if new_values is not None else None,
        reason=reason,
    )
    db.add(entry)
    return entry


def changed(old: dict, new: dict) -> tuple[dict, dict]:
    """Only the fields that differ, so an update's record says what changed."""
    keys = [k for k in new if old.get(k) != new.get(k)]
    return {k: old.get(k) for k in keys}, {k: new.get(k) for k in keys}
