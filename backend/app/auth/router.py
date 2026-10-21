from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import AuditContext, record
from app.auth.dependencies import get_current_user
from app.auth.schemas import CurrentUserResponse, LoginRequest, TokenResponse
from app.auth.security import create_access_token, create_refresh_token, verify_password
from app.core.database import get_db
from app.users.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _audit_login(db: Session, request: Request, user: User | None, username: str,
                 action: str, reason: str | None = None) -> None:
    """Record a sign-in attempt. Its own commit, because a failed login
    raises afterwards and would otherwise roll the record back."""
    forwarded = request.headers.get("x-forwarded-for")
    ctx = AuditContext(
        user_id=user.id if user else None,
        username=user.username if user else username[:100],
        ip_address=forwarded.split(",")[0].strip() if forwarded
        else (request.client.host if request.client else None),
        user_agent=(request.headers.get("user-agent") or "")[:255] or None,
    )
    record(db, ctx, action=action, module="auth", entity="users",
           entity_id=user.id if user else None, reason=reason)
    db.commit()


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))

    if not user or not verify_password(payload.password, user.hashed_password):
        _audit_login(db, request, user, payload.username, "login_failed", "Incorrect username or password")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    if not user.is_active:
        _audit_login(db, request, user, payload.username, "login_failed", "Account inactive")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

    _audit_login(db, request, user, payload.username, "login")
    return TokenResponse(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.get("/me", response_model=CurrentUserResponse)
def read_current_user(user: User = Depends(get_current_user)):
    return CurrentUserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        roles=[role.name for role in user.roles],
    )
