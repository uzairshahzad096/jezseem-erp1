from pydantic import BaseModel


class CompanyBase(BaseModel):
    name: str
    code: str
    legal_name: str | None = None
    tax_number: str | None = None
    default_currency: str = "PKR"


class CompanyCreate(CompanyBase):
    pass


class CompanyResponse(CompanyBase):
    id: str
    is_active: bool

    model_config = {"from_attributes": True}


class BranchBase(BaseModel):
    company_id: str
    name: str
    code: str
    address: str | None = None


class BranchCreate(BranchBase):
    pass


class BranchResponse(BranchBase):
    id: str
    is_active: bool

    model_config = {"from_attributes": True}
