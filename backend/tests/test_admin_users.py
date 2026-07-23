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
            "password_confirm": "Builder123",
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
        json={
            "username": "builder",
            "password": "Builder123",
            "password_confirm": "Builder123",
        },
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
    reset_forbidden = await client.put(
        f"/api/admin/users/{created.json()['id']}/password",
        json={
            "new_password": "EscalatedPass456",
            "new_password_confirm": "EscalatedPass456",
        },
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
    )
    assert reset_forbidden.status_code == 403
    assert reset_forbidden.json()["error"]["code"] == "auth.system_admin_required"


@pytest.mark.asyncio
async def test_creating_user_requires_matching_password_confirmation(
    client: httpx.AsyncClient,
) -> None:
    csrf = await admin_login(client)

    missing = await client.post(
        "/api/admin/users",
        json={"username": "missing", "password": "Builder123"},
        headers={"X-CSRF-Token": csrf},
    )
    mismatch = await client.post(
        "/api/admin/users",
        json={
            "username": "mismatch",
            "password": "Builder123",
            "password_confirm": "Different456",
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert missing.status_code == 422
    assert mismatch.status_code == 422
    assert (await client.get("/api/admin/users")).json() == []


@pytest.mark.asyncio
async def test_system_admin_resets_user_password_and_revokes_user_sessions(
    client: httpx.AsyncClient,
) -> None:
    csrf = await admin_login(client)
    created = await client.post(
        "/api/admin/users",
        json={
            "username": "builder",
            "password": "Builder123",
            "password_confirm": "Builder123",
        },
        headers={"X-CSRF-Token": csrf},
    )
    user_id = created.json()["id"]
    user_login = await client.post(
        "/api/admin/auth/login",
        json={"username": "builder", "password": "Builder123"},
    )
    user_session = client.cookies["chat4openapi_admin_session"]
    admin_login_response = await client.post(
        "/api/admin/auth/login",
        json={"username": ADMIN["username"], "password": ADMIN["password"]},
    )

    reset = await client.put(
        f"/api/admin/users/{user_id}/password",
        json={
            "new_password": "ResetPass456",
            "new_password_confirm": "ResetPass456",
        },
        headers={"X-CSRF-Token": admin_login_response.json()["csrf_token"]},
    )

    assert user_login.status_code == 200
    assert reset.status_code == 204
    client.cookies.set("chat4openapi_admin_session", user_session)
    assert (await client.get("/api/admin/auth/me")).status_code == 401
    assert (
        await client.post(
            "/api/admin/auth/login",
            json={"username": "builder", "password": "Builder123"},
        )
    ).status_code == 401
    assert (
        await client.post(
            "/api/admin/auth/login",
            json={"username": "builder", "password": "ResetPass456"},
        )
    ).status_code == 200
