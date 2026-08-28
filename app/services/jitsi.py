from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import jwt

from app.core.config import Settings
from app.models.meeting import MeetingRole
from app.models.user import User


def create_jitsi_token(
    *,
    room_name: str,
    user: User,
    role: MeetingRole,
    settings: Settings,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.jitsi_token_minutes)
    is_moderator = role in {MeetingRole.host, MeetingRole.moderator}
    jitsi_domain = urlparse(str(settings.jitsi_base_url)).hostname or "*"
    payload: dict[str, Any] = {
        "aud": settings.jitsi_app_id,
        "iss": settings.jitsi_app_id,
        "sub": jitsi_domain,
        "room": room_name,
        "iat": int(now.timestamp()),
        "nbf": int((now - timedelta(seconds=5)).timestamp()),
        "exp": int(expires_at.timestamp()),
        "context": {
            "user": {
                "id": str(user.id),
                "name": user.display_name,
                "email": user.email,
                "moderator": is_moderator,
                "affiliation": "owner" if is_moderator else "member",
            },
            "features": {"recording": False, "livestreaming": False},
        },
    }
    return (
        jwt.encode(payload, settings.jitsi_app_secret, algorithm="HS256"),
        expires_at,
    )


def make_room_name(meeting_id: UUID) -> str:
    return f"onda-{meeting_id.hex}"
