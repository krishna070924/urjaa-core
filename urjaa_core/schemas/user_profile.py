from pydantic import BaseModel, Field


class UserProfileUpdateRequest(BaseModel):
    full_name: str = Field(min_length=1)
    phone: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)
    confirm_password: str = Field(min_length=8)
