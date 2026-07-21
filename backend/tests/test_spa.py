from pathlib import Path

import httpx
import pytest

from chat4openapi.main import create_app


@pytest.fixture
def frontend_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text('<div id="app"></div>', encoding="utf-8")
    (assets / "app.js").write_text("console.log('chat4openapi')", encoding="utf-8")
    return dist


@pytest.mark.asyncio
async def test_spa_index_is_served_for_client_routes(frontend_dist: Path) -> None:
    transport = httpx.ASGITransport(app=create_app(frontend_dist=frontend_dist))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin")

    assert response.status_code == 200
    assert '<div id="app"></div>' in response.text


@pytest.mark.asyncio
async def test_spa_assets_are_served_from_the_fixed_asset_mount(frontend_dist: Path) -> None:
    transport = httpx.ASGITransport(app=create_app(frontend_dist=frontend_dist))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/assets/app.js")

    assert response.status_code == 200
    assert response.text == "console.log('chat4openapi')"


@pytest.mark.asyncio
async def test_unknown_api_path_never_falls_back_to_spa(frontend_dist: Path) -> None:
    transport = httpx.ASGITransport(app=create_app(frontend_dist=frontend_dist))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
