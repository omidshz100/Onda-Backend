from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call import CallParticipant, CallSession, CallStatus
from app.models.meeting import Meeting, MeetingStatus
from app.models.user import User
from app.schemas.call import CallParticipantResponse, CallResponse


async def expire_stale_calls(db: AsyncSession, timeout_seconds: int) -> None:
    cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
    calls = (
        await db.scalars(
            select(CallSession).where(
                CallSession.status == CallStatus.ringing,
                CallSession.created_at <= cutoff,
            )
        )
    ).all()
    now = datetime.now(UTC)
    for call in calls:
        call.status = CallStatus.missed
        call.ended_at = now
        call.end_reason = "no_answer"
        meeting = await db.get(Meeting, call.meeting_id)
        if meeting is not None:
            meeting.status = MeetingStatus.ended
            meeting.ended_at = now
    if calls:
        await db.flush()


async def call_to_response(db: AsyncSession, call: CallSession) -> CallResponse:
    meeting = await db.get(Meeting, call.meeting_id)
    rows = (
        await db.execute(
            select(CallParticipant, User)
            .join(User, User.id == CallParticipant.user_id)
            .where(CallParticipant.call_id == call.id)
            .order_by(CallParticipant.created_at.asc())
        )
    ).all()
    return CallResponse(
        id=call.id,
        meeting_id=call.meeting_id,
        initiated_by_id=call.initiated_by_id,
        status=call.status,
        started_at=call.started_at,
        ended_at=call.ended_at,
        end_reason=call.end_reason,
        created_at=call.created_at,
        title=meeting.title if meeting is not None else "Call",
        video_enabled=meeting.is_camera_enabled if meeting is not None else False,
        participants=[
            CallParticipantResponse(
                user_id=user.id,
                display_name=user.display_name,
                joined_at=participant.joined_at,
                left_at=participant.left_at,
            )
            for participant, user in rows
        ],
    )
