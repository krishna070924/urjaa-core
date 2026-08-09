from pydantic import BaseModel, Field


class AdminPermissionResponse(BaseModel):
    id: int | None = None
    key: str
    description: str | None = None


class AdminRoleResponse(BaseModel):
    role_id: int
    role: str
    label: str
    description: str | None = None
    permissions: list[str]


class AdminRolesResponse(BaseModel):
    roles: list[AdminRoleResponse]
    permissions: list[AdminPermissionResponse]


class AdminRolePermissionsUpdateRequest(BaseModel):
    permissions: list[str] = Field(default_factory=list)
