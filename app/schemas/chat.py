from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.chat import ConversationKind
from app.schemas.user import UserSummary


class DirectConversationCreate(BaseModel):
    recipient_id: UUID


class ChatMessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    client_message_id: UUID | None = None


class ChatMessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    sender: UserSummary
    client_message_id: UUID | None
    body: str
    delivered_at: datetime | None
    read_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConversationResponse(BaseModel):
    id: UUID
    kind: ConversationKind
    participants: list[UserSummary]
    last_message: ChatMessageResponse | None
    unread_count: int
    created_at: datetime
    updated_at: datetime


class ChatMessagePage(BaseModel):
    items: list[ChatMessageResponse]
    next_before: datetime | None


class ReadMessagesRequest(BaseModel):
    up_to_message_id: UUID


class MessageStatusResponse(BaseModel):
    message: ChatMessageResponse


class ReadMessagesResponse(BaseModel):
    conversation_id: UUID
    up_to_message_id: UUID
    updated_count: int
