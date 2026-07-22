import httpx
import pytest

ADMIN = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}


async def _login(client: httpx.AsyncClient) -> str:
    await client.post("/api/setup", json=ADMIN)
    response = await client.post(
        "/api/admin/auth/login",
        json={"username": ADMIN["username"], "password": ADMIN["password"]},
    )
    return response.json()["csrf_token"]


@pytest.mark.asyncio
async def test_admin_can_normalize_update_and_clear_base_url(client: httpx.AsyncClient) -> None:
    csrf = await _login(client)

    initial = await client.get("/api/admin/settings")
    updated = await client.put(
        "/api/admin/settings",
        json={"base_url": "https://Chat.Example/app/"},
        headers={"X-CSRF-Token": csrf},
    )
    cleared = await client.put(
        "/api/admin/settings",
        json={"base_url": None},
        headers={"X-CSRF-Token": csrf},
    )

    assert initial.status_code == 200
    assert initial.json()["base_url"] is None
    assert updated.json()["base_url"] == "https://chat.example/app"
    assert cleared.json()["base_url"] is None


@pytest.mark.asyncio
async def test_base_url_accepts_non_loopback_http(client: httpx.AsyncClient) -> None:
    csrf = await _login(client)

    response = await client.put(
        "/api/admin/settings",
        json={"base_url": "http://chat.example"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 200
    assert response.json()["base_url"] == "http://chat.example"


@pytest.mark.asyncio
async def test_settings_require_login_and_csrf(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/admin/settings")).status_code == 401
    await _login(client)
    response = await client.put("/api/admin/settings", json={"base_url": None})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.csrf_invalid"
