from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


ThemeValue = Literal["ivory", "obsidian"]


class UserPreferencesUpsertRequest(BaseModel):
    theme: ThemeValue | None = None
    wishlist: list[str] | None = None
    recently_viewed: list[str] | None = None
    preferred_categories: list[str] | None = None


class UserPreferencesResponse(BaseModel):
    user_id: UUID
    theme: ThemeValue
    wishlist: list[str]
    recently_viewed: list[str]
    preferred_categories: list[str]
    updated_at: datetime

    class Config:
        orm_mode = True
