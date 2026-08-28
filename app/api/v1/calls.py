from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from sqlalchemy import select

from app.api.dependencies import AppSettings, CurrentUser, DBSession
from app.models.call import CallParticipant, CallSession, CallStatus
from app.models.meeting import Meeting, MeetingKind, MeetingMember, MeetingRole, MeetingStatus
from app.models.user import Device, User
from app.schemas.call import CallEndRequest, CallResponse, DirectCallCreate
from app.schemas.common import MessageResponse
from app.services.apns import send_incoming_call
from app.services.calls import call_to_response, expire_stale_calls
from app.services.jitsi import make_room_name

router = APIRouter(prefix="/calls", tags=["calls"])


async def _participant_call(call_id: UUID, user_id: UUID, db: DBSession) -> CallSession:
    call = await db.scalar(
        select(CallSession)
        .join(CallParticipant)
        .where(CallSession.id == call_id, CallParticipant.user_id == user_id)
    )
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call not found")
    return call


@router.post("", response_model=CallResponse, status_code=status.HTTP_201_CREATED)
async def create_direct_call(
    payload: DirectCallCreate,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    db: DBSession,
    settings: AppSettings,
) -> CallResponse:
    if payload.callee_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot call yourself",
        )
    callee = await db.get(User, payload.callee_id)
    if callee is None or not callee.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    meeting_id = uuid4()
    meeting = Meeting(
        id=meeting_id,
        owner_id=current_user.id,
        title=payload.title.strip(),
        code=uuid4().hex[:10].upper(),
        room_name=make_room_name(meeting_id),
        kind=MeetingKind.direct,
        status=MeetingStatus.scheduled,
        starts_at=datetime.now(UTC),
        max_participants=2,
        uses_waiting_room=False,
        is_camera_enabled=payload.video_enabled,
    )
    db.add(meeting)
    db.add_all(
        [
            MeetingMember(meeting_id=meeting_id, user_id=current_user.id, role=MeetingRole.host),
            MeetingMember(meeting_id=meeting_id, user_id=callee.id, role=MeetingRole.participant),
        ]
    )
    call = CallSession(
        meeting_id=meeting_id,
        initiated_by_id=current_user.id,
        status=CallStatus.ringing,
    )
    db.add(call)
    await db.flush()
    db.add_all(
        [
            CallParticipant(
                call_id=call.id,
                user_id=current_user.id,
                joined_at=datetime.now(UTC),
            ),
            CallParticipant(call_id=call.id, user_id=callee.id),
        ]
    )
    devices = (await db.scalars(select(Device).where(Device.user_id == callee.id))).all()
    await db.commit()
    await db.refresh(call)
    background_tasks.add_task(
        send_incoming_call,
        devices=list(devices),
        call_id=call.id,
        meeting_id=meeting.id,
        caller=current_user,
        video_enabled=payload.video_enabled,
        settings=settings,
    )
    return await call_to_response(db, call)


@router.get("/history", response_model=list[CallResponse])
async def call_history(
    current_user: CurrentUser,
    db: DBSession,
    settings: AppSettings,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[CallResponse]:
    await expire_stale_calls(db, settings.call_ring_timeout_seconds)
    calls = (
        await db.scalars(
            select(CallSession)
            .join(CallParticipant)
            .where(CallParticipant.user_id == current_user.id)
            .order_by(CallSession.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    responses = [await call_to_response(db, call) for call in calls]
    await db.commit()
    return responses


@router.get("/incoming", response_model=list[CallResponse])
async def incoming_calls(
    current_user: CurrentUser,
    db: DBSession,
    settings: AppSettings,
) -> list[CallResponse]:
    await expire_stale_calls(db, settings.call_ring_timeout_seconds)
    calls = (
        await db.scalars(
            select(CallSession)
            .join(CallParticipant)
            .where(
                CallParticipant.user_id == current_user.id,
                CallSession.initiated_by_id != current_user.id,
                CallSession.status == CallStatus.ringing,
            )
            .order_by(CallSession.created_at.desc())
        )
    ).all()
    responses = [await call_to_response(db, call) for call in calls]
    await db.commit()
    return responses


@router.get("/{call_id}", response_model=CallResponse)
async def get_call(call_id: UUID, current_user: CurrentUser, db: DBSession) -> CallResponse:
    return await call_to_response(db, await _participant_call(call_id, current_user.id, db))


@router.post("/{call_id}/accept", response_model=CallResponse)
async def accept_call(call_id: UUID, current_user: CurrentUser, db: DBSession) -> CallResponse:
    call = await _participant_call(call_id, current_user.id, db)
    if call.initiated_by_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Caller cannot accept")
    if call.status != CallStatus.ringing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Call is not ringing")
    now = datetime.now(UTC)
    call.status = CallStatus.active
    call.started_at = now
    participant = await db.scalar(
        select(CallParticipant).where(
            CallParticipant.call_id == call.id,
            CallParticipant.user_id == current_user.id,
        )
    )
    if participant is not None:
        participant.joined_at = now
    meeting = await db.get(Meeting, call.meeting_id)
    if meeting is not None:
        meeting.status = MeetingStatus.active
    await db.commit()
    await db.refresh(call)
    return await call_to_response(db, call)


@router.post("/{call_id}/reject", response_model=CallResponse)
async def reject_call(call_id: UUID, current_user: CurrentUser, db: DBSession) -> CallResponse:
    call = await _participant_call(call_id, current_user.id, db)
    if call.initiated_by_id == current_user.id or call.status != CallStatus.ringing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Call cannot be rejected")
    call.status = CallStatus.rejected
    call.ended_at = datetime.now(UTC)
    call.end_reason = "rejected"
    await db.commit()
    await db.refresh(call)
    return await call_to_response(db, call)


@router.post("/{call_id}/cancel", response_model=CallResponse)
async def cancel_call(call_id: UUID, current_user: CurrentUser, db: DBSession) -> CallResponse:
    call = await _participant_call(call_id, current_user.id, db)
    if call.initiated_by_id != current_user.id or call.status != CallStatus.ringing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Call cannot be cancelled")
    call.status = CallStatus.cancelled
    call.ended_at = datetime.now(UTC)
    call.end_reason = "caller_cancelled"
    await db.commit()
    await db.refresh(call)
    return await call_to_response(db, call)


@router.post("/{call_id}/end", response_model=CallResponse)
async def end_call(
    call_id: UUID,
    payload: CallEndRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> CallResponse:
    call = await _participant_call(call_id, current_user.id, db)
    if call.status not in {CallStatus.ringing, CallStatus.active}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Call is already closed")
    now = datetime.now(UTC)
    call.status = CallStatus.ended
    call.ended_at = now
    call.end_reason = payload.reason
    participant = await db.scalar(
        select(CallParticipant).where(
            CallParticipant.call_id == call.id,
            CallParticipant.user_id == current_user.id,
        )
    )
    if participant is not None:
        participant.left_at = now
    meeting = await db.get(Meeting, call.meeting_id)
    if meeting is not None:
        meeting.status = MeetingStatus.ended
        meeting.ended_at = now
    await db.commit()
    await db.refresh(call)
    return await call_to_response(db, call)


@router.post("/{call_id}/leave", response_model=MessageResponse)
async def leave_call(call_id: UUID, current_user: CurrentUser, db: DBSession) -> MessageResponse:
    call = await _participant_call(call_id, current_user.id, db)
    participant = await db.scalar(
        select(CallParticipant).where(
            CallParticipant.call_id == call.id,
            CallParticipant.user_id == current_user.id,
        )
    )
    if participant is not None and participant.left_at is None:
        participant.left_at = datetime.now(UTC)
        await db.commit()
    return MessageResponse(message="Left call")
