"""Pydantic schemas for notification campaigns."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class CampaignCreateRequest(BaseModel):
    name: str
    type: str = "whatsapp"
    trigger_type: str
    template_name: str
    template_params: dict[str, Any] = {}
    audience_filter: dict[str, Any] = {}
    scheduled_at: Optional[datetime] = None


class CampaignUpdateRequest(BaseModel):
    name: Optional[str] = None
    trigger_type: Optional[str] = None
    template_name: Optional[str] = None
    template_params: Optional[dict[str, Any]] = None
    audience_filter: Optional[dict[str, Any]] = None
    scheduled_at: Optional[datetime] = None


class NotificationLogResponse(BaseModel):
    id: UUID
    user_id: Optional[UUID]
    channel: str
    recipient: str
    status: str
    provider_msg_id: Optional[str]
    error_message: Optional[str]
    sent_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class CampaignListItem(BaseModel):
    id: UUID
    name: str
    type: str
    trigger_type: str
    status: str
    recipient_count: int
    store_id: Optional[UUID]
    scheduled_at: Optional[datetime]
    sent_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class CampaignDetailResponse(BaseModel):
    id: UUID
    name: str
    type: str
    trigger_type: str
    template_name: str
    template_params: dict[str, Any]
    audience_filter: dict[str, Any]
    status: str
    recipient_count: int
    store_id: Optional[UUID]
    created_by: Optional[UUID]
    scheduled_at: Optional[datetime]
    sent_at: Optional[datetime]
    created_at: datetime
    logs: list[NotificationLogResponse] = []

    model_config = {"from_attributes": True}


class AudiencePreviewResponse(BaseModel):
    count: int
    sample_users: list[dict[str, Any]]


class PaginatedCampaignsResponse(BaseModel):
    items: list[CampaignListItem]
    total: int
    page: int
    limit: int
    pages: int
