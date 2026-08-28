import secrets
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import delete, func, select

from app.api.dependencies import AppSettings, CurrentUser, DBSession
from app.models.call import CallParticipant, CallSession, CallStatus
from app.models.meeting import Meeting, MeetingMember, MeetingRole, MeetingStatus
from app.models.user import User
from app.schemas.call import CallResponse
from app.schemas.meeting import (
    MeetingCreate,
    MeetingJoinResponse,
    MeetingParticipantResponse,
    MeetingResolveRequest,
    MeetingResponse,
)
from app.services.calls import call_to_response
from app.services.jitsi import create_jitsi_token, make_room_name
from app.services.meetings import get_membership, meeting_to_response

router = APIRouter(prefix="/meetings", tags=["meetings"])


def _new_meeting_code() -> str:
    return secrets.token_urlsafe(8).replace("-", "").replace("_", "").upper()[:10]


async def _unique_meeting_code(db: DBSession) -> str:
    for _ in range(10):
        code = _new_meeting_code()
        if not await db.scalar(select(Meeting.id).where(Meeting.code == code)):
            return code
    raise HTTPException(status_code=500, detail="Could not allocate a meeting code")


async def _authorized_meeting(
    meeting_id: UUID, current_user: CurrentUser, db: DBSession
) -> tuple[Meeting, MeetingMember]:
    meeting = await db.get(Meeting, meeting_id)
    membership = await get_membership(db, meeting_id, current_user.id)
    if meeting is None or membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    return meeting, membership


@router.post("", response_model=MeetingResponse, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingCreate, current_user: CurrentUser, db: DBSession
) -> MeetingResponse:
    meeting_id = uuid4()
    meeting = Meeting(
        id=meeting_id,
        owner_id=current_user.id,
        title=payload.title.strip(),
        code=await _unique_meeting_code(db),
        room_name=make_room_name(meeting_id),
        kind=payload.kind,
        starts_at=payload.starts_at,
        max_participants=payload.max_participants,
        uses_waiting_room=payload.configuration.uses_waiting_room,
        is_microphone_enabled=payload.configuration.is_microphone_enabled,
        is_camera_enabled=payload.configuration.is_camera_enabled,
        is_speaker_enabled=payload.configuration.is_speaker_enabled,
    )
    db.add(meeting)
    db.add(
        MeetingMember(
            meeting_id=meeting_id,
            user_id=current_user.id,
            role=MeetingRole.host,
            admitted_at=datetime.now(UTC),
        )
    )
    await db.flush()
    response = await meeting_to_response(db, meeting)
    await db.commit()
    return response


@router.get("/upcoming", response_model=list[MeetingResponse])
async def upcoming_meetings(
    current_user: CurrentUser,
    db: DBSession,
    limit: int = Query(default=25, ge=1, le=100),
) -> list[MeetingResponse]:
    meetings = (
        await db.scalars(
            select(Meeting)
            .join(MeetingMember)
            .where(
                MeetingMember.user_id == current_user.id,
                Meeting.status.in_([MeetingStatus.scheduled, MeetingStatus.active]),
            )
            .order_by(Meeting.starts_at.asc())
            .limit(limit)
        )
    ).all()
    return [await meeting_to_response(db, meeting) for meeting in meetings]


@router.post("/resolve", response_model=MeetingResponse)
async def resolve_meeting(
    payload: MeetingResolveRequest, current_user: CurrentUser, db: DBSession
) -> MeetingResponse:
    raw_value = payload.code_or_link.strip()
    parsed = urlparse(raw_value)
    code = parsed.path.rstrip("/").split("/")[-1] if parsed.scheme else raw_value
    meeting = await db.scalar(select(Meeting).where(func.upper(Meeting.code) == code.upper()))
    if meeting is None or meeting.status in {MeetingStatus.ended, MeetingStatus.cancelled}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    membership = await get_membership(db, meeting.id, current_user.id)
    if membership is None:
        count = await db.scalar(
            select(func.count(MeetingMember.id)).where(MeetingMember.meeting_id == meeting.id)
        )
        if (count or 0) >= meeting.max_participants:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Meeting is full")
        db.add(
            MeetingMember(
                meeting_id=meeting.id,
                user_id=current_user.id,
                role=MeetingRole.participant,
                admitted_at=None if meeting.uses_waiting_room else datetime.now(UTC),
            )
        )
        await db.flush()
    response = await meeting_to_response(db, meeting)
    await db.commit()
    return response


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(
    meeting_id: UUID, current_user: CurrentUser, db: DBSession
) -> MeetingResponse:
    meeting, _ = await _authorized_meeting(meeting_id, current_user, db)
    return await meeting_to_response(db, meeting)


@router.get("/{meeting_id}/participants", response_model=list[MeetingParticipantResponse])
async def list_participants(
    meeting_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> list[MeetingParticipantResponse]:
    await _authorized_meeting(meeting_id, current_user, db)
    rows = (
        await db.execute(
            select(MeetingMember, User, CallParticipant.joined_at)
            .join(User, User.id == MeetingMember.user_id)
            .outerjoin(
                CallSession,
                (CallSession.meeting_id == MeetingMember.meeting_id)
                & (CallSession.status == CallStatus.active),
            )
            .outerjoin(
                CallParticipant,
                (CallParticipant.call_id == CallSession.id)
                & (CallParticipant.user_id == MeetingMember.user_id),
            )
            .where(MeetingMember.meeting_id == meeting_id)
            .order_by(MeetingMember.created_at.asc())
        )
    ).all()
    return [
        MeetingParticipantResponse(
            id=user.id,
            display_name=user.display_name,
            role=member.role,
            is_admitted=member.admitted_at is not None,
            joined_at=joined_at,
        )
        for member, user, joined_at in rows
    ]


@router.post(
    "/{meeting_id}/participants/{user_id}/admit",
    response_model=MeetingParticipantResponse,
)
async def admit_participant(
    meeting_id: UUID,
    user_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> MeetingParticipantResponse:
    _, actor_membership = await _authorized_meeting(meeting_id, current_user, db)
    if actor_membership.role not in {MeetingRole.host, MeetingRole.moderator}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Host role required")
    membership = await get_membership(db, meeting_id, user_id)
    user = await db.get(User, user_id)
    if membership is None or user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    membership.admitted_at = datetime.now(UTC)
    await db.commit()
    return MeetingParticipantResponse(
        id=user.id,
        display_name=user.display_name,
        role=membership.role,
        is_admitted=True,
    )


@router.delete("/{meeting_id}/participants/{user_id}", response_model=MeetingResponse)
async def remove_participant(
    meeting_id: UUID,
    user_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
) -> MeetingResponse:
    meeting, actor_membership = await _authorized_meeting(meeting_id, current_user, db)
    if actor_membership.role not in {MeetingRole.host, MeetingRole.moderator}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Host role required")
    target = await get_membership(db, meeting_id, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Participant not found")
    if target.role == MeetingRole.host:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Host cannot be removed")
    active_call_id = await db.scalar(
        select(CallSession.id).where(
            CallSession.meeting_id == meeting_id,
            CallSession.status == CallStatus.active,
        )
    )
    if active_call_id is not None:
        await db.execute(
            delete(CallParticipant).where(
                CallParticipant.call_id == active_call_id,
                CallParticipant.user_id == user_id,
            )
        )
    await db.delete(target)
    await db.flush()
    response = await meeting_to_response(db, meeting)
    await db.commit()
    return response


@router.post("/{meeting_id}/start", response_model=CallResponse)
async def start_meeting(meeting_id: UUID, current_user: CurrentUser, db: DBSession) -> CallResponse:
    meeting, membership = await _authorized_meeting(meeting_id, current_user, db)
    if membership.role not in {MeetingRole.host, MeetingRole.moderator}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Host role required")
    if meeting.status in {MeetingStatus.ended, MeetingStatus.cancelled}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Meeting is closed")

    existing = await db.scalar(
        select(CallSession).where(
            CallSession.meeting_id == meeting.id,
            CallSession.status == CallStatus.active,
        )
    )
    if existing is not None:
        return await call_to_response(db, existing)

    now = datetime.now(UTC)
    meeting.status = MeetingStatus.active
    call = CallSession(
        meeting_id=meeting.id,
        initiated_by_id=current_user.id,
        status=CallStatus.active,
        started_at=now,
    )
    db.add(call)
    await db.flush()
    db.add(CallParticipant(call_id=call.id, user_id=current_user.id, joined_at=now))
    await db.commit()
    await db.refresh(call)
    return await call_to_response(db, call)


@router.post("/{meeting_id}/join", response_model=MeetingJoinResponse)
async def join_meeting(
    meeting_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    settings: AppSettings,
) -> MeetingJoinResponse:
    meeting, membership = await _authorized_meeting(meeting_id, current_user, db)
    if meeting.status != MeetingStatus.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Meeting is not active")
    if meeting.uses_waiting_room and membership.admitted_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Waiting for host approval"
        )
    call = await db.scalar(
        select(CallSession)
        .where(CallSession.meeting_id == meeting.id, CallSession.status == CallStatus.active)
        .order_by(CallSession.created_at.desc())
    )
    if call is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No active call")

    participant = await db.scalar(
        select(CallParticipant).where(
            CallParticipant.call_id == call.id,
            CallParticipant.user_id == current_user.id,
        )
    )
    if participant is None:
        db.add(
            CallParticipant(
                call_id=call.id,
                user_id=current_user.id,
                joined_at=datetime.now(UTC),
            )
        )
    elif participant.joined_at is None:
        participant.joined_at = datetime.now(UTC)

    token, expires_at = create_jitsi_token(
        room_name=meeting.room_name,
        user=current_user,
        role=membership.role,
        settings=settings,
    )
    meeting_response = await meeting_to_response(db, meeting)
    await db.commit()
    return MeetingJoinResponse(
        meeting=meeting_response,
        call_id=call.id,
        server_url=str(settings.jitsi_base_url).rstrip("/"),
        room_name=meeting.room_name,
        token=token,
        token_expires_at=expires_at,
        role=membership.role,
    )


@router.post("/{meeting_id}/end", response_model=MeetingResponse)
async def end_meeting(
    meeting_id: UUID, current_user: CurrentUser, db: DBSession
) -> MeetingResponse:
    meeting, membership = await _authorized_meeting(meeting_id, current_user, db)
    if membership.role not in {MeetingRole.host, MeetingRole.moderator}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Host role required")
    now = datetime.now(UTC)
    meeting.status = MeetingStatus.ended
    meeting.ended_at = now
    calls = (
        await db.scalars(
            select(CallSession).where(
                CallSession.meeting_id == meeting.id,
                CallSession.status.in_([CallStatus.ringing, CallStatus.active]),
            )
        )
    ).all()
    for call in calls:
        call.status = CallStatus.ended
        call.ended_at = now
        call.end_reason = "host_ended"
    response = await meeting_to_response(db, meeting)
    await db.commit()
    return response
