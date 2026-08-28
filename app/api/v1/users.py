from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import delete, or_, select

from app.api.dependencies import CurrentUser, DBSession
from app.models.user import Device, User
from app.schemas.common import MessageResponse
from app.schemas.user import DeviceUpsert, UserResponse, UserSummary, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_me(payload: UserUpdate, current_user: CurrentUser, db: DBSession) -> UserResponse:
    current_user.display_name = payload.display_name.strip()
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.put("/me/devices", response_model=MessageResponse, status_code=status.HTTP_200_OK)
async def register_device(
    payload: DeviceUpsert, current_user: CurrentUser, db: DBSession
) -> MessageResponse:
    device = await db.scalar(
        select(Device).where(
            or_(
                (
                    (Device.user_id == current_user.id)
                    & (Device.device_identifier == payload.device_identifier)
                ),
                Device.apns_token == payload.apns_token,
            )
        )
    )
    if device is None:
        device = Device(
            user_id=current_user.id,
            device_identifier=payload.device_identifier,
            apns_token=payload.apns_token,
            environment=payload.environment,
            token_kind=payload.token_kind,
            last_seen_at=datetime.now(UTC),
        )
        db.add(device)
    else:
        device.apns_token = payload.apns_token
        device.environment = payload.environment
        device.token_kind = payload.token_kind
        device.user_id = current_user.id
        device.device_identifier = payload.device_identifier
        device.last_seen_at = datetime.now(UTC)
    await db.commit()
    return MessageResponse(message="Device registered")


@router.delete("/me/devices/{device_identifier}", response_model=MessageResponse)
async def unregister_device(
    device_identifier: str,
    current_user: CurrentUser,
    db: DBSession,
) -> MessageResponse:
    result = await db.execute(
        delete(Device).where(
            Device.user_id == current_user.id,
            Device.device_identifier == device_identifier,
        )
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return MessageResponse(message="Device unregistered")


@router.get("/search", response_model=list[UserSummary])
async def search_users(
    current_user: CurrentUser,
    db: DBSession,
    query: str = Query(alias="q", min_length=2, max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
) -> list[UserSummary]:
    escaped = query.strip().replace("%", r"\%").replace("_", r"\_")
    users = (
        await db.scalars(
            select(User)
            .where(
                User.id != current_user.id,
                User.is_active.is_(True),
                or_(
                    User.display_name.ilike(f"%{escaped}%", escape="\\"),
                    User.email.ilike(f"{escaped}%", escape="\\"),
                ),
            )
            .order_by(User.display_name.asc())
            .limit(limit)
        )
    ).all()
    return [UserSummary.model_validate(user) for user in users]
