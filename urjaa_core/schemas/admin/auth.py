from pydantic import BaseModel, Field


class AdminLoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class AdminAuthUserResponse(BaseModel):
    id: int
    email: str
    role: str
    role_id: int | None = None
    permissions: list[str]
    is_active: bool


class AdminLoginResponse(BaseModel):
    access_token: str
    auth_token: str
    token_type: str
    user: AdminAuthUserResponse
