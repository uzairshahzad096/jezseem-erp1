"""
The audit trail.

One append-only table for every module. The database refuses UPDATE, DELETE
and TRUNCATE on it (migration 0008), so a record, once written, stays as it
was written, whoever connects.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.mixins import UUIDPKMixin
from app.core.database import Base


class AuditLog(UUIDPKMixin, Base):
    __tablename__ = "audit_logs"

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    #: Kept beside the id so the log still reads if a user is renamed.
    username: Mapped[str | None] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    #: create / update / delete / post / reverse / approve / reject / submit /
    #: cancel / import / export / close / reopen / lock / login / login_failed
    action: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    entity: Mapped[str | None] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    old_values: Mapped[dict | None] = mapped_column(JSONB)
    new_values: Mapped[dict | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(Text)
