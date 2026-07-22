# Agent Embed Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the public Base URL and secure Agent Embed/session ownership, then expose administrator CRUD and a secret-free public loader.

**Architecture:** Extend the singleton settings and owner constraints through one Alembic migration. Keep normalization and token handling in focused services, expose administrator APIs behind the existing admin/CSRF dependencies, and make public Embed responses origin-aware and non-enumerating.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, SQLite, pytest.

## Global Constraints

- Python is managed by Conda; run backend commands with `conda run -n chat4openapi`.
- Node.js is managed by nvm; frontend plans use `nvm use 20.19.4` before npm commands.
- Base URL accepts absolute HTTP/HTTPS URLs, rejects credentials/query/fragment, strips a trailing slash, and permits HTTP only for loopback development hosts.
- An empty Embed origin list allows any secure parent; configured lists contain normalized exact origins.
- Public IDs and bearer tokens are high entropy; only token hashes are stored.
- Anonymous Embed Chat never bypasses protected backend Tool authorization.
- Every task follows RED → GREEN → focused regression → review → commit.

---

## File and Responsibility Map

- `backend/migrations/versions/0013_agent_embeds.py`: settings, Embed, session, grant, and owner migration.
- `backend/src/chat4openapi/models/embed.py`: `AgentEmbed`, `EmbedSession`, and `EmbedAuthGrant` persistence.
- `backend/src/chat4openapi/models/app_setting.py`: singleton `base_url`.
- `backend/src/chat4openapi/models/conversation.py`: third mutually exclusive owner.
- `backend/src/chat4openapi/models/tool_session.py`: Embed-owned Tool Sessions.
- `backend/src/chat4openapi/embed/urls.py`: Base URL and origin normalization.
- `backend/src/chat4openapi/embed/sessions.py`: public identifiers, bearer hashing, expiry, and revocation.
- `backend/src/chat4openapi/schemas/settings.py`: administrator settings contracts.
- `backend/src/chat4openapi/schemas/embeds.py`: Embed CRUD and session contracts.
- `backend/src/chat4openapi/api/admin_settings.py`: settings endpoints.
- `backend/src/chat4openapi/api/admin_embeds.py`: per-Agent Embed administration.
- `backend/src/chat4openapi/api/embed_public.py`: loader, iframe bootstrap, and Embed Session endpoints.

---

### Task 1: Add Embed Persistence and Ownership Constraints

**Files:**
- Create: `backend/migrations/versions/0013_agent_embeds.py`
- Create: `backend/src/chat4openapi/models/embed.py`
- Modify: `backend/src/chat4openapi/models/app_setting.py`
- Modify: `backend/src/chat4openapi/models/conversation.py`
- Modify: `backend/src/chat4openapi/models/tool_session.py`
- Modify: `backend/src/chat4openapi/models/__init__.py`
- Test: `backend/tests/test_embed_migration.py`
- Test: `backend/tests/test_embed_models.py`

**Interfaces:**
- Produces: `AppSetting.base_url: str | None`.
- Produces: `AgentEmbed`, `EmbedSession`, `EmbedAuthGrant`.
- Produces: nullable `Conversation.embed_session_id` and `ToolUserSession.embed_session_id` with exactly-one-owner checks.

- [ ] **Step 1: Write failing migration and constraint tests**

```python
def test_0013_preserves_existing_owners(upgrade_from_0012):
    upgrade_from_0012()
    assert scalar("SELECT base_url FROM app_settings WHERE id = 1") is None
    assert scalar("SELECT count(*) FROM conversations") == 1

def test_embed_conversation_rejects_two_owners(db, embed_session, browser_session, agent):
    db.add(Conversation(agent_id=agent.id, embed_session_id=embed_session.id,
                        browser_chat_session_id=browser_session.id))
    with pytest.raises(IntegrityError):
        db.commit()
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `conda run -n chat4openapi pytest backend/tests/test_embed_migration.py backend/tests/test_embed_models.py -q`

Expected: failures for missing migration, tables, columns, and model imports.

- [ ] **Step 3: Implement the models and migration**

```python
class AgentEmbed(Base):
    __tablename__ = "agent_embeds"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    public_id: Mapped[str] = mapped_column(String(43), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    allowed_origins: Mapped[list[str]] = mapped_column(JSON, default=list)
    position: Mapped[str] = mapped_column(String(16), default="bottom_right")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

Migration checks must encode three active conversation owners and three Tool Session owners with nullable Embed foreign keys. `EmbedAuthGrant` stores `code_hash`, `embed_session_id`, `tool_session_id`, `api_source_id`, `expires_at`, and `consumed_at`.

- [ ] **Step 4: Run focused and migration acceptance tests**

Run: `conda run -n chat4openapi pytest backend/tests/test_embed_migration.py backend/tests/test_embed_models.py backend/tests/test_final_migration_acceptance.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/migrations/versions/0013_agent_embeds.py backend/src/chat4openapi/models backend/tests/test_embed_migration.py backend/tests/test_embed_models.py backend/tests/test_final_migration_acceptance.py
git commit -m "feat: persist Agent embeds and sessions"
```

---

### Task 2: Normalize Base URLs and Parent Origins

**Files:**
- Create: `backend/src/chat4openapi/embed/__init__.py`
- Create: `backend/src/chat4openapi/embed/urls.py`
- Test: `backend/tests/test_embed_urls.py`

**Interfaces:**
- Produces: `normalize_base_url(value: str) -> str`.
- Produces: `normalize_origin(value: str, *, allow_loopback_http: bool = True) -> str`.
- Produces: `frame_ancestors(origins: list[str]) -> str`.

- [ ] **Step 1: Write table-driven failing tests**

```python
@pytest.mark.parametrize(("value", "expected"), [
    ("https://chat.example.com/", "https://chat.example.com"),
    ("http://127.0.0.1:8000/", "http://127.0.0.1:8000"),
])
def test_normalize_base_url(value, expected):
    assert normalize_base_url(value) == expected

@pytest.mark.parametrize("value", [
    "http://chat.example.com", "https://u:p@chat.example.com", "https://chat.example.com?q=1",
])
def test_normalize_base_url_rejects_unsafe_values(value):
    with pytest.raises(ValueError):
        normalize_base_url(value)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `conda run -n chat4openapi pytest backend/tests/test_embed_urls.py -q`

Expected: import failure for `chat4openapi.embed.urls`.

- [ ] **Step 3: Implement strict normalization**

```python
def normalize_origin(value: str, *, allow_loopback_http: bool = True) -> str:
    url = urlsplit(value.strip())
    loopback = url.hostname in {"localhost", "127.0.0.1", "::1"}
    if url.scheme not in {"http", "https"} or not url.hostname:
        raise ValueError("absolute HTTP(S) origin required")
    if url.scheme == "http" and not (allow_loopback_http and loopback):
        raise ValueError("HTTPS required")
    if url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}:
        raise ValueError("origin components are not allowed")
    return f"{url.scheme}://{url.netloc}"

def frame_ancestors(origins: list[str]) -> str:
    return "frame-ancestors " + (" ".join(origins) if origins else "https: http://localhost:* http://127.0.0.1:*")
```

- [ ] **Step 4: Run URL tests**

Run: `conda run -n chat4openapi pytest backend/tests/test_embed_urls.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/chat4openapi/embed backend/tests/test_embed_urls.py
git commit -m "feat: validate public embed URLs"
```

---

### Task 3: Add Administrator Settings and Embed CRUD APIs

**Files:**
- Create: `backend/src/chat4openapi/schemas/settings.py`
- Create: `backend/src/chat4openapi/schemas/embeds.py`
- Create: `backend/src/chat4openapi/api/admin_settings.py`
- Create: `backend/src/chat4openapi/api/admin_embeds.py`
- Modify: `backend/src/chat4openapi/main.py`
- Test: `backend/tests/test_admin_settings.py`
- Test: `backend/tests/test_admin_embeds.py`

**Interfaces:**
- Produces: `GET/PUT /api/admin/settings`.
- Produces: CRUD at `/api/admin/agents/{agent_id}/embeds` and script preview endpoint.
- Consumes: `normalize_base_url`, `normalize_origin`, existing `require_admin`, `require_csrf`, and `serialized_write`.

- [ ] **Step 1: Write failing authorization, validation, and CRUD tests**

```python
def test_update_base_url_normalizes(client, csrf_headers):
    response = client.put("/api/admin/settings", json={"base_url": "https://chat.example/"}, headers=csrf_headers)
    assert response.status_code == 200
    assert response.json()["base_url"] == "https://chat.example"

def test_create_embed_returns_secret_free_script(client, csrf_headers, enabled_agent):
    response = client.post(f"/api/admin/agents/{enabled_agent.id}/embeds", json={
        "name": "Docs", "enabled": True, "allowed_origins": ["https://docs.example"],
        "position": "bottom_right",
    }, headers=csrf_headers)
    assert response.status_code == 201
    assert "<script src=\"https://chat.example/embed/" in response.json()["script"]
    assert "secret" not in response.text.lower()
```

- [ ] **Step 2: Run API tests and verify RED**

Run: `conda run -n chat4openapi pytest backend/tests/test_admin_settings.py backend/tests/test_admin_embeds.py -q`

Expected: 404 for the new routes.

- [ ] **Step 3: Implement schemas and routes**

```python
class AgentEmbedWrite(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    allowed_origins: list[str] = Field(default_factory=list, max_length=64)
    position: Literal["bottom_right", "bottom_left"] = "bottom_right"

def generated_script(base_url: str, public_id: str) -> str:
    src = html.escape(f"{base_url}/embed/{public_id}.js", quote=True)
    return f'<script src="{src}" async></script>'
```

Normalize and deduplicate origins before persistence; reject script generation with `settings.base_url_required`; soft-delete Embeds; require both admin and CSRF for mutations.

- [ ] **Step 4: Run focused APIs and admin concurrency tests**

Run: `conda run -n chat4openapi pytest backend/tests/test_admin_settings.py backend/tests/test_admin_embeds.py backend/tests/test_admin_write_concurrency.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/chat4openapi/api backend/src/chat4openapi/schemas backend/src/chat4openapi/main.py backend/tests/test_admin_settings.py backend/tests/test_admin_embeds.py
git commit -m "feat: administer Agent embeds"
```

---

### Task 4: Implement Public Loader, CSP, and Embed Sessions

**Files:**
- Create: `backend/src/chat4openapi/embed/sessions.py`
- Create: `backend/src/chat4openapi/api/embed_public.py`
- Modify: `backend/src/chat4openapi/main.py`
- Test: `backend/tests/test_embed_public.py`
- Test: `backend/tests/test_embed_sessions.py`

**Interfaces:**
- Produces: `GET /embed/{public_id}.js`, `GET /embed/{public_id}`, `POST /api/embed/{public_id}/sessions`, and `DELETE /api/embed/sessions/{session_id}`.
- Produces: `issue_embed_session(...) -> tuple[EmbedSession, str]` and `require_embed_session(...) -> EmbedSession`.

- [ ] **Step 1: Write failing public boundary tests**

```python
def test_loader_has_only_public_configuration(client, embed):
    body = client.get(f"/embed/{embed.public_id}.js").text
    assert 'allow="tools"' in body
    assert embed.public_id in body
    assert "client_secret" not in body

def test_iframe_has_exact_frame_ancestors(client, embed):
    response = client.get(f"/embed/{embed.public_id}")
    assert response.headers["content-security-policy"] == "frame-ancestors https://docs.example"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n chat4openapi pytest backend/tests/test_embed_public.py backend/tests/test_embed_sessions.py -q`

Expected: missing routes and session service.

- [ ] **Step 3: Implement token issuance and a self-contained loader**

```python
def issue_embed_session(db: Session, embed: AgentEmbed, parent_origin: str) -> tuple[EmbedSession, str]:
    token = secrets.token_urlsafe(32)
    session = EmbedSession(embed_id=embed.id, agent_id=embed.agent_id,
        public_subject_id=str(uuid.uuid4()), parent_origin=parent_origin,
        token_hash=hash_session_token(token), idle_expires_at=now_plus(hours=2),
        absolute_expires_at=now_plus(days=7))
    db.add(session)
    db.flush()
    return session, token
```

The loader creates one shadow-DOM logo and an iframe with `allow="tools"`, sends `{type: "chat4openapi:init", parentOrigin: location.origin}` using the exact Base URL origin, and accepts only open/close lifecycle messages from that iframe. Public unavailable/origin errors share the same 404 envelope.

- [ ] **Step 4: Run public/session and SPA fallback tests**

Run: `conda run -n chat4openapi pytest backend/tests/test_embed_public.py backend/tests/test_embed_sessions.py backend/tests/test_spa.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/chat4openapi/embed/sessions.py backend/src/chat4openapi/api/embed_public.py backend/src/chat4openapi/main.py backend/tests/test_embed_public.py backend/tests/test_embed_sessions.py
git commit -m "feat: serve secure Agent embed sessions"
```

---

### Task 5: Foundation Regression Gate

**Files:**
- Modify only files required by failures found in this gate.

**Interfaces:**
- Produces: a migration-safe, administrable, secret-free Embed foundation for the runtime plan.

- [ ] **Step 1: Run backend formatting and lint checks**

Run: `conda run -n chat4openapi ruff check backend`

Expected: PASS.

- [ ] **Step 2: Run the complete backend suite**

Run: `conda run -n chat4openapi pytest backend/tests -q`

Expected: PASS with no regression in browser Chat, API-key Chat, OAuth, or Tool Sessions.

- [ ] **Step 3: Inspect the migration and public script for secrets**

Run: `git grep -n -E "client_secret|encrypted_config|api_key" -- backend/src/chat4openapi/api/embed_public.py backend/src/chat4openapi/embed`

Expected: no serialization of credential values; security-related identifiers may appear only in validation code.

- [ ] **Step 4: Commit gate fixes if the gate changed files**

```powershell
git add backend
git commit -m "test: harden Agent embed foundation"
```
