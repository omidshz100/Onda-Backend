from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.call import CallSession
    from app.models.user import User


class MeetingStatus(StrEnum):
    scheduled = "scheduled"
    active = "active"
    ended = "ended"
    cancelled = "cancelled"


class MeetingKind(StrEnum):
    group = "group"
    direct = "direct"


class MeetingRole(StrEnum):
    host = "host"
    moderator = "moderator"
    participant = "participant"


class Meeting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "meetings"

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    room_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    kind: Mapped[MeetingKind] = mapped_column(
        Enum(MeetingKind, native_enum=False), default=MeetingKind.group, nullable=False
    )
    status: Mapped[MeetingStatus] = mapped_column(
        Enum(MeetingStatus, native_enum=False), default=MeetingStatus.scheduled, nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uses_waiting_room: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_microphone_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_camera_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_speaker_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_participants: Mapped[int] = mapped_column(Integer, default=50, nullable=False)

    members: Mapped[list["MeetingMember"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    calls: Mapped[list["CallSession"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )


class MeetingMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "meeting_members"
    __table_args__ = (UniqueConstraint("meeting_id", "user_id"),)

    meeting_id: Mapped[UUID] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[MeetingRole] = mapped_column(
        Enum(MeetingRole, native_enum=False), default=MeetingRole.participant, nullable=False
    )
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    meeting: Mapped[Meeting] = relationship(back_populates="members")
    user: Mapped["User"] = relationship()
