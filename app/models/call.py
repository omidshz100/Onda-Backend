from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.meeting import Meeting
    from app.models.user import User


class CallStatus(StrEnum):
    ringing = "ringing"
    active = "active"
    ended = "ended"
    rejected = "rejected"
    cancelled = "cancelled"
    missed = "missed"


class CallSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "call_sessions"

    meeting_id: Mapped[UUID] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    initiated_by_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[CallStatus] = mapped_column(
        Enum(CallStatus, native_enum=False), default=CallStatus.ringing, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(64))

    meeting: Mapped["Meeting"] = relationship(back_populates="calls")
    participants: Mapped[list["CallParticipant"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )


class CallParticipant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "call_participants"
    __table_args__ = (UniqueConstraint("call_id", "user_id"),)

    call_id: Mapped[UUID] = mapped_column(
        ForeignKey("call_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    call: Mapped[CallSession] = relationship(back_populates="participants")
    user: Mapped["User"] = relationship()
