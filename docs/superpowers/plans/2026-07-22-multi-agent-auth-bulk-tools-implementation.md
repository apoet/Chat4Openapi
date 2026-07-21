# Chat4Openapi Multi-Agent, Authentication, and Bulk Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the product to Chat4Openapi and deliver multiple Skill-bound Agents, per-Agent API keys, pre-authorized Tool Sessions, Agent-only Chat selection, bulk Tool management, and a scalable Skill Tool picker.

**Architecture:** Replace the singleton Agent with relational Agents and ordered Agent-Skill bindings. Authenticate compatible APIs with high-entropy Agent-bound keys, then keep upstream business identity in separately encrypted Tool Sessions. Preserve current Agent runtime semantics while selecting the Agent at conversation creation and add focused bulk/large-catalog UI services rather than expanding existing view components indefinitely.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, SQLite, Pydantic 2, httpx, cryptography, Vue 3, Pinia, TypeScript, Vitest, Vite, Playwright CLI.

## Global Constraints

- Node.js is managed with nvm; run `nvm use 20.19.4` and invoke `npm` from PATH.
- Python is managed with Conda; use the active pre-rename environment during the rename task, then document the new `chat4openapi` environment name.
- The canonical visible and package name is `Chat4Openapi` / `chat4openapi`; no old-name compatibility aliases remain.
- Existing SQLite data, imported APIs, Tools, Skills, conversations, and history must survive migration.
- Browser HIL clarifies business parameters only; Tool calls never require approval and OAuth never runs inside a chat turn.
- Compatible APIs require an Agent API key and may use only the Agent bound to that key.
- Secrets are never logged or returned after creation; Tool credentials remain encrypted at rest.
- Every task follows RED → GREEN → focused regression → review → commit.

---

## File and Responsibility Map

- `backend/src/chat4openapi/models/agent.py`: Agent, AgentSkill, and AgentApiKey persistence.
- `backend/src/chat4openapi/models/conversation.py`: immutable per-conversation Agent association.
- `backend/src/chat4openapi/models/tool_session.py`: Tool Session status and encrypted per-source credentials.
- `backend/src/chat4openapi/security/agent_keys.py`: key generation, hashing, verification, and masking.
- `backend/src/chat4openapi/tool_sessions/`: OAuth/device/PKCE/injection/login workflows and credential resolution.
- `backend/src/chat4openapi/chat/agent.py`: Agent-specific Skill catalog and Tool execution.
- `backend/src/chat4openapi/chat/api.py`: Agent selection, API-key authentication, and compatible aliases.
- `backend/src/chat4openapi/api/admin_agents.py`: Agent CRUD, default switch, bindings, and key administration.
- `backend/src/chat4openapi/api/admin_tools.py`: single-item and bulk Tool administration.
- `frontend/src/components/AgentSelect.vue`: Chat Agent selector.
- `frontend/src/components/AgentEditor.vue`: Agent configuration, Skill binding, and API-key management.
- `frontend/src/components/ToolCatalogPanel.vue`: compact searchable/filterable Tool catalog shared by Skill editing and `@tool` references.
- `frontend/src/components/ToolBulkBar.vue`: selection summary and bulk actions.
- `frontend/src/stores/agents.ts`, `toolSessions.ts`, `tools.ts`: focused client state and API calls.

---

### Task 1: Rename the Product and Packages

**Files:**
- Move the existing backend Python package to `backend/src/chat4openapi/`.
- Modify: `backend/pyproject.toml`
- Modify: `backend/alembic.ini`
- Modify: `backend/migrations/env.py`
- Modify: `backend/.env.example`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/index.html`
- Modify: all tracked imports, environment variables, headers, extensions, docs, tests, and fixtures containing the old name
- Test: `backend/tests/test_brand_migration.py`
- Test: `frontend/src/__tests__/locale-coverage.spec.ts`

**Interfaces:**
- Produces: import root `chat4openapi`, environment prefix `CHAT4OPENAPI_`, header prefix `X-Chat4Openapi-`, extension prefix `chat4openapi_`.
- Produces: `migrate_legacy_default_files(settings: Settings) -> None` that moves an old default DB/key only when the destination is absent.

- [ ] **Step 1: Write failing brand and file-migration tests**

```python
def test_legacy_default_files_move_without_overwriting(tmp_path):
    legacy = tmp_path / "legacy.db"
    current = tmp_path / "chat4openapi.db"
    legacy.write_bytes(b"sqlite")
    migrate_legacy_file(legacy, current)
    assert current.read_bytes() == b"sqlite"
    assert not legacy.exists()

def test_existing_new_file_is_never_overwritten(tmp_path):
    legacy = tmp_path / "legacy.db"
    current = tmp_path / "chat4openapi.db"
    legacy.write_bytes(b"old")
    current.write_bytes(b"new")
    migrate_legacy_file(legacy, current)
    assert current.read_bytes() == b"new"
    assert legacy.read_bytes() == b"old"
```

- [ ] **Step 2: Run tests and record RED**

Run: `conda run -n chat4openapi pytest backend/tests/test_brand_migration.py -q`
Expected: import failure for `chat4openapi` or missing migration helper.

- [ ] **Step 3: Move the package and replace owned identifiers**

```python
import os


def migrate_legacy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except (FileExistsError, FileNotFoundError):
        return
    source.unlink(missing_ok=True)
```

Use `git mv` for the Python package, then mechanically replace product-owned identifiers. Do not rename generic SQLite tables.

- [ ] **Step 4: Verify imports, frontend build, and zero tracked legacy names**

Run:

```powershell
conda run -n chat4openapi pytest backend/tests/test_brand_migration.py backend/tests/test_database.py -q
npm test -- --run src/__tests__/locale-coverage.spec.ts
npm run typecheck
$legacyLower = "chat" + "api"
$legacyTitle = "Chat" + "API"
$legacyUpper = "CHAT" + "API"
git grep -in -E "$legacyLower|$legacyTitle|$legacyUpper" -- .
```

Expected: tests pass, typecheck passes, and the final scan is empty after updating all historical tracked plans/specifications and the Conda command examples to the new name.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: rename product to Chat4Openapi"
```

---

### Task 2: Migrate Singleton Agent Persistence to Multi-Agent

**Files:**
- Create: `backend/migrations/versions/0008_multi_agent.py`
- Modify: `backend/src/chat4openapi/models/agent.py`
- Modify: `backend/src/chat4openapi/models/conversation.py`
- Modify: `backend/src/chat4openapi/models/__init__.py`
- Modify: `backend/src/chat4openapi/schemas/agents.py`
- Test: `backend/tests/test_multi_agent_models.py`
- Test: `backend/tests/test_database.py`

**Interfaces:**
- Produces: `Agent`, `AgentSkill`, `AgentApiKey` ORM models.
- Produces: `Conversation.agent_id: int` and immutable association at runtime.
- Produces: one active default Agent invariant and ordered `Agent.skills` bindings.

- [ ] **Step 1: Write migration and model tests**

```python
def test_existing_singleton_becomes_default_agent(migrated_0007_database):
    upgrade_to_head(migrated_0007_database)
    agents = rows("SELECT id, is_default FROM agents")
    assert agents == [(1, 1)]
    assert scalar("SELECT count(*) FROM conversations WHERE agent_id IS NULL") == 0
    assert scalar("SELECT count(*) FROM agent_skills") == scalar(
        "SELECT count(*) FROM skills WHERE deleted_at IS NULL"
    )
```

Cover fresh upgrade, existing conversations, stable Skill order, downgrade/re-upgrade, and preservation of prompt/provider/mode/failure fields.

- [ ] **Step 2: Run migration tests and record RED**

Run: `conda run -n chat4openapi pytest backend/tests/test_multi_agent_models.py backend/tests/test_database.py -q`
Expected: missing `agents`, `agent_skills`, `agent_api_keys`, and `conversations.agent_id`.

- [ ] **Step 3: Implement ORM and migration**

```python
class AgentSkill(Base):
    __tablename__ = "agent_skills"
    __table_args__ = (UniqueConstraint("agent_id", "skill_id"),)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(default=0)
```

Create the new tables, copy singleton data, bind non-deleted Skills, backfill conversations, then remove `agent_config`. Enforce one default with a SQLite partial unique index on active `is_default` rows.

- [ ] **Step 4: Run focused migrations and ORM tests**

Run: `conda run -n chat4openapi pytest backend/tests/test_multi_agent_models.py backend/tests/test_database.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/migrations backend/src/chat4openapi/models backend/src/chat4openapi/schemas backend/tests
git commit -m "feat: persist multiple skill-bound agents"
```

---

### Task 3: Implement Multi-Agent Administration

**Files:**
- Replace: `backend/src/chat4openapi/api/admin_agent.py` with `backend/src/chat4openapi/api/admin_agents.py`
- Modify: `backend/src/chat4openapi/api/admin_providers.py`
- Modify: `backend/src/chat4openapi/main.py`
- Modify: `backend/src/chat4openapi/schemas/agents.py`
- Test: `backend/tests/test_agent_api.py`
- Test: `backend/tests/test_llm_providers.py`

**Interfaces:**
- Produces CRUD routes at `/api/admin/agents` and `/api/admin/agents/{agent_id}`.
- Produces actions `/enable`, `/disable`, `/set-default`, and ordered `/skills` replacement.
- Produces provider-in-use errors with `agent_ids: list[int]`.

- [ ] **Step 1: Write failing CRUD/default/binding tests**

```python
def test_default_agent_cannot_be_disabled(client, csrf_headers):
    response = client.post("/api/admin/agents/1/disable", headers=csrf_headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agents.default_cannot_disable"

def test_enable_requires_provider_and_running_bound_skill(client, csrf_headers):
    response = client.post("/api/admin/agents/2/enable", headers=csrf_headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agents.no_running_skills"
```

Also cover transactional default switching, soft deletion, ordered bindings, stopped-binding retention, and provider reference lists.

- [ ] **Step 2: Run focused API tests and record RED**

Run: `conda run -n chat4openapi pytest backend/tests/test_agent_api.py backend/tests/test_llm_providers.py -q`
Expected: old singleton route or missing collection endpoints.

- [ ] **Step 3: Implement transactional services and routes**

```python
def set_default_agent(db: Session, agent: Agent) -> None:
    db.execute(update(Agent).where(Agent.deleted_at.is_(None)).values(is_default=False))
    agent.is_default = True
    agent.enabled = True
    db.commit()
```

Validate provider and running bound Skills on enable. Lock default transitions in one SQLite write transaction.

- [ ] **Step 4: Run focused and affected backend tests**

Run: `conda run -n chat4openapi pytest backend/tests/test_agent_api.py backend/tests/test_llm_providers.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/chat4openapi/api backend/src/chat4openapi/schemas backend/tests
git commit -m "feat: manage multiple agents"
```

---

### Task 4: Add Per-Agent API Keys and Compatible Authentication

**Files:**
- Create: `backend/src/chat4openapi/security/agent_keys.py`
- Create: `backend/src/chat4openapi/api/agent_keys.py`
- Modify: `backend/src/chat4openapi/chat/api.py`
- Modify: `backend/src/chat4openapi/schemas/agents.py`
- Test: `backend/tests/test_agent_keys.py`
- Test: `backend/tests/test_compatible_api.py`

**Interfaces:**
- Produces: `create_agent_key() -> tuple[AgentApiKey, str]`.
- Produces: `require_agent_api_key(Authorization) -> AgentKeyContext`.
- Consumes model aliases `agent-default`, `agent-<id>`, `skill-<id>` and `chat4openapi_skill_ids`.

- [ ] **Step 1: Write key lifecycle and isolation tests**

```python
def test_plaintext_agent_key_is_returned_once(client, csrf_headers):
    created = client.post("/api/admin/agents/1/keys", json={"label": "CI"}, headers=csrf_headers)
    secret = created.json()["secret"]
    assert secret.startswith("c4o_")
    listed = client.get("/api/admin/agents/1/keys").json()
    assert "secret" not in listed[0]

def test_key_cannot_select_another_agent(client, agent_one_key):
    response = client.post("/v1/chat/completions", headers=bearer(agent_one_key), json={"model": "agent-2", "messages": USER})
    assert response.status_code == 403
```

Cover missing/invalid/expired/revoked keys, last-used update, `agent-default`, bound/unbound Skill aliases, Anthropic, streaming, and secret non-disclosure.

- [ ] **Step 2: Run tests and record RED**

Run: `conda run -n chat4openapi pytest backend/tests/test_agent_keys.py backend/tests/test_compatible_api.py -q`
Expected: compatible endpoints still accept unauthenticated requests.

- [ ] **Step 3: Implement high-entropy hashed keys and dependency**

```python
def generate_agent_key() -> tuple[str, str, str]:
    secret = "c4o_" + secrets.token_urlsafe(32)
    prefix = secret[:12]
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return secret, prefix, digest
```

Use constant-time comparison after prefix narrowing. Resolve the Agent exclusively from the key context before model alias validation.

- [ ] **Step 4: Run focused tests and scan responses/log fixtures for secrets**

Run: `conda run -n chat4openapi pytest backend/tests/test_agent_keys.py backend/tests/test_compatible_api.py -q`
Expected: PASS and no plaintext key in persisted rows or list responses.

- [ ] **Step 5: Commit**

```bash
git add backend/src/chat4openapi/security backend/src/chat4openapi/api backend/src/chat4openapi/chat backend/tests
git commit -m "feat: authenticate compatible APIs per agent"
```

---

### Task 5: Make Agent Runtime Use Bound Skills and Locked Agent Conversations

**Files:**
- Modify: `backend/src/chat4openapi/chat/agent.py`
- Modify: `backend/src/chat4openapi/chat/context.py`
- Modify: `backend/src/chat4openapi/chat/api.py`
- Modify: `backend/src/chat4openapi/chat/orchestrator.py`
- Test: `backend/tests/test_agent_runtime.py`
- Test: `backend/tests/test_chat_turn_api.py`

**Interfaces:**
- Changes `AgentTurnRequest` to require `agent_id: int` and make direct browser candidate IDs unavailable.
- Produces Agent catalog from ordered, bound, running Skills only.
- Produces `409 chat.agent_locked` on explicit Agent change.

- [ ] **Step 1: Write failing Agent isolation and lock tests**

```python
async def test_agent_cannot_load_skill_bound_only_to_another_agent(runtime):
    result = await runtime.run(turn(agent_id=1, user_content="use foreign skill"))
    assert result.loaded_skill_ids == []
    assert tool_runner.calls == []

def test_browser_conversation_rejects_agent_change(client):
    first = client.post("/api/chat/turns", json={"agent_id": 1, "message": "hello"}).json()
    changed = client.post("/api/chat/turns", json={"agent_id": 2, "conversation_id": first["conversation_id"], "message": "again"})
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "chat.agent_locked"
```

- [ ] **Step 2: Run focused runtime tests and record RED**

Run: `conda run -n chat4openapi pytest backend/tests/test_agent_runtime.py backend/tests/test_chat_turn_api.py -q`
Expected: singleton Agent lookup and all-running-Skills catalog violate assertions.

- [ ] **Step 3: Implement Agent-specific configuration and catalog queries**

```python
query = (
    select(Skill)
    .join(AgentSkill, AgentSkill.skill_id == Skill.id)
    .where(AgentSkill.agent_id == agent.id, Skill.running.is_(True), Skill.deleted_at.is_(None))
    .order_by(AgentSkill.position, Skill.id)
)
```

Persist `conversation.agent_id` on creation and use it on continuation. Compatible Skill scopes are intersected with this catalog.

- [ ] **Step 4: Run focused runtime/API regressions**

Run: `conda run -n chat4openapi pytest backend/tests/test_agent_runtime.py backend/tests/test_chat_turn_api.py backend/tests/test_compatible_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/chat4openapi/chat backend/tests
git commit -m "feat: isolate conversations by agent"
```

---

### Task 6: Generalize Tool Session Persistence and Credential Injection

**Files:**
- Create: `backend/src/chat4openapi/models/tool_session.py`
- Create: `backend/src/chat4openapi/tool_sessions/credentials.py`
- Modify: `backend/src/chat4openapi/tool_sessions/service.py`
- Modify: `backend/src/chat4openapi/api/tool_sessions.py`
- Modify: `backend/src/chat4openapi/schemas/tools.py`
- Test: `backend/tests/test_tool_sessions.py`
- Test: `backend/tests/test_tool_session_credentials.py`

**Interfaces:**
- Produces `ToolSessionService.create_injected(context, credentials_by_source, expires_at)`.
- Produces `ToolSessionService.resolve(token, agent_id, agent_key_id, api_source_id)`.
- Produces statuses `authorization_required|pending|ready|expired|revoked|failed`.

- [ ] **Step 1: Write injection, binding, expiry, and allow-list tests**

```python
def test_injected_header_must_be_allow_listed(client, agent_key):
    response = client.post(
        "/api/tool-sessions/credentials",
        headers=bearer(agent_key),
        json={"api_source_id": 4, "headers": {"Host": "evil.example"}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tool_credentials.field_not_allowed"
```

Cover manual/browser creation, API creation, Cookie normalization, encrypted rows, cross-key/Agent/source rejection, key revocation, JWT-exp cap, and secret-free responses.

- [ ] **Step 2: Run tests and record RED**

Run: `conda run -n chat4openapi pytest backend/tests/test_tool_sessions.py backend/tests/test_tool_session_credentials.py -q`
Expected: existing global username/password Session cannot satisfy per-source bindings.

- [ ] **Step 3: Implement generalized encrypted credential maps**

```python
FORBIDDEN_HEADERS = {"host", "content-length", "connection", "forwarded", "x-forwarded-for"}

def validate_injected_headers(configured: set[str], supplied: Mapping[str, str]) -> None:
    normalized = {name.lower() for name in supplied}
    if normalized & FORBIDDEN_HEADERS or not normalized <= {name.lower() for name in configured}:
        raise ToolSessionError("tool_credentials.field_not_allowed")
```

Store only encrypted credential JSON plus hashes/metadata. Resolve the correct source credential immediately before Tool execution.

- [ ] **Step 4: Run focused Tool Session and Agent Tool execution tests**

Run: `conda run -n chat4openapi pytest backend/tests/test_tool_sessions.py backend/tests/test_tool_session_credentials.py backend/tests/test_agent_runtime.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/chat4openapi/models backend/src/chat4openapi/tool_sessions backend/src/chat4openapi/api backend/tests
git commit -m "feat: bind encrypted tool credentials to agent sessions"
```

---

### Task 7: Add OAuth Device and Authorization Code with PKCE

**Files:**
- Create: `backend/src/chat4openapi/tool_sessions/oauth.py`
- Create: `backend/src/chat4openapi/api/tool_oauth.py`
- Modify: `backend/src/chat4openapi/models/tool_session.py`
- Modify: `backend/src/chat4openapi/main.py`
- Test: `backend/tests/test_tool_oauth.py`

**Interfaces:**
- Produces start/status flows for Device Authorization Grant.
- Produces PKCE start/callback with one-time state and verifier binding.
- Consumes per-source OAuth configuration and writes encrypted tokens to a Tool Session.

- [ ] **Step 1: Write deterministic OAuth protocol tests with mock upstream**

```python
async def test_device_flow_returns_user_instructions_and_becomes_ready(client, agent_key, mock_oauth):
    started = client.post("/api/tool-sessions/oauth/device/start", headers=bearer(agent_key), json={"api_source_id": 3}).json()
    assert started["status"] == "pending"
    assert started["verification_uri"] == "https://issuer.example/device"
    mock_oauth.authorize(started["user_code"])
    status = client.get(f"/api/tool-sessions/{started['tool_session_id']}/status", headers=bearer(agent_key)).json()
    assert status["status"] == "ready"
```

Cover polling interval, expiry, authorization_pending, slow_down, denial, PKCE S256, state replay, callback mismatch, refresh, and redacted errors.

- [ ] **Step 2: Run OAuth tests and record RED**

Run: `conda run -n chat4openapi pytest backend/tests/test_tool_oauth.py -q`
Expected: missing OAuth services/routes.

- [ ] **Step 3: Implement OAuth clients without chat-turn redirects**

```python
def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge
```

Encrypt verifier, access token, and refresh token. Device status polling occurs only through the Session status endpoint, never inside AgentRuntime.

- [ ] **Step 4: Run OAuth and Tool Session regressions**

Run: `conda run -n chat4openapi pytest backend/tests/test_tool_oauth.py backend/tests/test_tool_sessions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/chat4openapi/tool_sessions backend/src/chat4openapi/api backend/tests
git commit -m "feat: preauthorize tool sessions with OAuth"
```

---

### Task 8: Build Multi-Agent Administration UI

**Files:**
- Create: `frontend/src/components/AgentEditor.vue`
- Create: `frontend/src/components/AgentKeyPanel.vue`
- Create: `frontend/src/stores/agents.ts`
- Modify: `frontend/src/views/AgentView.vue`
- Modify: `frontend/src/api/contracts.ts`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Test: `frontend/src/__tests__/agent-view.spec.ts`

**Interfaces:**
- Consumes multi-Agent admin and key APIs.
- Produces list/editor/default actions, ordered Skill bindings, and one-time key display.

- [ ] **Step 1: Write failing UI behavior tests**

```ts
it('creates an Agent, binds ordered Skills, and shows a new API key once', async () => {
  renderAgentView()
  await user.click(screen.getByRole('button', { name: 'New Agent' }))
  await user.click(screen.getByLabelText('Varcards2-Gene'))
  await user.click(screen.getByRole('button', { name: 'Save Agent' }))
  await user.click(screen.getByRole('button', { name: 'Create API key' }))
  expect(await screen.findByText(/^c4o_/)).toBeVisible()
})
```

Cover default protection, enable validation errors, provider references, key revoke/expiry, Skill search/order, and both locales.

- [ ] **Step 2: Run UI tests and record RED**

Run: `npm test -- --run src/__tests__/agent-view.spec.ts`
Expected: singleton form lacks list/editor/key behavior.

- [ ] **Step 3: Implement focused components and store**

Keep secrets in component memory only; clear them on close/navigation. Never place key plaintext in Pinia persistence or localStorage.

- [ ] **Step 4: Run Agent UI, locale, and build checks**

Run:

```powershell
npm test -- --run src/__tests__/agent-view.spec.ts src/__tests__/locale-coverage.spec.ts
npm run typecheck
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: administer multiple agents and keys"
```

---

### Task 9: Replace Chat Skill Selection with Agent Selection

**Files:**
- Create: `frontend/src/components/AgentSelect.vue`
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/api/contracts.ts`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Delete: `frontend/src/components/SkillMultiSelect.vue`
- Test: `frontend/src/__tests__/skills-chat.spec.ts`

**Interfaces:**
- Produces browser-local history with `agentId` and `agentName` snapshot.
- Sends `agent_id` only on conversation creation/explicit validation; continuation uses server association.

- [ ] **Step 1: Write failing selector, lock, and history migration tests**

```ts
it('selects the default Agent and locks it after the first turn', async () => {
  renderChat()
  expect(screen.getByRole('combobox', { name: 'Agent' })).toHaveValue('1')
  await send('hello')
  expect(screen.getByRole('combobox', { name: 'Agent' })).toBeDisabled()
  expect(turnBody()).toMatchObject({ agent_id: 1, message: 'hello' })
})
```

Cover two Agents, New Chat unlock, old `skillIds` history migration, refresh, stopped/deleted Agent, HIL, Tool Session forwarding, and malformed storage isolation.

- [ ] **Step 2: Run Chat tests and record RED**

Run: `npm test -- --run src/__tests__/skills-chat.spec.ts`
Expected: Skill multi-selector remains and no Agent lock exists.

- [ ] **Step 3: Implement Agent selection and v3 history migration**

Map old sessions to preserved messages with no client-selected Agent; load their Agent from server when resumed. New sessions store the selected Agent snapshot.

- [ ] **Step 4: Run Chat regressions and build**

Run:

```powershell
npm test -- --run src/__tests__/skills-chat.spec.ts src/__tests__/markdown-message.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: select agents in browser chat"
```

---

### Task 10: Implement Bulk Tool Backend Operations

**Files:**
- Modify: `backend/src/chat4openapi/api/admin_tools.py`
- Modify: `backend/src/chat4openapi/schemas/tools.py`
- Create: `backend/src/chat4openapi/tools/bulk.py`
- Test: `backend/tests/test_admin_tools_bulk.py`

**Interfaces:**
- Produces `POST /api/admin/tools/batch` with action `enable|disable|delete` and at most 200 IDs.
- Produces ordered per-item `succeeded` and `failed` results.

- [ ] **Step 1: Write partial-success and idempotency tests**

```python
def test_bulk_disable_is_partial_and_idempotent(client, csrf_headers, tools):
    response = client.post(
        "/api/admin/tools/batch",
        headers=csrf_headers,
        json={"action": "disable", "tool_ids": [tools.enabled, tools.disabled, 999999]},
    )
    assert response.status_code == 200
    assert [item["tool_id"] for item in response.json()["succeeded"]] == [tools.enabled, tools.disabled]
    assert response.json()["failed"][0]["code"] == "tools.not_found"
```

Cover delete, duplicate IDs, invalid IDs, 201st item, source constraints, CSRF, stable ordering, and rollback isolation.

- [ ] **Step 2: Run tests and record RED**

Run: `conda run -n chat4openapi pytest backend/tests/test_admin_tools_bulk.py -q`
Expected: route missing.

- [ ] **Step 3: Implement one-item transactions with structured results**

```python
for tool_id in unique_ids:
    try:
        with db.begin_nested():
            result = apply_bulk_action(db, tool_id, action)
        succeeded.append(result)
    except BulkToolError as exc:
        failed.append({"tool_id": tool_id, "code": exc.code, "params": exc.params})
db.commit()
```

- [ ] **Step 4: Run focused and existing Tool tests**

Run: `conda run -n chat4openapi pytest backend/tests/test_admin_tools_bulk.py backend/tests/test_admin_tools.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/chat4openapi/api backend/src/chat4openapi/schemas backend/src/chat4openapi/tools backend/tests
git commit -m "feat: bulk manage tools"
```

---

### Task 11: Add Tool Selection and Bulk Actions to the Tools UI

**Files:**
- Create: `frontend/src/components/ToolBulkBar.vue`
- Modify: `frontend/src/views/ToolsView.vue`
- Modify: `frontend/src/stores/tools.ts`
- Modify: `frontend/src/api/contracts.ts`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Test: `frontend/src/__tests__/tools-view.spec.ts`

**Interfaces:**
- Consumes the batch endpoint.
- Produces selection that persists across filtering; `Select visible` affects visible Tools only.

- [ ] **Step 1: Write failing selection/partial-result tests**

```ts
it('keeps failed Tools selected and clears successful Tools', async () => {
  renderTools()
  await selectTools([1, 2])
  mockBatch({ succeeded: [{ tool_id: 1, status: 'disabled' }], failed: [{ tool_id: 2, code: 'tools.not_found', params: {} }] })
  await user.click(screen.getByRole('button', { name: 'Disable selected' }))
  expect(toolCheckbox(1)).not.toBeChecked()
  expect(toolCheckbox(2)).toBeChecked()
})
```

Cover select-visible, search changes, collapsed sources, delete confirmation with source count, limit messaging, and locale strings.

- [ ] **Step 2: Run Tools UI tests and record RED**

Run: `npm test -- --run src/__tests__/tools-view.spec.ts`
Expected: no selection or bulk bar.

- [ ] **Step 3: Implement selection set and bulk result reconciliation**

Use a `Set<number>` keyed by Tool ID, independent of rendered groups. After a response, remove succeeded IDs and retain failed IDs.

- [ ] **Step 4: Run Tool UI and build checks**

Run:

```powershell
npm test -- --run src/__tests__/tools-view.spec.ts
npm run typecheck
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: bulk manage tools in administration"
```

---

### Task 12: Build the Scalable Skill Tool Catalog

**Files:**
- Create: `frontend/src/components/ToolCatalogPanel.vue`
- Create: `frontend/src/composables/useToolCatalog.ts`
- Modify: `frontend/src/views/SkillsView.vue`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Test: `frontend/src/__tests__/skills-chat.spec.ts`
- Test: `frontend/src/__tests__/tool-catalog.spec.ts`

**Interfaces:**
- Produces a shared searchable/grouped index for binding and `@tool` references.
- Produces locally stored, failure-tolerant panel height.

- [ ] **Step 1: Write large-catalog search/filter/resize tests**

```ts
it('searches a large catalog by name, description, path, tag, and source', async () => {
  renderCatalog(makeTools(1000))
  for (const query of ['gene_lookup', 'HGNC symbol', '/genes/{symbol}', 'Genomics', 'Varcards']) {
    await user.clear(searchBox())
    await user.type(searchBox(), query)
    expect(visibleToolNames()).toEqual(['gene_lookup'])
  }
})
```

Cover source/tag/enabled filters, hierarchy collapse, dense row metadata, stopped Tool markers, `@tool` insertion, keyboard navigation, resize persistence, and localStorage failure.

- [ ] **Step 2: Run catalog tests and record RED**

Run: `npm test -- --run src/__tests__/tool-catalog.spec.ts src/__tests__/skills-chat.spec.ts`
Expected: current inline list lacks shared index/search/resize behavior.

- [ ] **Step 3: Implement memoized catalog indexing and focused component**

```ts
export function searchableText(tool: ToolSummary): string {
  return [tool.name, tool.description, tool.path, tool.api_source_name, ...tool.tags]
    .filter(Boolean)
    .join('\n')
    .toLocaleLowerCase()
}
```

Use the same filtered/grouped result for the right panel and prompt reference menu. Wrap storage reads/writes in `try/catch` and retain in-memory behavior on failure.

- [ ] **Step 4: Run catalog, Skill, locale, and build checks**

Run:

```powershell
npm test -- --run src/__tests__/tool-catalog.spec.ts src/__tests__/skills-chat.spec.ts src/__tests__/locale-coverage.spec.ts
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat: scale skill tool catalog editing"
```

---

### Task 13: Complete Documentation, Migration Gates, and Browser Acceptance

**Files:**
- Modify: `README.md`
- Modify: `backend/.env.example`
- Modify: deployment/start scripts and documentation discovered by `git grep`
- Modify: affected backend/frontend tests where final public contracts changed
- Create: `docs/tool-session-authentication.md`
- Test: complete backend and frontend suites

**Interfaces:**
- Produces final documented operator and client workflows.
- Verifies every earlier task against a real isolated SQLite database and browser.

- [ ] **Step 1: Update documentation with exact flows**

Document:

- Conda/nvm setup under the new package name;
- multi-Agent creation/default/binding;
- Agent API key creation and one-time secret handling;
- Device Flow, PKCE, injected credential, and Swagger-login Tool Sessions;
- compatible API examples with required key and Tool Session header;
- bulk Tool partial-result semantics; and
- migration/backup procedure.

- [ ] **Step 2: Run fresh and existing migration probes**

Run isolated scripts that prove:

```text
fresh -> head
0007 existing data -> head
head -> 0007 -> head
legacy DB/key filename -> new filename without overwrite
```

Expected: one Alembic head; all rows, secrets, Agent bindings, and conversations preserved.

- [ ] **Step 3: Run complete automated gates serially**

```powershell
conda run -n chat4openapi pytest backend/tests -q
conda run -n chat4openapi ruff check backend/src backend/tests
npm test -- --run --testTimeout=15000
npm run typecheck
npm run build
git diff --check
```

Expected: zero failures and zero lint/type/build errors.

- [ ] **Step 4: Run isolated Playwright CLI acceptance**

Use distinct ports and a temporary SQLite database. Verify:

1. initialize and log in;
2. create two Agents with different bound Skills;
3. create two keys and prove cross-Agent access is 403;
4. Chat selects only an Agent and locks it after sending;
5. each Agent can load only its own Skills;
6. create an injected-credential Tool Session and execute an authenticated Tool;
7. simulate Device/PKCE authorization-required and ready states with a deterministic mock issuer;
8. select Tools across filters and perform a partial-success bulk disable/delete;
9. search a 1,000-Tool Skill catalog and insert an `@tool` reference; and
10. refresh restores Agent-bound history and rendered Markdown.

Stop services and delete only the explicitly verified temporary database, logs, mock server, and browser artifacts.

- [ ] **Step 5: Verify the global rename and clean worktree**

Run a case-insensitive tracked-file scan for the old product/package/environment/header/extension names. Expected: no matches. Confirm `git status --short` contains only intended documentation/test changes before commit.

- [ ] **Step 6: Commit**

```bash
git add README.md backend/.env.example docs backend/tests frontend/src/__tests__
git commit -m "docs: complete Chat4Openapi multi-agent workflows"
```

---

## Final Review Gate

After Task 13:

1. Generate a review package from the plan base SHA to HEAD.
2. Request an independent whole-branch review against the design and this plan.
3. Fix every Critical and Important finding with RED/GREEN tests and re-review.
4. Re-run the complete automated gates and migration probes from fresh output.
5. Report the branch/worktree location and do not merge into the main checkout without explicit authorization.
