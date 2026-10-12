import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


class NewsletterSubscribeRequest(BaseModel):
    email: EmailStr
    phone: str | None = Field(default=None, max_length=24)
    whatsapp_opt_in: bool = False
    source: Literal["footer", "popup"] = "footer"

    @model_validator(mode="after")
    def _phone_only_with_whatsapp(self):
        # Kept only when the separate WhatsApp box is ticked: a number given
        # for anything else is not consent to be messaged.
        if not self.whatsapp_opt_in:
            self.phone = None
            return self
        phone = re.sub(r"[\s()\-]", "", self.phone or "")
        if not re.fullmatch(r"\+?[0-9]{10,15}", phone):
            raise ValueError("Enter a valid phone number for WhatsApp")
        self.phone = phone
        return self


class NewsletterUnsubscribeRequest(BaseModel):
    email: EmailStr
    token: str = Field(min_length=1, max_length=128)


class NewsletterMessageResponse(BaseModel):
    message: str


class NewsletterSubscriberResponse(BaseModel):
    id: UUID
    email: str
    phone: str | None = None
    whatsapp_opt_in: bool = False
    source: str = "footer"
    subscribed_at: datetime
    unsubscribed_at: datetime | None


class PaginatedNewsletterSubscribersResponse(BaseModel):
    items: list[NewsletterSubscriberResponse]
    page: int
    limit: int
    total: int
    pages: int
