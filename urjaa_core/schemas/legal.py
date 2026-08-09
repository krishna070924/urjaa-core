from datetime import datetime

from pydantic import BaseModel, Field


class LegalPageResponse(BaseModel):
    key: str
    title: str
    content: str
    last_updated: datetime


class LegalPageUpsertRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str
