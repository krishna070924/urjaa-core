from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class StoreLocationResponse(BaseModel):
    id: UUID
    store_name: str
    address: str
    city: str
    state: str
    pincode: str
    phone: str | None
    hours: dict
    lat: Decimal | None
    lng: Decimal | None


class StoreLocationCreateRequest(BaseModel):
    store_id: UUID
    address: str = Field(min_length=1, max_length=255)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    pincode: str = Field(min_length=1, max_length=10)
    phone: str | None = Field(default=None, max_length=20)
    hours: dict = Field(default_factory=dict)
    lat: Decimal | None = None
    lng: Decimal | None = None
    is_active: bool = True


class StoreLocationUpdateRequest(BaseModel):
    store_id: UUID | None = None
    address: str | None = Field(default=None, min_length=1, max_length=255)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    state: str | None = Field(default=None, min_length=1, max_length=100)
    pincode: str | None = Field(default=None, min_length=1, max_length=10)
    phone: str | None = Field(default=None, max_length=20)
    hours: dict | None = None
    lat: Decimal | None = None
    lng: Decimal | None = None
    is_active: bool | None = None


class AdminStoreLocationResponse(BaseModel):
    id: UUID
    store_id: UUID
    store_name: str
    address: str
    city: str
    state: str
    pincode: str
    phone: str | None
    hours: dict
    lat: Decimal | None
    lng: Decimal | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
