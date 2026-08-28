from httpx import AsyncClient

from tests.helpers import authorization, register_user


async def test_register_profile_and_refresh_rotation(client: AsyncClient) -> None:
    tokens = await register_user(client, email="owner@example.com", display_name="Owner")

    profile = await client.get(
        "/api/v1/users/me",
        headers=authorization(tokens["access_token"]),
    )
    assert profile.status_code == 200
    assert profile.json()["email"] == "owner@example.com"

    refreshed = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != tokens["refresh_token"]

    reused = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert reused.status_code == 401
    assert reused.json()["detail"] == "Refresh token reuse detected"


async def test_duplicate_registration_and_invalid_password(client: AsyncClient) -> None:
    await register_user(client, email="same@example.com", display_name="First User")
    duplicate = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "same@example.com",
            "display_name": "Second User",
            "password": "SecurePassword123",
        },
    )
    weak = await client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "display_name": "Weak", "password": "password"},
    )

    assert duplicate.status_code == 409
    assert weak.status_code == 422
