from pydantic import BaseModel, Field


class CustomerSessionCreateRequest(BaseModel):
    email: str = Field(min_length=3)
    full_name: str = Field(min_length=1)
    phone: str | None = None


class CustomerSessionProfile(BaseModel):
    id: int
    store_id: str
    email: str
    full_name: str
    phone: str | None


class CustomerSessionResponse(BaseModel):
    token: str
    customer: CustomerSessionProfile
