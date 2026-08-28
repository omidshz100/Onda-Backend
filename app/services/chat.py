from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, Conversation, ConversationMember
from app.models.user import User
from app.schemas.chat import ChatMessageResponse, ConversationResponse
from app.schemas.user import UserSummary


def make_direct_key(first_user_id: UUID, second_user_id: UUID) -> str:
    return ":".join(sorted((str(first_user_id), str(second_user_id))))


async def require_conversation_member(
    db: AsyncSession, conversation_id: UUID, user_id: UUID
) -> Conversation:
    conversation = await db.scalar(
        select(Conversation)
        .join(ConversationMember)
        .where(
            Conversation.id == conversation_id,
            ConversationMember.user_id == user_id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


async def conversation_user_ids(db: AsyncSession, conversation_id: UUID) -> set[UUID]:
    return set(
        (
            await db.scalars(
                select(ConversationMember.user_id).where(
                    ConversationMember.conversation_id == conversation_id
                )
            )
        ).all()
    )


async def message_to_response(db: AsyncSession, message: ChatMessage) -> ChatMessageResponse:
    sender = await db.get(User, message.sender_id)
    if sender is None:
        raise RuntimeError("Message sender is missing")
    return ChatMessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sender=UserSummary.model_validate(sender),
        client_message_id=message.client_message_id,
        body=message.body,
        delivered_at=message.delivered_at,
        read_at=message.read_at,
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


async def conversation_to_response(
    db: AsyncSession, conversation: Conversation, current_user_id: UUID
) -> ConversationResponse:
    participants = (
        await db.scalars(
            select(User)
            .join(ConversationMember, ConversationMember.user_id == User.id)
            .where(ConversationMember.conversation_id == conversation.id)
            .order_by(User.display_name.asc())
        )
    ).all()
    last_message = await db.scalar(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation.id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )
    unread_count = await db.scalar(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.sender_id != current_user_id,
            ChatMessage.read_at.is_(None),
        )
    )
    return ConversationResponse(
        id=conversation.id,
        kind=conversation.kind,
        participants=[UserSummary.model_validate(user) for user in participants],
        last_message=await message_to_response(db, last_message) if last_message else None,
        unread_count=unread_count or 0,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


async def mark_message_delivered(
    db: AsyncSession, message: ChatMessage, current_user_id: UUID
) -> None:
    if message.sender_id == current_user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sender cannot mark their own message as delivered",
        )
    if message.delivered_at is None:
        message.delivered_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(message)
