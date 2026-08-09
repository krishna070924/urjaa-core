from pydantic import BaseModel


class GlobalConfigResponse(BaseModel):
    announcement_text: str = ""
    maintenance_mode: bool = False


class GlobalConfigUpdateRequest(BaseModel):
    announcement_text: str | None = None
    maintenance_mode: bool | None = None


class SeoMetaResponse(BaseModel):
    title: str | None = None
    description: str | None = None
    og_image: str | None = None
