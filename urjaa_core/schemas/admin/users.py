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
    # L4 follow-up: matches hash_admin_password's 8-char minimum (admin_auth.py)
    # so a too-short password fails cleanly as a 422 here, not an unhandled
    # 500 from hash_admin_password's ValueError.
    password: str = Field(min_length=8)
    role: str = Field(min_length=2)
    permissions: list[str] | None = None
    is_active: bool = True


class AdminUserUpdateRequest(BaseModel):
    email: str | None = None
    password: str | None = Field(default=None, min_length=8)
    role: str | None = None
    permissions: list[str] | None = None
    is_active: bool | None = None


class AdminUserStatusUpdateRequest(BaseModel):
    is_active: bool


class AdminUserDeleteResponse(BaseModel):
    message: str
