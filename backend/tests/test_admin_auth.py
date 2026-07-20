from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chatapi.models.admin_session import AdminSession

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
async def test_login_sets_http_only_cookie_and_me_rotates_csrf(
    client: httpx.AsyncClient,
) -> None:
    await initialize(client)

    login = await client.post(
        "/api/admin/auth/login",
        json={"username": "admin", "password": "StrongPass!123"},
    )
    first_csrf = login.json()["csrf_token"]
    me = await client.get("/api/admin/auth/me")

    assert login.status_code == 200
    assert login.json()["admin"] == {"username": "admin", "locale": "en-US"}
    assert first_csrf
    assert "HttpOnly" in login.headers["set-cookie"]
    assert "SameSite=lax" in login.headers["set-cookie"]
    assert me.status_code == 200
    assert me.json()["admin"]["username"] == "admin"
    assert me.json()["csrf_token"] != first_csrf


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
