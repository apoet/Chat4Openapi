import httpx
import pytest

ADMIN = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}


async def admin_login(client: httpx.AsyncClient) -> str:
    assert (await client.post("/api/setup", json=ADMIN)).status_code == 201
    response = await client.post(
        "/api/admin/auth/login",
        json={"username": ADMIN["username"], "password": ADMIN["password"]},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


@pytest.mark.asyncio
async def test_system_admin_can_manage_ordinary_users(client: httpx.AsyncClient) -> None:
    csrf = await admin_login(client)
    created = await client.post(
        "/api/admin/users",
        json={
            "username": "builder",
            "password": "Builder123",
            "locale": "zh-CN",
            "enabled": True,
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert created.status_code == 201
    assert created.json()["role"] == "user"
    assert [user["username"] for user in (await client.get("/api/admin/users")).json()] == [
        "builder"
    ]

    updated = await client.patch(
        f"/api/admin/users/{created.json()['id']}",
        json={"enabled": False},
        headers={"X-CSRF-Token": csrf},
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False


@pytest.mark.asyncio
async def test_ordinary_user_can_build_but_cannot_use_system_domain(
    client: httpx.AsyncClient,
) -> None:
    csrf = await admin_login(client)
    created = await client.post(
        "/api/admin/users",
        json={"username": "builder", "password": "Builder123"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201

    login = await client.post(
        "/api/admin/auth/login",
        json={"username": "builder", "password": "Builder123"},
    )
    assert login.status_code == 200
    assert login.json()["admin"]["role"] == "user"

    assert (await client.get("/api/admin/sources")).status_code == 200
    assert (await client.get("/api/admin/build/providers")).status_code == 200
    forbidden = await client.get("/api/admin/settings")
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "auth.system_admin_required"
    assert (await client.get("/api/admin/providers")).status_code == 403
    assert (await client.get("/api/admin/users")).status_code == 403
