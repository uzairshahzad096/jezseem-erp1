from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.companies.models import Branch, Company, FinancialYear
from app.core.database import get_db
from app.dashboard.schemas import DashboardSummary, StatValue
from app.users.models import User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Figures for the home dashboard.

    Only modules that actually exist contribute a value. Sales, receivables,
    stock, revenue and activity are reported as None until Phases 5-8 build
    those tables, so the UI shows an em dash instead of a misleading zero.
    """
    company = db.scalar(select(Company).order_by(Company.created_at).limit(1))
    branch = (
        db.scalar(select(Branch).where(Branch.company_id == company.id).limit(1))
        if company
        else None
    )
    financial_year = (
        db.scalar(
            select(FinancialYear).where(
                FinancialYear.company_id == company.id,
                FinancialYear.is_current.is_(True),
            )
        )
        if company
        else None
    )

    active_users = db.scalar(
        select(func.count()).select_from(User).where(User.is_active.is_(True))
    )

    return DashboardSummary(
        company_name=company.name if company else "—",
        branch_name=branch.name if branch else None,
        financial_year=financial_year.name if financial_year else None,
        user_full_name=user.full_name,
        stats={
            # Real, because the Security module exists.
            "activeUsers": StatValue(
                value=float(active_users or 0), formatted=f"{active_users or 0:,}"
            ),
            # Awaiting their modules — see Phases 5-8.
            "sales": StatValue(),
            "customers": StatValue(),
            "stockItems": StatValue(),
            "receivables": StatValue(),
        },
        revenue=None,
        sales_statistics={},
        recent_activity=[],
        top_products=[],
    )


@router.get("/overview")
def dashboard_overview(view: str | None = None, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """The home dashboard. Sales, receivables and customer figures go only to users
    holding dashboard.business.view; everyone else gets the simple one — decided
    here, so the figures never reach a browser that should not show them.
    `view=simple` lets anyone see the simple one (to preview what staff see)."""
    from app.auth.dependencies import has_permission
    from app.dashboard.overview import overview, simple
    from app.inventory.router import active_company_id
    company_id = active_company_id(db)
    if view == "simple" or not has_permission(user, "dashboard.business.view"):
        data = simple(db, company_id, user)
        data["can_see_business"] = has_permission(user, "dashboard.business.view")
        return data
    data = overview(db, company_id, user)
    data["mode"] = "business"
    return data
