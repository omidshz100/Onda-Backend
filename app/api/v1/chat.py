from datetime import UTC, datetime
from uuid import UUID

import jwt
from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy import select

from app.api.dependencies import AppSettings, CurrentUser, DBSession
from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.session import AsyncSessionFactory
from app.models.chat import ChatMessage, Conversation, ConversationKind, ConversationMember
from app.models.user import Device, User
from app.schemas.chat import (
    ChatMessageCreate,
    ChatMessagePage,
    ChatMessageResponse,
    ConversationResponse,
    DirectConversationCreate,
    MessageStatusResponse,
    ReadMessagesRequest,
    ReadMessagesResponse,
)
from app.services.apns import send_chat_message
from app.services.chat import (
    conversation_to_response,
    conversation_user_ids,
    make_direct_key,
    mark_message_delivered,
    message_to_response,
    require_conversation_member,
)
from app.services.realtime import realtime_manager

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "/conversations/direct",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_direct_conversation(
    payload: DirectConversationCreate, current_user: CurrentUser, db: DBSession
) -> ConversationResponse:
    if payload.recipient_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A direct conversation requires another user",
        )
    recipient = await db.get(User, payload.recipient_id)
    if recipient is None or not recipient.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    direct_key = make_direct_key(current_user.id, recipient.id)
    conversation = await db.scalar(
        select(Conversation).where(Conversation.direct_key == direct_key)
    )
    if conversation is None:
        conversation = Conversation(kind=ConversationKind.direct, direct_key=direct_key)
        db.add(conversation)
        await db.flush()
        db.add_all(
            [
                ConversationMember(conversation_id=conversation.id, user_id=current_user.id),
                ConversationMember(conversation_id=conversation.id, user_id=recipient.id),
            ]
        )
        await db.commit()
        await db.refresh(conversation)
    return await conversation_to_response(db, conversation, current_user.id)


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    current_user: CurrentUser,
    db: DBSession,
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[ConversationResponse]:
    conversations = (
        await db.scalars(
            select(Conversation)
            .join(ConversationMember)
            .where(ConversationMember.user_id == current_user.id)
            .order_by(Conversation.last_message_at.desc(), Conversation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return [
        await conversation_to_response(db, conversation, current_user.id)
        for conversation in conversations
    ]


@router.get(
    "/conversations/{conversation_id}/messages", response_model=ChatMessagePage
)
async def list_messages(
    conversation_id: UUID,
    current_user: CurrentUser,
    db: DBSession,
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> ChatMessagePage:
    await require_conversation_member(db, conversation_id, current_user.id)
    statement = select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
    if before is not None:
        statement = statement.where(ChatMessage.created_at < before)
    messages = (
        await db.scalars(
            statement.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(limit)
        )
    ).all()
    items = [await message_to_response(db, message) for message in reversed(messages)]
    next_before = messages[-1].created_at if len(messages) == limit else None
    return ChatMessagePage(items=items, next_before=next_before)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    conversation_id: UUID,
    payload: ChatMessageCreate,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    db: DBSession,
    settings: AppSettings,
) -> ChatMessageResponse:
    conversation = await require_conversation_member(db, conversation_id, current_user.id)
    body = payload.body.strip()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Message body cannot be blank",
        )
    if payload.client_message_id is not None:
        existing = await db.scalar(
            select(ChatMessage).where(
                ChatMessage.sender_id == current_user.id,
                ChatMessage.client_message_id == payload.client_message_id,
            )
        )
        if existing is not None:
            if existing.conversation_id != conversation_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="client_message_id is already used in another conversation",
                )
            return await message_to_response(db, existing)

    message = ChatMessage(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        client_message_id=payload.client_message_id,
        body=body,
    )
    db.add(message)
    await db.flush()
    conversation.last_message_at = message.created_at
    await db.commit()
    await db.refresh(message)
    response = await message_to_response(db, message)
    member_ids = await conversation_user_ids(db, conversation_id)
    await realtime_manager.send_to_users(
        member_ids,
        {"type": "message.created", "data": response.model_dump(mode="json")},
    )
    recipient_ids = member_ids - {current_user.id}
    devices = (
        await db.scalars(select(Device).where(Device.user_id.in_(recipient_ids)))
    ).all()
    background_tasks.add_task(
        send_chat_message,
        devices=list(devices),
        message_id=message.id,
        conversation_id=conversation_id,
        sender=current_user,
        body=message.body,
        settings=settings,
    )
    return response


@router.post("/messages/{message_id}/delivered", response_model=MessageStatusResponse)
async def mark_delivered(
    message_id: UUID, current_user: CurrentUser, db: DBSession
) -> MessageStatusResponse:
    message = await db.get(ChatMessage, message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    await require_conversation_member(db, message.conversation_id, current_user.id)
    await mark_message_delivered(db, message, current_user.id)
    response = await message_to_response(db, message)
    await realtime_manager.send_to_users(
        {message.sender_id},
        {"type": "message.delivered", "data": response.model_dump(mode="json")},
    )
    return MessageStatusResponse(message=response)


@router.post("/conversations/{conversation_id}/read", response_model=ReadMessagesResponse)
async def mark_conversation_read(
    conversation_id: UUID,
    payload: ReadMessagesRequest,
    current_user: CurrentUser,
    db: DBSession,
) -> ReadMessagesResponse:
    await require_conversation_member(db, conversation_id, current_user.id)
    target = await db.get(ChatMessage, payload.up_to_message_id)
    if target is None or target.conversation_id != conversation_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    now = datetime.now(UTC)
    messages = (
        await db.scalars(
            select(ChatMessage).where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.sender_id != current_user.id,
                ChatMessage.created_at <= target.created_at,
                ChatMessage.read_at.is_(None),
            )
        )
    ).all()
    sender_ids: set[UUID] = set()
    for message in messages:
        message.delivered_at = message.delivered_at or now
        message.read_at = now
        sender_ids.add(message.sender_id)
    await db.commit()
    event_data = {
        "conversation_id": str(conversation_id),
        "up_to_message_id": str(payload.up_to_message_id),
        "read_at": now.isoformat(),
    }
    await realtime_manager.send_to_users(
        sender_ids, {"type": "messages.read", "data": event_data}
    )
    return ReadMessagesResponse(
        conversation_id=conversation_id,
        up_to_message_id=payload.up_to_message_id,
        updated_count=len(messages),
    )


@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    settings = get_settings()
    if token is None:
        await websocket.close(code=4401, reason="Access token required")
        return
    try:
        user_id = decode_access_token(token, settings)
    except (jwt.InvalidTokenError, ValueError):
        await websocket.close(code=4401, reason="Invalid or expired access token")
        return
    async with AsyncSessionFactory() as db:
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            await websocket.close(code=4401, reason="Invalid or expired access token")
            return

    await realtime_manager.connect(user_id, websocket)
    await websocket.send_json({"type": "connected", "data": {"user_id": str(user_id)}})
    try:
        while True:
            event = await websocket.receive_json()
            if event.get("type") == "ping":
                await websocket.send_json(
                    {"type": "pong", "data": {"timestamp": datetime.now(UTC).isoformat()}}
                )
    except WebSocketDisconnect:
        await realtime_manager.disconnect(user_id, websocket)
