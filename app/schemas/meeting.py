from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.meeting import MeetingKind, MeetingRole, MeetingStatus


class MeetingConfiguration(BaseModel):
    uses_waiting_room: bool = True
    is_microphone_enabled: bool = True
    is_camera_enabled: bool = False
    is_speaker_enabled: bool = True


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    starts_at: datetime
    kind: MeetingKind = MeetingKind.group
    max_participants: int = Field(default=50, ge=2, le=500)
    configuration: MeetingConfiguration = Field(default_factory=MeetingConfiguration)


class MeetingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    code: str
    kind: MeetingKind
    status: MeetingStatus
    starts_at: datetime
    ended_at: datetime | None
    participant_count: int = 1
    configuration: MeetingConfiguration


class MeetingResolveRequest(BaseModel):
    code_or_link: str = Field(min_length=4, max_length=500)


class MeetingJoinResponse(BaseModel):
    meeting: MeetingResponse
    call_id: UUID
    server_url: str
    room_name: str
    token: str
    token_expires_at: datetime
    role: MeetingRole


class MeetingParticipantResponse(BaseModel):
    id: UUID
    display_name: str
    role: MeetingRole
    is_admitted: bool
    joined_at: datetime | None = None
