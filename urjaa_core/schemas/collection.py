from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CollectionResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str] = None
    banner_image: Optional[str] = None
    is_featured: bool = False
    display_order: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        orm_mode = True