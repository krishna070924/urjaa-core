"""Pydantic schemas for support tickets."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr


# ---------------------------------------------------------------------------
# Ticket
# ---------------------------------------------------------------------------

class TicketCreateRequest(BaseModel):
    subject: str
    body: str
    customer_name: str
    customer_email: str
    customer_phone: Optional[str] = None
    category: str = "general"
    priority: str = "normal"
    store_id: Optional[UUID] = None


class TicketUpdateRequest(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[UUID] = None
    category: Optional[str] = None


class TicketReplyCreateRequest(BaseModel):
    body: str
    is_internal: bool = False


class TicketReplyResponse(BaseModel):
    id: UUID
    ticket_id: UUID
    admin_id: Optional[UUID]
    admin_name: Optional[str]
    body: str
    is_internal: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TicketListItem(BaseModel):
    id: UUID
    subject: str
    customer_name: str
    customer_email: str
    category: str
    priority: str
    status: str
    assigned_to_name: Optional[str]
    reply_count: int
    store_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TicketDetailResponse(BaseModel):
    id: UUID
    subject: str
    body: str
    customer_name: str
    customer_email: str
    customer_phone: Optional[str]
    category: str
    priority: str
    status: str
    store_id: Optional[UUID]
    user_id: Optional[UUID]
    assigned_to: Optional[UUID]
    assigned_to_name: Optional[str]
    resolved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    replies: list[TicketReplyResponse]

    model_config = {"from_attributes": True}


class PaginatedTicketsResponse(BaseModel):
    items: list[TicketListItem]
    total: int
    page: int
    limit: int
    pages: int
