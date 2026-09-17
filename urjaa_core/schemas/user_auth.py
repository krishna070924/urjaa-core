from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserSignupRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1)
    phone: str | None = None


class UserLoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class UserRefreshRequest(BaseModel):
    # H3 FIX: refresh_token now normally arrives via an HttpOnly cookie, not this
    # field — kept optional for non-browser callers that can't use cookies.
    refresh_token: str | None = Field(default=None, min_length=16)


class UserLogoutRequest(BaseModel):
    refresh_token: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3)


class ForgotPasswordResponse(BaseModel):
    message: str


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=16)
    new_password: str = Field(min_length=8)


class GoogleLoginRequest(BaseModel):
    id_token: str = Field(min_length=16)


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    phone: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserAuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token: str
    token_type: str = "bearer"
    user: UserProfileResponse


class MessageResponse(BaseModel):
    message: str
