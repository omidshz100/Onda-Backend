from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.meeting import Meeting, MeetingMember
from app.schemas.meeting import MeetingConfiguration, MeetingResponse


async def meeting_to_response(db: AsyncSession, meeting: Meeting) -> MeetingResponse:
    participant_count = await db.scalar(
        select(func.count(MeetingMember.id)).where(MeetingMember.meeting_id == meeting.id)
    )
    return MeetingResponse(
        id=meeting.id,
        title=meeting.title,
        code=meeting.code,
        kind=meeting.kind,
        status=meeting.status,
        starts_at=meeting.starts_at,
        ended_at=meeting.ended_at,
        participant_count=participant_count or 0,
        configuration=MeetingConfiguration(
            uses_waiting_room=meeting.uses_waiting_room,
            is_microphone_enabled=meeting.is_microphone_enabled,
            is_camera_enabled=meeting.is_camera_enabled,
            is_speaker_enabled=meeting.is_speaker_enabled,
        ),
    )


async def get_membership(db: AsyncSession, meeting_id: UUID, user_id: UUID) -> MeetingMember | None:
    return await db.scalar(
        select(MeetingMember).where(
            MeetingMember.meeting_id == meeting_id,
            MeetingMember.user_id == user_id,
        )
    )
