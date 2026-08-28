from httpx import AsyncClient


async def test_health_endpoints(client: AsyncClient) -> None:
    live = await client.get("/api/v1/health/live")
    ready = await client.get("/api/v1/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "ok", "api_version": "v1"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "api_version": "v1"}
    assert live.headers["x-content-type-options"] == "nosniff"
    assert live.headers["x-request-id"]
