from httpx import AsyncClient

from tests.helpers import authorization, register_user


async def test_user_search_and_device_lifecycle(client: AsyncClient) -> None:
    owner = await register_user(client, email="owner@example.com", display_name="Owner")
    await register_user(client, email="friend@example.com", display_name="Friendly Person")
    headers = authorization(owner["access_token"])

    search = await client.get("/api/v1/users/search?q=friend", headers=headers)
    assert search.status_code == 200
    assert search.json()[0]["display_name"] == "Friendly Person"
    assert "email" not in search.json()[0]

    registered = await client.put(
        "/api/v1/users/me/devices",
        headers=headers,
        json={
            "device_identifier": "test-device-001",
            "apns_token": "a" * 64,
            "environment": "sandbox",
            "token_kind": "voip",
        },
    )
    assert registered.status_code == 200

    removed = await client.delete(
        "/api/v1/users/me/devices/test-device-001",
        headers=headers,
    )
    assert removed.status_code == 200
