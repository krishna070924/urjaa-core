from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Per-event data payloads — all fields optional/nullable for resilience
# ---------------------------------------------------------------------------

class ProductViewData(BaseModel):
    product_id:  Optional[str] = None
    variant_id:  Optional[str] = None
    referrer:    Optional[str] = None
    duration_ms: Optional[int] = None


class SearchData(BaseModel):
    query:              Optional[str] = None
    result_count:       Optional[int] = None
    clicked_product_id: Optional[str] = None


class CartData(BaseModel):
    event_type:     Optional[str] = None   # add | remove | checkout_started | checkout_abandoned
    product_id:     Optional[str] = None
    variant_id:     Optional[str] = None
    quantity:       Optional[int] = None
    price_at_event: Optional[float] = None


# ---------------------------------------------------------------------------
# Discriminated union item
# ---------------------------------------------------------------------------

class ProductViewItem(BaseModel):
    type:       Literal["product_view"]
    session_id: str
    data:       ProductViewData = Field(default_factory=ProductViewData)


class SearchItem(BaseModel):
    type:       Literal["search"]
    session_id: str
    data:       SearchData = Field(default_factory=SearchData)


class CartItem(BaseModel):
    type:       Literal["cart"]
    session_id: str
    data:       CartData = Field(default_factory=CartData)


BatchEventItem = Annotated[
    Union[ProductViewItem, SearchItem, CartItem],
    Field(discriminator="type"),
]


class BatchEventsRequest(BaseModel):
    events: list[BatchEventItem] = Field(default_factory=list)

    @field_validator("events")
    @classmethod
    def max_twenty(cls, v: list) -> list:
        if len(v) > 20:
            raise ValueError("Maximum 20 events per batch")
        return v


class BatchEventsResponse(BaseModel):
    accepted: int
