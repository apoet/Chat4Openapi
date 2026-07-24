# Platform Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable Chat4Openapi foundation with SQLite migrations, first-run single-admin setup, secure admin sessions, English/Chinese localization, and a Vue initialization/login shell.

**Architecture:** A FastAPI application under `backend/` owns configuration, SQLAlchemy persistence, setup and admin authentication APIs. A Vue 3 application under `frontend/` calls those APIs and guards routes using setup and login state. This phase deliberately excludes API import, Tool Session, Skills, chat execution, and compatibility endpoints; later phases build on the interfaces defined here.

**Tech Stack:** Python 3.12 managed by conda, FastAPI, SQLAlchemy 2, Alembic, Pydantic Settings, pwdlib with Argon2, pytest, Vue 3, TypeScript, Vite, Pinia, Vue Router, vue-i18n, Element Plus, Vitest, Playwright, Node.js managed by nvm.

## Global Constraints

- The application is single-instance and has exactly one backend administrator.
- SQLite uses foreign keys, WAL mode, and a busy timeout.
- Backend and frontend support `en-US` and `zh-CN`; default locale is `en-US`.
- Administrator cookies are HttpOnly and SameSite=Lax; state-changing requests require CSRF validation.
- Passwords use Argon2id and are never logged or returned.
- `fastmcp==3.4.4` is pinned now so later phases do not change the dependency baseline.
- Node.js is selected through nvm; Python runs from the conda environment named `chat4openapi`.
- API errors use stable codes plus interpolation parameters; frontend code owns translated user-facing text.

---

## Planned File Structure

```text
Chat4Openapi/
├── environment.yml                     # conda environment entrypoint
├── backend/
│   ├── pyproject.toml                  # backend dependencies and tool configuration
│   ├── alembic.ini
│   ├── migrations/
│   │   ├── env.py
│   │   └── versions/0001_foundation.py
│   ├── src/chat4openapi/
│   │   ├── main.py                     # application factory and router mounting
│   │   ├── config.py                   # validated environment settings
│   │   ├── api/errors.py               # stable API error envelope
│   │   ├── api/health.py               # liveness/readiness API
│   │   ├── api/setup.py                # initialization status and bootstrap API
│   │   ├── api/admin_auth.py           # login/logout/me API
│   │   ├── db/base.py                  # declarative base and model imports
│   │   ├── db/session.py               # engine/session and SQLite pragmas
│   │   ├── models/admin.py             # single admin row
│   │   ├── models/admin_session.py     # hashed server-side sessions
│   │   ├── models/app_setting.py       # singleton application settings
│   │   ├── schemas/setup.py
│   │   ├── schemas/auth.py
│   │   ├── security/passwords.py       # Argon2id hashing
│   │   ├── security/session_tokens.py  # opaque token generation and hashing
│   │   └── services/admin_auth.py      # setup and authentication transactions
│   └── tests/
│       ├── conftest.py
│       ├── test_health.py
│       ├── test_setup.py
│       └── test_admin_auth.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── vitest.config.ts
    ├── src/
    │   ├── main.ts
    │   ├── App.vue
    │   ├── api/client.ts
    │   ├── api/contracts.ts
    │   ├── i18n/index.ts
    │   ├── i18n/en-US.ts
    │   ├── i18n/zh-CN.ts
    │   ├── router/index.ts
    │   ├── stores/auth.ts
    │   ├── layouts/AdminLayout.vue
    │   ├── views/SetupView.vue
    │   ├── views/LoginView.vue
    │   └── views/OverviewView.vue
    └── src/__tests__/
        ├── setup-view.spec.ts
        └── router-guards.spec.ts
```

### Task 1: Backend Application and Health Contract

**Files:**
- Create: `environment.yml`
- Create: `backend/pyproject.toml`
- Create: `backend/src/chat4openapi/__init__.py`
- Create: `backend/src/chat4openapi/config.py`
- Create: `backend/src/chat4openapi/main.py`
- Create: `backend/src/chat4openapi/api/__init__.py`
- Create: `backend/src/chat4openapi/api/health.py`
- Create: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: environment variables prefixed with `CHAT4OPENAPI_`.
- Produces: `chat4openapi.main:create_app() -> FastAPI`, `GET /health -> {"status":"ok"}` and `Settings.database_url`.

- [ ] **Step 1: Add the environment and Python package metadata**

```yaml
# environment.yml
name: agent4api
channels:
  - conda-forge
dependencies:
  - python=3.12
  - pip
  - pip:
      - -e ./backend[dev]
```

```toml
# backend/pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "chat4openapi"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "alembic>=1.16,<2",
  "fastapi>=0.116,<1",
  "fastmcp==3.4.4",
  "httpx>=0.28,<1",
  "openapi-spec-validator>=0.8,<1",
  "pydantic-settings>=2.10,<3",
  "pwdlib[argon2]>=0.2,<1",
  "sqlalchemy>=2.0,<3",
  "uvicorn[standard]>=0.35,<1",
]

[project.optional-dependencies]
dev = ["pytest>=8.4,<9", "pytest-asyncio>=1.1,<2", "ruff>=0.12,<1"]

[tool.hatch.build.targets.wheel]
packages = ["src/chat4openapi"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 2: Write the failing health test**

```python
from fastapi.testclient import TestClient

from chat4openapi.main import create_app


def test_health_returns_ok() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 3: Create the conda environment and confirm the application does not exist**

Run: `conda env create -f environment.yml && conda run -n agent4api pip install -e "backend[dev]" && conda run -n agent4api pytest backend/tests/test_health.py -q`

Expected: FAIL during collection because `chat4openapi.main` has not been created.

- [ ] **Step 4: Implement configuration, health router, and app factory**

```python
# backend/src/chat4openapi/config.py
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHAT4OPENAPI_", extra="ignore")

    database_url: str = f"sqlite:///{Path('data/chat4openapi.db').as_posix()}"
    default_locale: str = "en-US"
    admin_session_idle_minutes: int = 30
    admin_session_absolute_hours: int = 8
    secure_cookies: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

```python
# backend/src/chat4openapi/api/health.py
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

```python
# backend/src/chat4openapi/main.py
from fastapi import FastAPI

from chat4openapi.api.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="Chat4Openapi", version="0.1.0")
    app.include_router(health_router)
    return app


app = create_app()
```

- [ ] **Step 5: Run backend checks**

Run: `conda run -n agent4api pytest backend/tests/test_health.py -q && conda run -n agent4api ruff check backend`

Expected: one passing test and `All checks passed!`.

- [ ] **Step 6: Commit the backend skeleton**

```powershell
git add environment.yml backend
git commit -m "feat: scaffold backend application"
```

### Task 2: SQLite Foundation and Initial Migration

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/versions/0001_foundation.py`
- Create: `backend/src/chat4openapi/db/__init__.py`
- Create: `backend/src/chat4openapi/db/base.py`
- Create: `backend/src/chat4openapi/db/session.py`
- Create: `backend/src/chat4openapi/models/__init__.py`
- Create: `backend/src/chat4openapi/models/admin.py`
- Create: `backend/src/chat4openapi/models/admin_session.py`
- Create: `backend/src/chat4openapi/models/app_setting.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_database.py`

**Interfaces:**
- Consumes: `Settings.database_url`.
- Produces: `Base`, `create_engine_for_url(url)`, `session_scope()`, and tables `admin_users`, `admin_sessions`, `app_settings`.

- [ ] **Step 1: Write failing SQLite pragma and schema tests**

```python
from sqlalchemy import text


def test_sqlite_enables_foreign_keys_and_wal(db_engine) -> None:
    with db_engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"


def test_foundation_tables_exist(db_engine) -> None:
    with db_engine.connect() as connection:
        names = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
    assert {"admin_users", "admin_sessions", "app_settings"} <= names
```

- [ ] **Step 2: Run tests and confirm missing fixtures/models**

Run: `conda run -n agent4api pytest backend/tests/test_database.py -q`

Expected: FAIL because `db_engine` is unavailable.

- [ ] **Step 3: Implement the database engine contract**

```python
# backend/src/chat4openapi/db/session.py
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.config import get_settings


def create_engine_for_url(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


engine = create_engine_for_url(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 4: Add typed models and the initial Alembic migration**

```python
# backend/src/chat4openapi/models/admin.py
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from chat4openapi.db.base import Base


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (CheckConstraint("id = 1", name="ck_single_admin"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    username: Mapped[str] = mapped_column(String(128), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    locale: Mapped[str] = mapped_column(String(16), default="en-US")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

```python
# backend/src/chat4openapi/models/admin_session.py
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from chat4openapi.db.base import Base


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

```python
# backend/src/chat4openapi/models/app_setting.py
from sqlalchemy import Boolean, CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from chat4openapi.db.base import Base


class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_single_app_setting"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    default_locale: Mapped[str] = mapped_column(String(16), default="en-US")
    tool_login_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
```

```python
# backend/src/chat4openapi/db/base.py
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from chat4openapi.models.admin import AdminUser  # noqa: E402,F401
from chat4openapi.models.admin_session import AdminSession  # noqa: E402,F401
from chat4openapi.models.app_setting import AppSetting  # noqa: E402,F401
```

```python
# backend/migrations/versions/0001_foundation.py (upgrade body)
op.create_table(
    "admin_users",
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("username", sa.String(128), nullable=False, unique=True),
    sa.Column("password_hash", sa.String(512), nullable=False),
    sa.Column("locale", sa.String(16), nullable=False, server_default="en-US"),
    sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint("id = 1", name="ck_single_admin"),
)
op.create_table(
    "admin_sessions",
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("admin_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="CASCADE")),
    sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
    sa.Column("csrf_hash", sa.String(64), nullable=False),
    sa.Column("idle_expires_at", sa.DateTime(), nullable=False),
    sa.Column("absolute_expires_at", sa.DateTime(), nullable=False),
    sa.Column("revoked_at", sa.DateTime(), nullable=True),
)
op.create_index("ix_admin_sessions_token_hash", "admin_sessions", ["token_hash"])
op.create_table(
    "app_settings",
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("default_locale", sa.String(16), nullable=False, server_default="en-US"),
    sa.Column("tool_login_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.CheckConstraint("id = 1", name="ck_single_app_setting"),
)
```

`downgrade()` drops `app_settings`, `admin_sessions`, then `admin_users`. `backend/migrations/env.py` sets `target_metadata = Base.metadata` and chooses offline or online Alembic execution using `config.get_main_option("sqlalchemy.url")`.

- [ ] **Step 5: Add isolated migrated-database fixtures and pass tests**

```python
# backend/tests/conftest.py
import pytest
from alembic import command
from alembic.config import Config

from chat4openapi.db.session import create_engine_for_url


@pytest.fixture
def database_url(tmp_path) -> str:
    return f"sqlite:///{(tmp_path / 'test.db').as_posix()}"


@pytest.fixture
def db_engine(database_url, monkeypatch):
    monkeypatch.setenv("CHAT4OPENAPI_DATABASE_URL", database_url)
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_engine_for_url(database_url)
    yield engine
    engine.dispose()
```

Run: `conda run -n agent4api pytest backend/tests/test_database.py -q`

Expected: two passing tests.

- [ ] **Step 6: Commit the persistence foundation**

```powershell
git add backend/alembic.ini backend/migrations backend/src/chat4openapi/db backend/src/chat4openapi/models backend/tests
git commit -m "feat: add SQLite persistence foundation"
```

### Task 3: First-Run Administrator Setup

**Files:**
- Create: `backend/src/chat4openapi/api/errors.py`
- Create: `backend/src/chat4openapi/api/setup.py`
- Create: `backend/src/chat4openapi/schemas/setup.py`
- Create: `backend/src/chat4openapi/security/passwords.py`
- Create: `backend/src/chat4openapi/services/admin_auth.py`
- Modify: `backend/src/chat4openapi/main.py`
- Test: `backend/tests/test_setup.py`

**Interfaces:**
- Consumes: database `Session`, `AdminUser`, `AppSetting`.
- Produces: `GET /api/setup/status`, `POST /api/setup`, `hash_password()`, `verify_password()`, `initialize_admin()`.

- [ ] **Step 1: Write setup contract tests**

```python
def test_setup_status_is_false_before_initialization(client) -> None:
    assert client.get("/api/setup/status").json() == {"initialized": False}


def test_setup_creates_only_one_admin(client) -> None:
    payload = {"username": "admin", "password": "StrongPass!123", "locale": "zh-CN"}
    first = client.post("/api/setup", json=payload)
    second = client.post("/api/setup", json=payload)

    assert first.status_code == 201
    assert first.json() == {"initialized": True, "locale": "zh-CN"}
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "setup.already_initialized"


def test_setup_rejects_weak_password(client) -> None:
    response = client.post(
        "/api/setup", json={"username": "admin", "password": "short", "locale": "en-US"}
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run setup tests and confirm 404 responses**

Run: `conda run -n agent4api pytest backend/tests/test_setup.py -q`

Expected: FAIL because `/api/setup` routes do not exist.

- [ ] **Step 3: Implement password and setup service contracts**

```python
# backend/src/chat4openapi/security/passwords.py
from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)
```

```python
# backend/src/chat4openapi/schemas/setup.py
from pydantic import BaseModel, Field


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)
    locale: str = Field(pattern=r"^(en-US|zh-CN)$")


class SetupStatus(BaseModel):
    initialized: bool
    locale: str | None = None
```

`initialize_admin(session, request)` starts an immediate SQLite transaction, rejects any existing `AdminUser`, writes `AdminUser(id=1, ...)` and `AppSetting(id=1, default_locale=request.locale)`, and returns `SetupStatus(initialized=True, locale=request.locale)`.

- [ ] **Step 4: Implement setup API with stable error envelope**

```python
# backend/src/chat4openapi/api/errors.py
from typing import Any

from fastapi import HTTPException


def api_error(status_code: int, code: str, **params: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": {"code": code, "params": params}})
```

The application installs an `HTTPException` handler that returns `exc.detail` unchanged. `GET /api/setup/status` checks for `AdminUser.id == 1`; `POST /api/setup` calls `initialize_admin` and maps the duplicate-admin condition to HTTP 409 with `setup.already_initialized`.

- [ ] **Step 5: Run setup and password tests**

Run: `conda run -n agent4api pytest backend/tests/test_setup.py -q`

Expected: three passing tests, and a database assertion confirms the stored password is an Argon2 hash rather than plaintext.

- [ ] **Step 6: Commit first-run setup**

```powershell
git add backend/src/chat4openapi backend/tests/test_setup.py
git commit -m "feat: add first-run administrator setup"
```

### Task 4: Secure Administrator Sessions

**Files:**
- Create: `backend/src/chat4openapi/api/admin_auth.py`
- Create: `backend/src/chat4openapi/schemas/auth.py`
- Create: `backend/src/chat4openapi/security/session_tokens.py`
- Modify: `backend/src/chat4openapi/services/admin_auth.py`
- Modify: `backend/src/chat4openapi/main.py`
- Test: `backend/tests/test_admin_auth.py`

**Interfaces:**
- Consumes: initialized `AdminUser` and `AdminSession` table.
- Produces: `POST /api/admin/auth/login`, `POST /api/admin/auth/logout`, `GET /api/admin/auth/me`, `require_admin()`.

- [ ] **Step 1: Write failing login, CSRF, and expiry tests**

```python
def test_login_sets_http_only_cookie_and_returns_csrf(initialized_client) -> None:
    response = initialized_client.post(
        "/api/admin/auth/login", json={"username": "admin", "password": "StrongPass!123"}
    )
    assert response.status_code == 200
    assert response.json()["admin"]["username"] == "admin"
    assert response.json()["csrf_token"]
    assert "HttpOnly" in response.headers["set-cookie"]


def test_logout_requires_csrf(initialized_client) -> None:
    login = initialized_client.post(
        "/api/admin/auth/login", json={"username": "admin", "password": "StrongPass!123"}
    )
    response = initialized_client.post("/api/admin/auth/logout")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.csrf_invalid"


def test_me_rejects_expired_session(initialized_client, expire_admin_sessions) -> None:
    initialized_client.post(
        "/api/admin/auth/login", json={"username": "admin", "password": "StrongPass!123"}
    )
    expire_admin_sessions()
    assert initialized_client.get("/api/admin/auth/me").status_code == 401
```

- [ ] **Step 2: Run auth tests and confirm missing routes**

Run: `conda run -n agent4api pytest backend/tests/test_admin_auth.py -q`

Expected: FAIL with 404 responses.

- [ ] **Step 3: Implement opaque token primitives**

```python
# backend/src/chat4openapi/security/session_tokens.py
import hashlib
import secrets


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Implement login and authenticated dependency**

`authenticate_admin(session, username, password, now)` verifies the single enabled admin, creates independent opaque session and CSRF tokens, stores only SHA-256 hashes, and sets idle and absolute expiry from `Settings`. `require_admin` hashes the `chat4openapi_admin_session` cookie, rejects revoked/expired rows, and advances idle expiry without exceeding absolute expiry. `require_csrf` compares the hash of `X-CSRF-Token` with the stored CSRF hash using `secrets.compare_digest`.

The login response sets `chat4openapi_admin_session` with `httponly=True`, `samesite="lax"`, `secure=settings.secure_cookies`, and `path="/"`. Logout requires both dependencies, marks the row revoked, and deletes the cookie.

- [ ] **Step 5: Run the complete backend suite**

Run: `conda run -n agent4api pytest backend/tests -q && conda run -n agent4api ruff check backend`

Expected: all tests pass and Ruff reports no violations.

- [ ] **Step 6: Commit administrator authentication**

```powershell
git add backend/src/chat4openapi backend/tests
git commit -m "feat: add secure administrator sessions"
```

### Task 5: Vue Shell, Localization, and API State

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/contracts.ts`
- Create: `frontend/src/i18n/index.ts`
- Create: `frontend/src/i18n/en-US.ts`
- Create: `frontend/src/i18n/zh-CN.ts`
- Create: `frontend/src/stores/auth.ts`
- Test: `frontend/src/__tests__/auth-store.spec.ts`

**Interfaces:**
- Consumes: `/api/setup/status`, `/api/admin/auth/login`, `/api/admin/auth/logout`, `/api/admin/auth/me`.
- Produces: `useAuthStore()` with `loadState`, `initialize`, `login`, `logout`; `apiClient.request<T>()`; locale messages.

- [ ] **Step 1: Select Node through nvm and scaffold dependency metadata**

Run: `nvm use 20.19.4`

Expected: `Now using node v20.19.4`.

```json
{
  "name": "chat4openapi-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "test": "vitest run",
    "typecheck": "vue-tsc -b"
  },
  "dependencies": {
    "@element-plus/icons-vue": "^2.3.2",
    "element-plus": "^2.10.4",
    "pinia": "^3.0.3",
    "vue": "^3.5.18",
    "vue-i18n": "^11.1.11",
    "vue-router": "^4.5.1"
  },
  "devDependencies": {
    "@testing-library/vue": "^8.1.0",
    "@vitejs/plugin-vue": "^6.0.1",
    "@vue/test-utils": "^2.4.6",
    "jsdom": "^26.1.0",
    "msw": "^2.10.4",
    "typescript": "^5.8.3",
    "vite": "^7.0.6",
    "vitest": "^3.2.4",
    "vue-tsc": "^3.0.4"
  }
}
```

- [ ] **Step 2: Write failing auth store tests**

```typescript
it('loads uninitialized setup state', async () => {
  server.use(http.get('/api/setup/status', () => HttpResponse.json({ initialized: false })))
  const store = useAuthStore()
  await store.loadState()
  expect(store.initialized).toBe(false)
  expect(store.admin).toBeNull()
})

it('retains the csrf token returned by login', async () => {
  server.use(http.post('/api/admin/auth/login', () => HttpResponse.json({
    admin: { username: 'admin', locale: 'en-US' }, csrf_token: 'csrf-value'
  })))
  const store = useAuthStore()
  await store.login('admin', 'StrongPass!123')
  expect(store.csrfToken).toBe('csrf-value')
})
```

- [ ] **Step 3: Implement the typed API client and store**

```typescript
export async function request<T>(path: string, init: RequestInit = {}, csrfToken?: string): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  if (csrfToken) headers.set('X-CSRF-Token', csrfToken)
  const response = await fetch(path, { ...init, headers, credentials: 'include' })
  const payload = await response.json()
  if (!response.ok) throw new ApiError(response.status, payload.error.code, payload.error.params)
  return payload as T
}
```

`useAuthStore` stores `initialized: boolean | null`, `admin: AdminSummary | null`, and `csrfToken: string | null`. `loadState()` checks setup first and calls `/me` only when initialized. `initialize`, `login`, and `logout` update state only after successful responses.

- [ ] **Step 4: Add complete English and Chinese message objects**

Both locale files define the same keys: `app.name`, `setup.title`, `setup.username`, `setup.password`, `setup.locale`, `setup.submit`, `login.title`, `login.submit`, `overview.title`, `nav.logout`, and every backend error code used in this phase. A test asserts `Object.keys(flatten(enUS)).sort()` equals `Object.keys(flatten(zhCN)).sort()`.

- [ ] **Step 5: Install and pass frontend unit checks**

Run: `Set-Location frontend; npm install; npm test; npm run typecheck`

Expected: all Vitest tests pass and vue-tsc exits with code 0.

- [ ] **Step 6: Commit the frontend foundation**

```powershell
git add frontend
git commit -m "feat: scaffold localized Vue frontend"
```

### Task 6: Initialization Wizard, Login, and Route Guards

**Files:**
- Create: `frontend/src/router/index.ts`
- Create: `frontend/src/layouts/AdminLayout.vue`
- Create: `frontend/src/views/SetupView.vue`
- Create: `frontend/src/views/LoginView.vue`
- Create: `frontend/src/views/OverviewView.vue`
- Modify: `frontend/src/App.vue`
- Test: `frontend/src/__tests__/setup-view.spec.ts`
- Test: `frontend/src/__tests__/router-guards.spec.ts`

**Interfaces:**
- Consumes: `useAuthStore()` and vue-i18n.
- Produces: `/setup`, `/login`, `/admin` routes with deterministic setup/auth redirects.

- [ ] **Step 1: Write route-guard tests**

```typescript
it('redirects an uninitialized installation to setup', async () => {
  auth.initialized = false
  await router.push('/admin')
  await router.isReady()
  expect(router.currentRoute.value.fullPath).toBe('/setup')
})

it('redirects an initialized unauthenticated admin to login', async () => {
  auth.initialized = true
  auth.admin = null
  await router.push('/admin')
  expect(router.currentRoute.value.fullPath).toBe('/login')
})

it('allows the authenticated administrator into overview', async () => {
  auth.initialized = true
  auth.admin = { username: 'admin', locale: 'en-US' }
  await router.push('/admin')
  expect(router.currentRoute.value.fullPath).toBe('/admin')
})
```

- [ ] **Step 2: Run route tests and confirm missing router**

Run: `Set-Location frontend; npm test -- router-guards.spec.ts`

Expected: FAIL because `router/index.ts` does not exist.

- [ ] **Step 3: Implement deterministic router guards**

```typescript
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (auth.initialized === null) await auth.loadState()
  if (!auth.initialized && to.name !== 'setup') return { name: 'setup' }
  if (auth.initialized && to.name === 'setup') return auth.admin ? { name: 'overview' } : { name: 'login' }
  if (to.meta.requiresAdmin && !auth.admin) return { name: 'login', query: { redirect: to.fullPath } }
  if (to.name === 'login' && auth.admin) return { name: 'overview' }
  return true
})
```

- [ ] **Step 4: Build setup, login, and overview views**

`SetupView` contains locale, username, password, and password-confirmation fields; validates matching passwords and minimum 12 characters; calls `auth.initialize`; updates vue-i18n locale; then routes to login. `LoginView` calls `auth.login` and follows the validated local `redirect` query or `/admin`. `AdminLayout` provides language switch and CSRF-protected logout. `OverviewView` shows provider, API Source, Tool, and Skill empty-state cards without implementing those modules.

- [ ] **Step 5: Test view behavior and production build**

Run: `Set-Location frontend; npm test; npm run build`

Expected: all tests pass and `frontend/dist/index.html` is produced.

- [ ] **Step 6: Commit the first vertical UI slice**

```powershell
git add frontend
git commit -m "feat: add setup and admin login flows"
```

### Task 7: Serve the SPA and Verify the Vertical Slice

**Files:**
- Modify: `backend/src/chat4openapi/main.py`
- Create: `backend/tests/test_spa.py`
- Modify: `README.md`
- Create: `.env.example`

**Interfaces:**
- Consumes: optional `frontend/dist` directory.
- Produces: same-origin SPA hosting with API paths excluded from fallback routing and documented local startup commands.

- [ ] **Step 1: Write SPA fallback tests**

```python
def test_spa_index_is_served_when_dist_exists(app_with_dist) -> None:
    response = app_with_dist.get("/admin")
    assert response.status_code == 200
    assert '<div id="app"></div>' in response.text


def test_unknown_api_path_never_falls_back_to_spa(app_with_dist) -> None:
    response = app_with_dist.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
```

- [ ] **Step 2: Run SPA tests and confirm fallback is absent**

Run: `conda run -n agent4api pytest backend/tests/test_spa.py -q`

Expected: FAIL because `/admin` returns 404.

- [ ] **Step 3: Add safe static mounting and fallback**

`create_app(frontend_dist: Path | None = None)` mounts `/assets` only when the directory exists. A final `/{path:path}` GET handler serves `index.html` only when the path does not start with `api/`, `v1/`, `anthropic/`, or `health`; otherwise it raises 404. The handler uses `FileResponse` with a resolved path fixed to `index.html`, never concatenates user input into filesystem paths.

- [ ] **Step 4: Document exact development commands**

```powershell
conda env create -f environment.yml
conda run -n agent4api alembic -c backend/alembic.ini upgrade head
conda run -n agent4api uvicorn chat4openapi.main:app --app-dir backend/src --reload
nvm use 20.19.4
Set-Location frontend
npm install
npm run dev
```

`.env.example` contains `CHAT4OPENAPI_DATABASE_URL=sqlite:///data/chat4openapi.db`, `CHAT4OPENAPI_DEFAULT_LOCALE=en-US`, and `CHAT4OPENAPI_SECURE_COOKIES=false`, with comments stating that secure cookies must be true behind production HTTPS.

- [ ] **Step 5: Run full verification**

Run: `conda run -n agent4api pytest backend/tests -q; conda run -n agent4api ruff check backend; Set-Location frontend; npm test; npm run typecheck; npm run build`

Expected: every command exits 0, the backend suite passes, frontend tests pass, type checking passes, and Vite creates `dist`.

- [ ] **Step 6: Commit Phase 1**

```powershell
git add backend frontend README.md .env.example
git commit -m "feat: complete platform foundation"
```

## Phase 1 Completion Gate

The phase is complete only when a new SQLite database can be migrated, `/api/setup/status` reports uninitialized, the Vue wizard creates the one administrator, a second setup attempt is rejected, login creates a server-side session with CSRF protection, `/admin` is guarded, both locales render, and the production SPA build is served by FastAPI without masking unknown API routes.

The next implementation plan starts only after this gate passes and covers OpenAPI 2.0/3.x normalization, FastMCP candidate generation, Tool management, global login Tool, isolated Tool User Sessions, dynamic authentication injection, and secure HTTP execution.
