from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import DeviceTokenKind


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str
    is_email_verified: bool
    created_at: datetime


class UserUpdate(BaseModel):
    display_name: str = Field(min_length=2, max_length=100)


class DeviceUpsert(BaseModel):
    device_identifier: str = Field(min_length=8, max_length=255)
    apns_token: str = Field(min_length=32, max_length=255)
    environment: str = Field(pattern="^(sandbox|production)$")
    token_kind: DeviceTokenKind = DeviceTokenKind.standard


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
