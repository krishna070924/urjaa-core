from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UserAddressCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    address_line_1: str = Field(min_length=1)
    address_line_2: str | None = None
    city: str = Field(min_length=1)
    state: str = Field(min_length=1)
    pincode: str = Field(min_length=1)
    country: str = Field(min_length=1)
    is_default: bool | None = None


class UserAddressUpdateRequest(BaseModel):
    name: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    address_line_1: str = Field(min_length=1)
    address_line_2: str | None = None
    city: str = Field(min_length=1)
    state: str = Field(min_length=1)
    pincode: str = Field(min_length=1)
    country: str = Field(min_length=1)
    is_default: bool | None = None


class UserAddressResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    phone: str
    address_line_1: str
    address_line_2: str | None
    city: str
    state: str
    pincode: str
    country: str
    is_default: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
