from pydantic import BaseModel, Field


class AdminRolePermissionResponse(BaseModel):
    role: str
    role_id: int | None = None
    label: str
    description: str | None = None
    permissions: list[str]


class AdminUserResponse(BaseModel):
    id: int
    email: str
    role: str
    role_id: int | None = None
    permissions: list[str]
    is_active: bool


class AdminUserCreateRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)
    role: str = Field(min_length=2)
    permissions: list[str] | None = None
    is_active: bool = True


class AdminUserUpdateRequest(BaseModel):
    email: str | None = None
    password: str | None = None
    role: str | None = None
    permissions: list[str] | None = None
    is_active: bool | None = None


class AdminUserStatusUpdateRequest(BaseModel):
    is_active: bool


class AdminUserDeleteResponse(BaseModel):
    message: str
