from typing import Any

from httpx import AsyncClient


async def register_user(
    client: AsyncClient,
    *,
    email: str,
    display_name: str,
    password: str = "SecurePassword123",
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "display_name": display_name, "password": password},
    )
    assert response.status_code == 201, response.text
    return response.json()


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
