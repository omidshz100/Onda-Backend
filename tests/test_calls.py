from httpx import AsyncClient

from tests.helpers import authorization, register_user


async def test_direct_call_accept_join_end_and_history(client: AsyncClient) -> None:
    caller = await register_user(client, email="caller@example.com", display_name="Caller")
    callee = await register_user(client, email="callee@example.com", display_name="Callee")
    caller_headers = authorization(caller["access_token"])
    callee_headers = authorization(callee["access_token"])

    callee_profile = await client.get("/api/v1/users/me", headers=callee_headers)
    direct_call = await client.post(
        "/api/v1/calls",
        headers=caller_headers,
        json={
            "callee_id": callee_profile.json()["id"],
            "title": "Video call",
            "video_enabled": True,
        },
    )
    assert direct_call.status_code == 201, direct_call.text
    call = direct_call.json()
    assert call["status"] == "ringing"
    assert call["title"] == "Video call"
    assert {item["display_name"] for item in call["participants"]} == {"Caller", "Callee"}

    incoming = await client.get("/api/v1/calls/incoming", headers=callee_headers)
    assert incoming.status_code == 200
    assert [item["id"] for item in incoming.json()] == [call["id"]]

    accepted = await client.post(f"/api/v1/calls/{call['id']}/accept", headers=callee_headers)
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "active"

    joined = await client.post(
        f"/api/v1/meetings/{call['meeting_id']}/join",
        headers=callee_headers,
    )
    assert joined.status_code == 200, joined.text
    assert joined.json()["role"] == "participant"

    ended = await client.post(
        f"/api/v1/calls/{call['id']}/end",
        headers=caller_headers,
        json={"reason": "completed"},
    )
    assert ended.status_code == 200
    assert ended.json()["status"] == "ended"

    for headers in (caller_headers, callee_headers):
        history = await client.get("/api/v1/calls/history", headers=headers)
        assert history.status_code == 200
        assert [item["id"] for item in history.json()] == [call["id"]]
