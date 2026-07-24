from datetime import UTC, datetime, timedelta
import os

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.config import Settings, get_settings
from chat4openapi.models.admin_session import AdminSession

ADMIN_PAYLOAD = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}


async def initialize(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/setup", json=ADMIN_PAYLOAD)
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_login_rejects_invalid_credentials(client: httpx.AsyncClient) -> None:
    await initialize(client)

    response = await client.post(
        "/api/admin/auth/login", json={"username": "admin", "password": "wrong-password"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.invalid_credentials"


@pytest.mark.asyncio
async def test_login_and_me_share_stable_csrf_across_browser_tabs(
    client: httpx.AsyncClient,
) -> None:
    await initialize(client)

    login = await client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "StrongPass!123"},
    )
    first_csrf = login.json()["csrf_token"]
    first_tab = await client.get("/api/admin/auth/me")
    second_tab = await client.get("/api/admin/auth/me")
    logout = await client.post(
        "/api/admin/auth/logout",
        headers={"X-CSRF-Token": first_csrf},
    )

    assert login.status_code == 200
    assert login.json()["admin"] == {
        "username": "admin",
        "locale": "en-US",
        "role": "admin",
    }
    assert first_csrf
    assert "HttpOnly" in login.headers["set-cookie"]
    assert "SameSite=lax" in login.headers["set-cookie"]
    assert first_tab.status_code == 200
    assert first_tab.json()["admin"]["username"] == "admin"
    assert first_tab.json()["csrf_token"] == first_csrf
    assert second_tab.json()["csrf_token"] == first_csrf
    assert logout.status_code == 204


@pytest.mark.asyncio
async def test_logout_requires_the_current_csrf_token(client: httpx.AsyncClient) -> None:
    await initialize(client)
    login = await client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "StrongPass!123"},
    )

    missing = await client.post("/api/admin/auth/logout")
    valid = await client.post(
        "/api/admin/auth/logout",
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
    )
    me = await client.get("/api/admin/auth/me")

    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "auth.csrf_invalid"
    assert valid.status_code == 204
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_me_rejects_an_expired_session(
    client: httpx.AsyncClient, db_session_factory: sessionmaker[Session]
) -> None:
    await initialize(client)
    await client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "StrongPass!123"},
    )
    past = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    with db_session_factory() as session:
        admin_session = session.scalar(select(AdminSession))
        assert admin_session is not None
        admin_session.idle_expires_at = past
        session.commit()

    response = await client.get("/api/admin/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.session_expired"


@pytest.mark.asyncio
async def test_signed_in_user_changes_password_and_all_sessions_are_revoked(
    client: httpx.AsyncClient,
) -> None:
    await initialize(client)
    first = await client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "StrongPass!123"},
    )
    csrf = first.json()["csrf_token"]

    wrong_current = await client.put(
        "/api/admin/auth/password",
        headers={"X-CSRF-Token": csrf},
        json={
            "current_password": "WrongPass123",
            "new_password": "ChangedPass456",
            "new_password_confirm": "ChangedPass456",
        },
    )
    assert wrong_current.status_code == 400
    assert wrong_current.json()["error"]["code"] == "auth.current_password_invalid"

    changed = await client.put(
        "/api/admin/auth/password",
        headers={"X-CSRF-Token": csrf},
        json={
            "current_password": "StrongPass!123",
            "new_password": "ChangedPass456",
            "new_password_confirm": "ChangedPass456",
        },
    )
    assert changed.status_code == 204
    assert (await client.get("/api/admin/auth/me")).status_code == 401
    assert (
        await client.post(
            "/api/admin/auth/login",
            json={"username": "admin", "password": "StrongPass!123"},
        )
    ).status_code == 401
    assert (
        await client.post(
            "/api/admin/auth/login",
            json={"username": "admin", "password": "ChangedPass456"},
        )
    ).status_code == 200


@pytest.mark.asyncio
async def test_admin_password_reset_uses_a_private_one_time_file_credential(
    client: httpx.AsyncClient, app, tmp_path
) -> None:
    reset_dir = tmp_path / "private-password-reset"
    settings = Settings(
        admin_password_reset_dir=reset_dir,
        admin_password_reset_minutes=15,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    await initialize(client)

    requested = await client.post("/api/admin/auth/password-reset/request")

    assert requested.status_code == 201
    credential_path = reset_dir / "admin-password-reset.key"
    assert requested.json()["credential_path"] == str(credential_path.resolve())
    assert "key" not in requested.json()
    assert credential_path.is_file()
    reset_key = credential_path.read_text(encoding="utf-8").strip()
    assert len(reset_key) >= 32
    repeated = await client.post("/api/admin/auth/password-reset/request")
    assert repeated.status_code == 201
    assert credential_path.read_text(encoding="utf-8").strip() == reset_key
    assert repeated.json()["expires_at"] == requested.json()["expires_at"]

    invalid = await client.post(
        "/api/admin/auth/password-reset/complete",
        json={
            "key": "invalid-reset-key",
            "new_password": "RecoveredPass456",
            "new_password_confirm": "RecoveredPass456",
        },
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "auth.reset_key_invalid"
    assert credential_path.is_file()

    mismatch = await client.post(
        "/api/admin/auth/password-reset/complete",
        json={
            "key": reset_key,
            "new_password": "RecoveredPass456",
            "new_password_confirm": "DifferentPass789",
        },
    )
    assert mismatch.status_code == 422
    assert credential_path.is_file()

    completed = await client.post(
        "/api/admin/auth/password-reset/complete",
        json={
            "key": reset_key,
            "new_password": "RecoveredPass456",
            "new_password_confirm": "RecoveredPass456",
        },
    )
    assert completed.status_code == 204
    assert not credential_path.exists()
    assert (
        await client.post(
            "/api/admin/auth/login",
            json={"username": "admin", "password": "StrongPass!123"},
        )
    ).status_code == 401
    assert (
        await client.post(
            "/api/admin/auth/login",
            json={"username": "admin", "password": "RecoveredPass456"},
        )
    ).status_code == 200

    replay = await client.post(
        "/api/admin/auth/password-reset/complete",
        json={
            "key": reset_key,
            "new_password": "ReplayPass789",
            "new_password_confirm": "ReplayPass789",
        },
    )
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "auth.reset_key_invalid"

    assert (
        await client.post("/api/admin/auth/password-reset/request")
    ).status_code == 201
    expired_key = credential_path.read_text(encoding="utf-8").strip()
    expired_timestamp = (
        datetime.now(UTC) - timedelta(minutes=16)
    ).timestamp()
    os.utime(credential_path, (expired_timestamp, expired_timestamp))
    expired = await client.post(
        "/api/admin/auth/password-reset/complete",
        json={
            "key": expired_key,
            "new_password": "ExpiredPass789",
            "new_password_confirm": "ExpiredPass789",
        },
    )
    assert expired.status_code == 400
    assert expired.json()["error"]["code"] == "auth.reset_key_expired"
    assert not credential_path.exists()
