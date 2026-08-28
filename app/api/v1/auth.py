from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select, update

from app.api.dependencies import AppSettings, DBSession
from app.core.security import (
    dummy_password_hash,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.user import RefreshSession, User
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.common import MessageResponse
from app.services.auth import issue_token_pair, refresh_session_is_valid

router = APIRouter(prefix="/auth", tags=["authentication"])


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None
    return user_agent, ip_address


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: DBSession,
    settings: AppSettings,
) -> TokenResponse:
    email = payload.email.lower()
    if await db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    user = User(
        email=email,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.flush()
    user_agent, ip_address = _request_metadata(request)
    tokens, _ = await issue_token_pair(
        db=db,
        user=user,
        settings=settings,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    await db.commit()
    return tokens


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: DBSession,
    settings: AppSettings,
) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == payload.email.lower()))
    password_matches = verify_password(
        payload.password,
        user.password_hash if user is not None else dummy_password_hash,
    )
    if user is None or not user.is_active or not password_matches:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user_agent, ip_address = _request_metadata(request)
    tokens, _ = await issue_token_pair(
        db=db,
        user=user,
        settings=settings,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    await db.commit()
    return tokens


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    db: DBSession,
    settings: AppSettings,
) -> TokenResponse:
    session = await db.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == hash_refresh_token(payload.refresh_token)
        )
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    if session.revoked_at is not None:
        await db.execute(
            update(RefreshSession)
            .where(RefreshSession.user_id == session.user_id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token reuse detected",
        )
    if not refresh_session_is_valid(session):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
        )

    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive")

    session.revoked_at = datetime.now(UTC)
    user_agent, ip_address = _request_metadata(request)
    tokens, replacement = await issue_token_pair(
        db=db,
        user=user,
        settings=settings,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    session.replaced_by_id = replacement.id
    await db.commit()
    return tokens


@router.post("/logout", response_model=MessageResponse)
async def logout(payload: LogoutRequest, db: DBSession) -> MessageResponse:
    session = await db.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == hash_refresh_token(payload.refresh_token)
        )
    )
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        await db.commit()
    return MessageResponse(message="Signed out")
