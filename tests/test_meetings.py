from datetime import UTC, datetime, timedelta

import jwt
from httpx import AsyncClient

from tests.helpers import authorization, register_user


async def test_group_meeting_flow_issues_room_scoped_jitsi_tokens(client: AsyncClient) -> None:
    owner = await register_user(client, email="owner@example.com", display_name="Owner")
    guest = await register_user(client, email="guest@example.com", display_name="Guest")
    owner_headers = authorization(owner["access_token"])
    guest_headers = authorization(guest["access_token"])

    created = await client.post(
        "/api/v1/meetings",
        headers=owner_headers,
        json={
            "title": "Product sync",
            "starts_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            "max_participants": 10,
            "configuration": {
                "uses_waiting_room": True,
                "is_microphone_enabled": True,
                "is_camera_enabled": True,
                "is_speaker_enabled": True,
            },
        },
    )
    assert created.status_code == 201, created.text
    meeting = created.json()

    resolved = await client.post(
        "/api/v1/meetings/resolve",
        headers=guest_headers,
        json={"code_or_link": f"https://onda.example/join/{meeting['code']}"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["participant_count"] == 2

    start = await client.post(f"/api/v1/meetings/{meeting['id']}/start", headers=owner_headers)
    assert start.status_code == 200
    assert start.json()["status"] == "active"

    waiting_join = await client.post(
        f"/api/v1/meetings/{meeting['id']}/join", headers=guest_headers
    )
    assert waiting_join.status_code == 403
    assert waiting_join.json()["detail"] == "Waiting for host approval"

    guest_profile = await client.get("/api/v1/users/me", headers=guest_headers)
    admitted = await client.post(
        f"/api/v1/meetings/{meeting['id']}/participants/{guest_profile.json()['id']}/admit",
        headers=owner_headers,
    )
    assert admitted.status_code == 200
    assert admitted.json()["is_admitted"] is True

    owner_join = await client.post(f"/api/v1/meetings/{meeting['id']}/join", headers=owner_headers)
    guest_join = await client.post(f"/api/v1/meetings/{meeting['id']}/join", headers=guest_headers)
    assert owner_join.status_code == 200, owner_join.text
    assert guest_join.status_code == 200, guest_join.text

    owner_claims = jwt.decode(
        owner_join.json()["token"],
        "test-jitsi-secret-that-is-long-enough",
        algorithms=["HS256"],
        audience="onda",
    )
    guest_claims = jwt.decode(
        guest_join.json()["token"],
        "test-jitsi-secret-that-is-long-enough",
        algorithms=["HS256"],
        audience="onda",
    )
    assert owner_claims["room"] == owner_join.json()["room_name"]
    assert owner_claims["context"]["user"]["moderator"] is True
    assert owner_claims["context"]["user"]["affiliation"] == "owner"
    assert guest_claims["context"]["user"]["moderator"] is False
    assert guest_claims["context"]["user"]["affiliation"] == "member"

    forbidden = await client.post(f"/api/v1/meetings/{meeting['id']}/end", headers=guest_headers)
    assert forbidden.status_code == 403
    ended = await client.post(f"/api/v1/meetings/{meeting['id']}/end", headers=owner_headers)
    assert ended.status_code == 200
    assert ended.json()["status"] == "ended"
