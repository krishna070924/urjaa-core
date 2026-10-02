from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CmsVersionSummary(BaseModel):
    """One entry in the version history list — metadata only, never the
    full saved content (that would make the GET response as heavy as
    fetching every version's content individually)."""

    index: int
    saved_at: datetime | None = None
    saved_by: str | None = None


class CmsGetResponse(BaseModel):
    current: dict[str, Any] | None = None
    versions: list[CmsVersionSummary] = []


class CmsSaveResponse(BaseModel):
    content: dict[str, Any]
    warnings: list[str] = []
