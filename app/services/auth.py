from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import create_access_token, create_refresh_token, hash_refresh_token
from app.models.user import RefreshSession, User
from app.schemas.auth import TokenResponse


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def refresh_session_is_valid(session: RefreshSession) -> bool:
    return session.revoked_at is None and _as_utc(session.expires_at) > datetime.now(UTC)


async def issue_token_pair(
    *,
    db: AsyncSession,
    user: User,
    settings: Settings,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[TokenResponse, RefreshSession]:
    access_token, access_expires_at = create_access_token(user.id, settings)
    refresh_token = create_refresh_token()
    refresh_session = RefreshSession(
        user_id=user.id,
        token_hash=hash_refresh_token(refresh_token),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(refresh_session)
    await db.flush()
    return (
        TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_at=access_expires_at,
        ),
        refresh_session,
    )
