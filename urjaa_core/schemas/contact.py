from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class ContactRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    message: str = Field(min_length=1)
    store_id: UUID | None = None


class ContactCreateResponse(BaseModel):
    message: str


class ContactSubmissionResponse(BaseModel):
    id: UUID
    name: str
    email: str
    phone: str | None
    message: str
    store_id: UUID | None
    status: str
    created_at: datetime


class ContactStatusUpdateRequest(BaseModel):
    status: str = Field(pattern="^(new|read|replied)$")


class PaginatedContactSubmissionsResponse(BaseModel):
    items: list[ContactSubmissionResponse]
    page: int
    limit: int
    total: int
    pages: int
