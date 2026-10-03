"""O-04/D44: Custom Orders + Karigars admin schemas.

Phone numbers are normalised to a bare 10-digit Indian mobile number (the
`+91` prefix, if present, is stripped) so lookups/search never have to deal
with two representations of the same number. Reference image URLs reuse the
same MEDIA_BASE_URL choke point as CMS content (urjaa_core/schemas/cms_content.py)
-- the one place that keeps uploaded-media fields pinned to our own host.
"""
import re
from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, model_validator

from urjaa_core.schemas.cms_content import RequiredMediaUrl

_INDIAN_MOBILE_RE = re.compile(r"^(?:\+91)?([6-9]\d{9})$")


def _normalize_indian_mobile(value: str) -> str:
    compact = re.sub(r"[\s\-]", "", value.strip())
    match = _INDIAN_MOBILE_RE.match(compact)
    if not match:
        raise ValueError("Enter a valid 10-digit Indian mobile number")
    return match.group(1)


def _trimmed_name(value: str) -> str:
    trimmed = value.strip()
    if not (1 <= len(trimmed) <= 120):
        raise ValueError("name must be 1-120 characters")
    return trimmed


IndianMobile = Annotated[str, AfterValidator(_normalize_indian_mobile)]
TrimmedName = Annotated[str, AfterValidator(_trimmed_name)]


# =============================================================================
# Karigars
# =============================================================================

class KarigarCreateRequest(BaseModel):
    name: TrimmedName
    phone: IndianMobile
    speciality: str | None = Field(default=None, max_length=200)
    is_active: bool = True


def _reject_null(model: BaseModel, *names: str) -> None:
    """A partial update may omit a field, but an explicit null on a column the
    database requires would be a 500 — reject it as a 422 instead."""
    for name in names:
        if name in model.model_fields_set and getattr(model, name) is None:
            raise ValueError(f"{name} cannot be empty")


class KarigarUpdateRequest(BaseModel):
    """Partial update: a field left out (None) is unchanged -- same
    convention as DiscountUpdateRequest."""

    name: TrimmedName | None = None
    phone: IndianMobile | None = None
    speciality: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _no_null_required(self):
        _reject_null(self, "name", "phone", "is_active")
        return self


class AdminKarigarResponse(BaseModel):
    id: int
    store_id: UUID
    name: str
    phone: str
    speciality: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class AdminKarigarListResponse(BaseModel):
    items: list[AdminKarigarResponse]


# =============================================================================
# Custom orders
# =============================================================================

class CustomOrderCreateRequest(BaseModel):
    customer_name: TrimmedName
    customer_phone: IndianMobile
    design_notes: str | None = Field(default=None, max_length=4000)
    reference_image_urls: list[RequiredMediaUrl] = Field(default_factory=list, max_length=10)
    expected_date: date | None = None


class CustomOrderUpdateRequest(BaseModel):
    """General edit -- status and karigar changes go through their own
    endpoints so they get their own logged event kind."""

    customer_name: TrimmedName | None = None
    customer_phone: IndianMobile | None = None
    design_notes: str | None = Field(default=None, max_length=4000)
    reference_image_urls: list[RequiredMediaUrl] | None = Field(default=None, max_length=10)
    expected_date: date | None = None

    @model_validator(mode="after")
    def _no_null_required(self):
        _reject_null(self, "customer_name", "customer_phone", "reference_image_urls")
        return self


class CustomOrderStatusUpdateRequest(BaseModel):
    status_code: str = Field(min_length=1, max_length=30)
    note: str | None = Field(default=None, max_length=4000)
    # D44: moving out of a terminal status (delivered/cancelled) is a
    # deliberate reopen, not an accidental board drag -- must be explicit.
    reopen: bool = False


class CustomOrderKarigarAssignRequest(BaseModel):
    karigar_id: int | None = None


class AdminCustomOrderEventResponse(BaseModel):
    id: int
    at: datetime
    by_admin_id: int | None
    by_admin_email: str | None = None
    kind: str
    from_value: str | None
    to_value: str | None
    note: str | None

    class Config:
        orm_mode = True


class AdminCustomOrderResponse(BaseModel):
    id: int
    store_id: UUID
    customer_name: str
    customer_phone: str
    taken_at: datetime
    taken_by_admin_id: int | None
    karigar_id: int | None
    karigar_name: str | None = None
    status_id: int
    status_code: str
    status_label: str
    design_notes: str | None
    reference_image_urls: list[str]
    expected_date: date | None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class AdminCustomOrderDetailResponse(AdminCustomOrderResponse):
    events: list[AdminCustomOrderEventResponse] = Field(default_factory=list)


class PaginatedCustomOrdersResponse(BaseModel):
    items: list[AdminCustomOrderResponse]
    page: int
    limit: int
    total: int
    pages: int
