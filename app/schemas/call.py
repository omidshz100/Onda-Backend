from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.call import CallStatus


class DirectCallCreate(BaseModel):
    callee_id: UUID
    title: str = Field(default="Direct call", min_length=1, max_length=120)
    video_enabled: bool = True


class CallParticipantResponse(BaseModel):
    user_id: UUID
    display_name: str
    joined_at: datetime | None
    left_at: datetime | None


class CallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    meeting_id: UUID
    initiated_by_id: UUID
    status: CallStatus
    started_at: datetime | None
    ended_at: datetime | None
    end_reason: str | None
    created_at: datetime
    title: str
    video_enabled: bool
    participants: list[CallParticipantResponse]


class CallEndRequest(BaseModel):
    reason: str = Field(default="completed", min_length=1, max_length=64)
