"""
Reusable FastAPI dependencies for authentication and permission checks.

Spec section 15 is explicit: "Never rely only on frontend permission checks.
Every sensitive permission must also be enforced in FastAPI." This module is
where that enforcement lives — every module router depends on
`require_permission(...)` rather than checking a role name.

During development `settings.AUTH_DISABLED` short-circuits both the identity
lookup and the permission check so the UI can be built before login is wired
up. It cannot be enabled in production: app startup aborts (see main.py).
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import decode_token
from app.core.config import settings
from app.core.database import get_db
from app.users.models import User

# auto_error=False so an absent header reaches our own handler rather than
# raising before AUTH_DISABLED can be considered.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _development_user(db: Session) -> User:
    user = db.scalar(select(User).where(User.username == settings.DEV_USER_USERNAME))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"AUTH_DISABLED is on but no user '{settings.DEV_USER_USERNAME}' exists. "
                "Run: docker compose exec backend python -m app.core.seed"
            ),
        )
    return user


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    if settings.AUTH_DISABLED:
        return _development_user(db)

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise credentials_exception

    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def require_permission(permission_code: str):
    """Usage: Depends(require_permission("sales.quotation.approve"))

    Superusers bypass the check — a platform-admin escape hatch only; never
    set is_superuser on a normal business user."""

    def checker(
        user: User = Depends(get_current_user),
    ) -> User:
        if settings.AUTH_DISABLED or user.is_superuser:
            return user

        held = {perm.code for role in user.roles for perm in role.permissions}
        if permission_code not in held:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission_code}",
            )
        return user

    return checker


def has_permission(user: User, permission_code: str) -> bool:
    """Whether the user holds a permission, for a screen that shows more or less
    rather than refusing outright (the home dashboard)."""
    if settings.AUTH_DISABLED or user.is_superuser:
        return True
    return any(perm.code == permission_code for role in user.roles for perm in role.permissions)
