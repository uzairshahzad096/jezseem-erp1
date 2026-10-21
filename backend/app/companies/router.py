from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_permission
from app.companies.models import Branch, Company
from app.companies.schemas import BranchCreate, BranchResponse, CompanyCreate, CompanyResponse
from app.core.database import get_db

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyResponse])
def list_companies(
    db: Session = Depends(get_db),
    user=Depends(require_permission("admin.companies.view")),
):
    return db.scalars(select(Company)).all()


@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company(
    payload: CompanyCreate,
    db: Session = Depends(get_db),
    user=Depends(require_permission("admin.companies.create")),
):
    if db.scalar(select(Company).where(Company.code == payload.code)):
        raise HTTPException(status_code=400, detail="Company code already exists")
    company = Company(**payload.model_dump(), created_by=user.id)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.get("/{company_id}/branches", response_model=list[BranchResponse])
def list_branches(
    company_id: str,
    db: Session = Depends(get_db),
    user=Depends(require_permission("admin.branches.view")),
):
    return db.scalars(select(Branch).where(Branch.company_id == company_id)).all()


@router.post("/{company_id}/branches", response_model=BranchResponse, status_code=status.HTTP_201_CREATED)
def create_branch(
    company_id: str,
    payload: BranchCreate,
    db: Session = Depends(get_db),
    user=Depends(require_permission("admin.branches.create")),
):
    if not db.get(Company, company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    branch = Branch(**payload.model_dump(), created_by=user.id)
    db.add(branch)
    db.commit()
    db.refresh(branch)
    return branch
