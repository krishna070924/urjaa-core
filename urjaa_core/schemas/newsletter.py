from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class NewsletterEmailRequest(BaseModel):
    email: EmailStr


class NewsletterMessageResponse(BaseModel):
    message: str


class NewsletterSubscriberResponse(BaseModel):
    id: UUID
    email: str
    subscribed_at: datetime
    unsubscribed_at: datetime | None


class PaginatedNewsletterSubscribersResponse(BaseModel):
    items: list[NewsletterSubscriberResponse]
    page: int
    limit: int
    total: int
    pages: int
