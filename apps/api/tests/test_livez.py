import httpx

from origin_api.app import create_app
from origin_core.settings import Settings


async def test_livez() -> None:
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    transport = httpx.ASGITransport(app=create_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/livez")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
