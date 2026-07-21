import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chatapi.models.admin import AdminUser
from chatapi.models.app_setting import AppSetting
from chatapi.security.passwords import verify_password


@pytest.mark.asyncio
async def test_setup_status_is_false_before_initialization(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/setup/status")

    assert response.status_code == 200
    assert response.json() == {"initialized": False, "locale": None}


@pytest.mark.asyncio
async def test_setup_creates_only_one_admin(client: httpx.AsyncClient) -> None:
    payload = {"username": "admin", "password": "StrongPass!123", "locale": "zh-CN"}

    first = await client.post("/api/setup", json=payload)
    second = await client.post("/api/setup", json=payload)

    assert first.status_code == 201
    assert first.json() == {"initialized": True, "locale": "zh-CN"}
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "setup.already_initialized"


@pytest.mark.asyncio
async def test_setup_rejects_weak_password(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/setup",
        json={"username": "admin", "password": "short", "locale": "en-US"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation.invalid"


@pytest.mark.asyncio
async def test_setup_accepts_six_character_letter_number_password(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/setup",
        json={"username": "admin", "password": "abc123", "locale": "en-US"},
    )

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_setup_reuses_settings_when_administrator_was_reset(
    client: httpx.AsyncClient, db_session_factory: sessionmaker[Session]
) -> None:
    with db_session_factory() as session:
        session.add(
            AppSetting(id=1, default_locale="zh-CN", tool_login_enabled=True)
        )
        session.commit()

    response = await client.post(
        "/api/setup",
        json={"username": "admin", "password": "abc123", "locale": "en-US"},
    )

    assert response.status_code == 201
    with db_session_factory() as session:
        settings = session.get(AppSetting, 1)
    assert settings is not None
    assert settings.default_locale == "en-US"
    assert settings.tool_login_enabled is True


@pytest.mark.asyncio
@pytest.mark.parametrize("password", ["abcdef", "123456"])
async def test_setup_requires_both_letters_and_numbers(
    client: httpx.AsyncClient, password: str
) -> None:
    response = await client.post(
        "/api/setup",
        json={"username": "admin", "password": password, "locale": "en-US"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation.invalid"


@pytest.mark.asyncio
async def test_setup_hashes_the_admin_password(
    client: httpx.AsyncClient, db_session_factory: sessionmaker[Session]
) -> None:
    password = "StrongPass!123"
    await client.post(
        "/api/setup",
        json={"username": "admin", "password": password, "locale": "en-US"},
    )

    with db_session_factory() as session:
        admin = session.scalar(select(AdminUser))

    assert admin is not None
    assert admin.password_hash != password
    assert verify_password(password, admin.password_hash)
