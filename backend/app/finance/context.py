"""
Who is acting, for which company, and which branches they may see.

Every finance endpoint takes a `FinanceContext`. It combines the existing
permission check (`require_permission`), the working company, the caller's
branch access and the audit details, so no endpoint can forget one of them.

The company defaults to the ERP's working company (`active_company_id`, the
same rule every other module uses). An `X-Company-Id` header can choose
another. A non-superuser must hold that company in `user_company_access`.
An `X-Branch-Id` header narrows the context to one branch. Without it, a
user who holds any `user_branch_access` rows for the company is limited to
those branches; a user with none works at company level.
"""

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import AuditContext
from app.auth.dependencies import require_permission
from app.companies.models import Branch, Company
from app.core.config import settings
from app.core.database import get_db
from app.finance.errors import FinanceError
from app.inventory.router import active_company_id
from app.users.models import User, user_branch_access, user_company_access


@dataclass
class FinanceContext:
    company_id: uuid.UUID
    user: User
    audit: AuditContext
    #: The branch chosen for this request, if any.
    branch_id: uuid.UUID | None = None
    #: Branches the caller may see; None means every branch of the company.
    branch_ids: frozenset[uuid.UUID] | None = None

    @property
    def user_id(self) -> uuid.UUID:
        return self.user.id

    def branch_condition(self, column):
        """A WHERE clause limiting `column` to the visible branches, or None."""
        if self.branch_ids is None:
            return None
        return column.in_(self.branch_ids)

    def check_branch(self, branch_id: uuid.UUID | None) -> None:
        """Refuse to write to a branch the caller cannot see."""
        if self.branch_ids is None:
            return
        if branch_id is None or branch_id not in self.branch_ids:
            raise FinanceError("You do not have access to that branch.", 403)

    def default_branch(self, branch_id: uuid.UUID | None) -> uuid.UUID | None:
        """The branch a new record belongs to: as given, else the context's."""
        chosen = branch_id or self.branch_id
        if chosen is None and self.branch_ids is not None and len(self.branch_ids) == 1:
            chosen = next(iter(self.branch_ids))
        self.check_branch(chosen)
        return chosen


def _unrestricted(user: User) -> bool:
    return settings.AUTH_DISABLED or user.is_superuser


def build_context(
    db: Session,
    user: User,
    company_id: uuid.UUID | None,
    branch_id: uuid.UUID | None,
    audit: AuditContext,
) -> FinanceContext:
    company_id = company_id or active_company_id(db)
    if db.get(Company, company_id) is None:
        raise FinanceError("That company does not exist.", 404)

    if not _unrestricted(user):
        has_company = db.execute(
            select(user_company_access.c.company_id).where(
                user_company_access.c.user_id == user.id,
                user_company_access.c.company_id == company_id,
            )
        ).first()
        if not has_company:
            raise FinanceError("You do not have access to that company.", 403)

    allowed: frozenset[uuid.UUID] | None = None
    if not _unrestricted(user):
        rows = db.execute(
            select(Branch.id)
            .join(user_branch_access, user_branch_access.c.branch_id == Branch.id)
            .where(user_branch_access.c.user_id == user.id, Branch.company_id == company_id)
        ).scalars().all()
        allowed = frozenset(rows) if rows else None

    if branch_id is not None:
        branch = db.get(Branch, branch_id)
        if branch is None or branch.company_id != company_id:
            raise FinanceError("That branch does not belong to the company.", 404)
        if allowed is not None and branch_id not in allowed:
            raise FinanceError("You do not have access to that branch.", 403)
        allowed = frozenset({branch_id})

    return FinanceContext(company_id=company_id, user=user, audit=audit,
                          branch_id=branch_id, branch_ids=allowed)


def finance_context(permission: str):
    """Usage: ctx: FinanceContext = Depends(finance_context("finance.view"))"""

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
        user: User = Depends(require_permission(permission)),
        x_company_id: uuid.UUID | None = Header(default=None),
        x_branch_id: uuid.UUID | None = Header(default=None),
    ) -> FinanceContext:
        forwarded = request.headers.get("x-forwarded-for")
        audit = AuditContext(
            user_id=user.id,
            username=user.username,
            ip_address=forwarded.split(",")[0].strip() if forwarded
            else (request.client.host if request.client else None),
            user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        )
        return build_context(db, user, x_company_id, x_branch_id, audit)

    return dependency
