"""Security -> Users: logins for employees, their role, and whether they see
the business figures on the home dashboard.

A user is given one of two main roles — Administrator (everything) or Staff
(every module, without the business figures and without these Security
screens) — and, optionally, the "Business Dashboard" role, which adds the
sales and money figures to a Staff user's dashboard.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.auth.security import hash_password
from app.core.database import get_db
from app.inventory.router import active_company_id
from app.users.models import Role, User, user_company_access

router = APIRouter(prefix="/security", tags=["security"])

MAIN_ROLES = ("Administrator", "Staff")
BUSINESS_ROLE = "Business Dashboard"


def _role(db: Session, name: str) -> Role:
    role = db.scalar(select(Role).where(Role.name == name).order_by(Role.created_at))
    if role is None:
        raise HTTPException(500, f"The {name} role is missing; run the database upgrade.")
    return role


def _out(u: User) -> dict:
    names = {r.name for r in u.roles}
    main = next((r for r in MAIN_ROLES if r in names), None)
    return {"id": str(u.id), "username": u.username, "full_name": u.full_name, "email": u.email,
            "is_active": u.is_active, "is_superuser": u.is_superuser, "role": main,
            "other_roles": sorted(names - set(MAIN_ROLES) - {BUSINESS_ROLE}),
            "business_dashboard": u.is_superuser or main == "Administrator" or BUSINESS_ROLE in names}


@router.get("/users")
def list_users(db: Session = Depends(get_db), user: User = Depends(require_permission("security.users.view"))):
    users = db.scalars(select(User).order_by(User.is_active.desc(), func.lower(User.full_name))).all()
    return {"items": [_out(u) for u in users], "total": len(users), "page": 1, "page_size": len(users)}


class UserIn(BaseModel):
    username: str | None = None
    full_name: str
    email: str
    password: str | None = None
    role: str = "Staff"
    business_dashboard: bool = False
    is_active: bool = True


def _apply_roles(db: Session, u: User, role: str, business: bool) -> None:
    if role not in MAIN_ROLES:
        raise HTTPException(400, f"Role must be {' or '.join(MAIN_ROLES)}.")
    keep = [r for r in u.roles if r.name not in MAIN_ROLES and r.name != BUSINESS_ROLE]
    roles = keep + [_role(db, role)]
    # An Administrator sees everything already; the extra role is for Staff.
    if business and role != "Administrator":
        roles.append(_role(db, BUSINESS_ROLE))
    u.roles = roles


def _check_password(password: str | None) -> str:
    if not password or len(password) < 8:
        raise HTTPException(400, "The password must be at least 8 characters.")
    return password


@router.post("/users", status_code=201)
def create_user(payload: UserIn, db: Session = Depends(get_db),
                user: User = Depends(require_permission("security.users.create"))):
    username = (payload.username or "").strip().lower()
    if not username or not payload.full_name.strip() or not payload.email.strip():
        raise HTTPException(400, "Enter the username, full name and email.")
    if db.scalar(select(User).where(func.lower(User.username) == username)):
        raise HTTPException(400, f"The username {username} is taken.")
    if db.scalar(select(User).where(func.lower(User.email) == payload.email.strip().lower())):
        raise HTTPException(400, "Another user has that email.")
    u = User(id=uuid.uuid4(), username=username, full_name=payload.full_name.strip(), email=payload.email.strip(),
             hashed_password=hash_password(_check_password(payload.password)), is_active=payload.is_active,
             is_superuser=False)
    db.add(u)
    _apply_roles(db, u, payload.role, payload.business_dashboard)
    db.flush()
    # Access to the working company, without which the finance screens refuse them.
    db.execute(user_company_access.insert().values(user_id=u.id, company_id=active_company_id(db)))
    db.commit()
    return _out(u)


@router.put("/users/{user_id}")
def update_user(user_id: uuid.UUID, payload: UserIn, db: Session = Depends(get_db),
                user: User = Depends(require_permission("security.users.edit"))):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found.")
    if u.id == user.id and (not payload.is_active or (payload.role != "Administrator" and not u.is_superuser)):
        raise HTTPException(400, "You cannot switch off or demote your own login.")
    if db.scalar(select(User).where(func.lower(User.email) == payload.email.strip().lower(), User.id != u.id)):
        raise HTTPException(400, "Another user has that email.")
    u.full_name, u.email, u.is_active = payload.full_name.strip(), payload.email.strip(), payload.is_active
    _apply_roles(db, u, payload.role, payload.business_dashboard)
    if payload.password:
        u.hashed_password = hash_password(_check_password(payload.password))
    db.commit()
    return _out(u)
