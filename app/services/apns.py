import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import jwt

from app.core.config import Settings
from app.models.user import Device, DeviceTokenKind, User

logger = logging.getLogger("onda.apns")


def _provider_token(settings: Settings) -> str | None:
    if not all(
        [
            settings.apns_key_id,
            settings.apns_team_id,
            settings.apns_bundle_id,
            settings.apns_private_key,
        ]
    ):
        return None
    now = datetime.now(UTC)
    return jwt.encode(
        {"iss": settings.apns_team_id, "iat": int(now.timestamp())},
        settings.apns_private_key.replace(r"\n", "\n"),
        algorithm="ES256",
        headers={"kid": settings.apns_key_id},
    )


async def send_incoming_call(
    *,
    devices: list[Device],
    call_id: UUID,
    meeting_id: UUID,
    caller: User,
    video_enabled: bool,
    settings: Settings,
) -> None:
    provider_token = _provider_token(settings)
    if provider_token is None or not devices:
        return

    async with httpx.AsyncClient(http2=True, timeout=10) as client:
        await asyncio.gather(
            *[
                _send_to_device(
                    client=client,
                    device=device,
                    provider_token=provider_token,
                    call_id=call_id,
                    meeting_id=meeting_id,
                    caller=caller,
                    video_enabled=video_enabled,
                    settings=settings,
                )
                for device in devices
            ]
        )


async def send_chat_message(
    *,
    devices: list[Device],
    message_id: UUID,
    conversation_id: UUID,
    sender: User,
    body: str,
    settings: Settings,
) -> None:
    provider_token = _provider_token(settings)
    standard_devices = [
        device for device in devices if device.token_kind == DeviceTokenKind.standard
    ]
    if provider_token is None or not standard_devices:
        return

    async with httpx.AsyncClient(http2=True, timeout=10) as client:
        await asyncio.gather(
            *[
                _send_chat_to_device(
                    client=client,
                    device=device,
                    provider_token=provider_token,
                    message_id=message_id,
                    conversation_id=conversation_id,
                    sender=sender,
                    body=body,
                    settings=settings,
                )
                for device in standard_devices
            ]
        )


async def _send_chat_to_device(
    *,
    client: httpx.AsyncClient,
    device: Device,
    provider_token: str,
    message_id: UUID,
    conversation_id: UUID,
    sender: User,
    body: str,
    settings: Settings,
) -> None:
    host = (
        "https://api.sandbox.push.apple.com"
        if device.environment == "sandbox"
        else "https://api.push.apple.com"
    )
    payload = {
        "aps": {
            "alert": {"title": sender.display_name, "body": body[:160]},
            "sound": "default",
            "thread-id": str(conversation_id),
        },
        "event": "chat_message",
        "message_id": str(message_id),
        "conversation_id": str(conversation_id),
        "sender_id": str(sender.id),
        "sender_name": sender.display_name,
    }
    try:
        response = await client.post(
            f"{host}/3/device/{device.apns_token}",
            headers={
                "authorization": f"bearer {provider_token}",
                "apns-topic": settings.apns_bundle_id or "",
                "apns-push-type": "alert",
                "apns-priority": "10",
                "apns-collapse-id": str(conversation_id),
            },
            json=payload,
        )
        if response.status_code != 200:
            logger.warning(
                "apns_chat_delivery_failed device_id=%s status=%s reason=%s",
                device.id,
                response.status_code,
                response.text[:256],
            )
    except httpx.HTTPError:
        logger.exception("apns_chat_delivery_error device_id=%s", device.id)


async def _send_to_device(
    *,
    client: httpx.AsyncClient,
    device: Device,
    provider_token: str,
    call_id: UUID,
    meeting_id: UUID,
    caller: User,
    video_enabled: bool,
    settings: Settings,
) -> None:
    is_voip = device.token_kind == DeviceTokenKind.voip
    host = (
        "https://api.sandbox.push.apple.com"
        if device.environment == "sandbox"
        else "https://api.push.apple.com"
    )
    topic = f"{settings.apns_bundle_id}.voip" if is_voip else settings.apns_bundle_id
    aps: dict[str, Any] = {"content-available": 1}
    if not is_voip:
        aps.update(
            {
                "alert": {
                    "title": "Incoming video call" if video_enabled else "Incoming audio call",
                    "body": caller.display_name,
                },
                "sound": "default",
            }
        )
    payload = {
        "aps": aps,
        "event": "incoming_call",
        "call_id": str(call_id),
        "meeting_id": str(meeting_id),
        "caller_id": str(caller.id),
        "caller_name": caller.display_name,
        "video_enabled": video_enabled,
        "expires_at": int((datetime.now(UTC) + timedelta(seconds=45)).timestamp()),
    }
    try:
        response = await client.post(
            f"{host}/3/device/{device.apns_token}",
            headers={
                "authorization": f"bearer {provider_token}",
                "apns-topic": topic or "",
                "apns-push-type": "voip" if is_voip else "alert",
                "apns-priority": "10",
                "apns-expiration": "0",
            },
            json=payload,
        )
        if response.status_code != 200:
            logger.warning(
                "apns_delivery_failed device_id=%s status=%s reason=%s",
                device.id,
                response.status_code,
                response.text[:256],
            )
    except httpx.HTTPError:
        logger.exception("apns_delivery_error device_id=%s", device.id)
