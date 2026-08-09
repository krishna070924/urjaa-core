from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AdminRegisteredCustomerListItem(BaseModel):
    id: UUID
    email: str
    full_name: str
    phone: str | None = None
    source: Literal["WEBSITE", "STORE", "ADMIN"]
    is_active: bool
    provider: str
    provider_id: str | None = None
    created_at: datetime
    updated_at: datetime
    addresses_count: int


class AdminRegisteredCustomersPage(BaseModel):
    items: list[AdminRegisteredCustomerListItem]
    page: int
    limit: int
    total: int
    pages: int


class AdminRegisteredCustomerAddress(BaseModel):
    id: UUID
    name: str
    phone: str
    address_line_1: str
    address_line_2: str | None = None
    city: str
    state: str
    pincode: str
    country: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


class AdminRegisteredCustomerDetail(BaseModel):
    id: UUID
    email: str
    full_name: str
    phone: str | None = None
    source: Literal["WEBSITE", "STORE", "ADMIN"]
    is_active: bool
    provider: str
    provider_id: str | None = None
    created_at: datetime
    updated_at: datetime
    addresses: list[AdminRegisteredCustomerAddress]
