# Embed Authentication, Administration, and Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete protected Tool authorization for anonymous Embed Sessions, add administrator interfaces, update README imagery, and publish operational guidance to the GitHub Wiki.

**Architecture:** Keep OAuth 2.0 and Swagger login configuration on API Sources, bind resulting Tool Sessions to the Embed Session, and return only a short-lived one-time grant from top-level popups. Extend the existing Vue admin with focused settings and Embed panels, then document detailed operations in the Wiki while READMEs remain concise.

**Tech Stack:** FastAPI, OAuth 2.0 PKCE, encrypted SQLAlchemy persistence, Vue 3, Pinia, Element Plus, TypeScript, Vitest, pytest, GitHub Wiki git repository.

## Global Constraints

- OAuth authorization URL, token URL, optional Device Authorization URL, client ID, encrypted client secret, scopes, and redirect override belong to the API Source.
- Recommended callback URL is `{base_url}/api/tool-sessions/oauth/pkce/callback`; always display the final effective redirect URI.
- Popup URLs and `postMessage` payloads never carry OAuth tokens, Tool Session tokens, or credentials.
- Embed Auth Grants are hashed, single-use, atomically consumed, and expire within five minutes.
- OAuth state is bound to Embed Session, Agent, API Source, and parent origin.
- README files contain only introduction and quick start; detailed architecture and operations go to the GitHub Wiki.
- Node.js is managed by nvm; run `nvm use 20.19.4` before npm commands.
- Python is managed by Conda; run backend commands with `conda run -n chatapi`.
- Every task follows RED → GREEN → focused regression → review → commit.

---

## File and Responsibility Map

- `backend/src/chat4openapi/embed/grants.py`: create/hash/consume single-use authorization grants.
- `backend/src/chat4openapi/tool_sessions/oauth.py`: Embed-bound PKCE state and callback.
- `backend/src/chat4openapi/api/embed_auth.py`: authorization start/exchange/logout endpoints and popup pages.
- `backend/src/chat4openapi/api/tool_oauth.py`: existing callback integration and effective redirect URI.
- `frontend/src/views/SettingsView.vue`: Base URL administration.
- `frontend/src/components/AgentEmbedPanel.vue`: Embed CRUD, script copy, and preview.
- `frontend/src/components/EmbedAuthorization.vue`: popup/grant lifecycle.
- `frontend/src/views/ApiSourcesView.vue`: OAuth source fields and derived callback display.
- `README.md`, `README.zh-CN.md`: demo image beneath the workflow image.
- GitHub Wiki pages: Embed, authorization, WebMCP, security, and operations.

---

### Task 1: Create and Atomically Consume Embed Auth Grants

**Files:**
- Create: `backend/src/chat4openapi/embed/grants.py`
- Test: `backend/tests/test_embed_auth_grants.py`

**Interfaces:**
- Produces: `create_auth_grant(db, embed_session_id, tool_session_id, api_source_id) -> str`.
- Produces: `consume_auth_grant(db, code, embed_session_id) -> EmbedAuthGrant`.

- [ ] **Step 1: Write failing expiry, ownership, and replay tests**

```python
def test_grant_is_single_use(db, embed_session, tool_session, source):
    code = create_auth_grant(db, embed_session.id, tool_session.id, source.id)
    grant = consume_auth_grant(db, code, embed_session.id)
    assert grant.tool_session_id == tool_session.id
    with pytest.raises(AuthGrantError, match="invalid_or_expired"):
        consume_auth_grant(db, code, embed_session.id)

def test_grant_rejects_other_embed_owner(db, grant_code, other_embed_session):
    with pytest.raises(AuthGrantError, match="invalid_or_expired"):
        consume_auth_grant(db, grant_code, other_embed_session.id)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n chatapi pytest backend/tests/test_embed_auth_grants.py -q`

Expected: missing grants module.

- [ ] **Step 3: Implement hashed, transactional grants**

```python
def consume_auth_grant(db: Session, code: str, embed_session_id: int) -> EmbedAuthGrant:
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    now = datetime.now(UTC)
    result = db.execute(update(EmbedAuthGrant).where(
        EmbedAuthGrant.code_hash == code_hash,
        EmbedAuthGrant.embed_session_id == embed_session_id,
        EmbedAuthGrant.consumed_at.is_(None), EmbedAuthGrant.expires_at > now,
    ).values(consumed_at=now).returning(EmbedAuthGrant.id))
    grant_id = result.scalar_one_or_none()
    if grant_id is None:
        raise AuthGrantError("invalid_or_expired")
    return db.get_one(EmbedAuthGrant, grant_id)
```

Generate 32 random bytes, store SHA-256 only, and set expiry to `min(now + five minutes, embed_session.absolute_expires_at)`.

- [ ] **Step 4: Run grant and concurrency tests**

Run: `conda run -n chatapi pytest backend/tests/test_embed_auth_grants.py backend/tests/test_admin_write_concurrency.py -q`

Expected: PASS and exactly one concurrent consumer succeeds.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/chat4openapi/embed/grants.py backend/tests/test_embed_auth_grants.py
git commit -m "feat: issue one-time Embed auth grants"
```

---

### Task 2: Bind OAuth PKCE and Swagger Login to Embed Sessions

**Files:**
- Modify: `backend/src/chat4openapi/tool_sessions/oauth.py`
- Modify: `backend/src/chat4openapi/tool_sessions/service.py`
- Modify: `backend/src/chat4openapi/api/tool_oauth.py`
- Create: `backend/src/chat4openapi/api/embed_auth.py`
- Modify: `backend/src/chat4openapi/main.py`
- Test: `backend/tests/test_embed_oauth.py`
- Test: `backend/tests/test_embed_swagger_login.py`

**Interfaces:**
- Produces: `POST /api/embed/sessions/{session_id}/auth/start`.
- Produces: `POST /api/embed/sessions/{session_id}/auth/exchange`.
- Produces: Embed logout/revocation action.
- Consumes: existing source OAuth config and `create_auth_grant` / `consume_auth_grant`.

- [ ] **Step 1: Write failing PKCE binding and popup tests**

```python
def test_embed_pkce_state_binds_origin(client, embed_headers, source):
    response = client.post("/api/embed/sessions/current/auth/start", headers=embed_headers,
                           json={"api_source_id": source.id, "flow": "pkce"})
    state = decrypt_state(query_value(response.json()["authorization_url"], "state"))
    assert state["parent_origin"] == "https://docs.example"
    assert state["embed_session_id"]

def test_callback_returns_grant_not_tokens(client, completed_embed_callback):
    body = completed_embed_callback.text
    assert "chat4openapi:auth-grant" in body
    assert "access_token" not in body
    assert "tool_session" not in body
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n chatapi pytest backend/tests/test_embed_oauth.py backend/tests/test_embed_swagger_login.py -q`

Expected: missing Embed auth endpoints/owner support.

- [ ] **Step 3: Implement the owner-aware authorization lifecycle**

```python
def popup_result_page(grant: str, target_origin: str) -> HTMLResponse:
    payload = json.dumps({"type": "chat4openapi:auth-grant", "grant": grant})
    origin = json.dumps(target_origin)
    return HTMLResponse(f"<script>window.opener.postMessage({payload}, {origin});window.close()</script>",
                        headers={"Cache-Control": "no-store"})
```

Create the Tool Session with only `embed_session_id`; bind encrypted PKCE state to session/Agent/source/origin; use the source's effective redirect URI; validate and consume state before token exchange; create a grant after storing encrypted credentials. Swagger login posts credentials to Chat4Openapi over HTTPS, executes the configured login Tool once, clears the request body from logs, and returns through the same grant page.

- [ ] **Step 4: Run Embed and existing OAuth/Tool Session regressions**

Run: `conda run -n chatapi pytest backend/tests/test_embed_oauth.py backend/tests/test_embed_swagger_login.py backend/tests/test_tool_oauth.py backend/tests/test_tool_sessions.py backend/tests/test_tool_session_credentials.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/chat4openapi/tool_sessions backend/src/chat4openapi/api/embed_auth.py backend/src/chat4openapi/api/tool_oauth.py backend/src/chat4openapi/main.py backend/tests/test_embed_oauth.py backend/tests/test_embed_swagger_login.py
git commit -m "feat: authorize Embed Tool Sessions"
```

---

### Task 3: Add Widget Authorization UI

**Files:**
- Create: `frontend/src/components/EmbedAuthorization.vue`
- Modify: `frontend/src/views/EmbedChatView.vue`
- Modify: `frontend/src/api/contracts.ts`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Test: `frontend/src/__tests__/embed-authorization.spec.ts`

**Interfaces:**
- Produces: authorization-required prompt, popup launch, exact-origin grant listener, exchange, retry, and logout.
- Consumes: AG-UI `CUSTOM` event `{name: "authorization_required", value: {api_source_id, api_source_name}}`.

- [ ] **Step 1: Write failing popup and grant validation tests**

```typescript
it('opens authorization only from the user button', async () => {
  const open = vi.spyOn(window, 'open').mockReturnValue(fakePopup())
  const wrapper = mountAuthorization()
  expect(open).not.toHaveBeenCalled()
  await wrapper.get('[data-testid="authorize"]').trigger('click')
  expect(open).toHaveBeenCalledOnce()
})

it('ignores grants from another origin or window', async () => {
  const wrapper = mountAuthorization()
  dispatchMessage({ origin: 'https://evil.example', source: window, data: validGrant })
  expect(exchangeGrant).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm --prefix frontend test -- --run src/__tests__/embed-authorization.spec.ts`

Expected: missing component and contracts.

- [ ] **Step 3: Implement popup lifecycle**

```typescript
function onGrant(event: MessageEvent<AuthGrantMessage>): void {
  if (event.origin !== chatOrigin || event.source !== popup.value) return
  if (event.data?.type !== 'chat4openapi:auth-grant') return
  void exchange(event.data.grant)
}

function authorize(): void {
  popup.value = window.open(authUrl.value, 'chat4openapi-auth', 'popup,width=520,height=720')
  if (!popup.value) error.value = t('embed.popupBlocked')
}
```

Handle cancellation, expired grant, failed exchange, logout, and a retry that replays the user's intent but never automatically repeats a completed Tool call.

- [ ] **Step 4: Run authorization, Widget, locale, and build checks**

Run: `npm --prefix frontend test -- --run src/__tests__/embed-authorization.spec.ts src/__tests__/embed-chat.spec.ts src/__tests__/locale-coverage.spec.ts && npm --prefix frontend run build`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/EmbedAuthorization.vue frontend/src/views/EmbedChatView.vue frontend/src/api/contracts.ts frontend/src/i18n frontend/src/__tests__/embed-authorization.spec.ts
git commit -m "feat: authorize protected Tools in Widget"
```

---

### Task 4: Add System Settings, Embed Management, and Source Callback UI

**Files:**
- Create: `frontend/src/views/SettingsView.vue`
- Create: `frontend/src/components/AgentEmbedPanel.vue`
- Create: `frontend/src/stores/settings.ts`
- Create: `frontend/src/stores/embeds.ts`
- Modify: `frontend/src/components/AgentEditor.vue`
- Modify: `frontend/src/views/ApiSourcesView.vue`
- Modify: `frontend/src/api/contracts.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/layouts/AdminLayout.vue`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Test: `frontend/src/__tests__/settings-view.spec.ts`
- Test: `frontend/src/__tests__/agent-embed-panel.spec.ts`
- Test: `frontend/src/__tests__/api-source-oauth.spec.ts`

**Interfaces:**
- Produces: administrator `/admin/settings` route.
- Produces: multi-Embed CRUD panel on saved Agents, script copy, and preview.
- Produces: recommended and effective OAuth redirect URI display on API Sources.

- [ ] **Step 1: Write failing management UI tests**

```typescript
it('disables script copy until Base URL exists', async () => {
  mockSettings({ base_url: null })
  const wrapper = mountAgentEmbedPanel()
  await flushPromises()
  expect(wrapper.get('[data-testid="copy-script"]').attributes('disabled')).toBeDefined()
})

it('shows the source effective callback URI', async () => {
  mockSourceOAuth({ recommended_redirect_uri: 'https://chat.example/api/tool-sessions/oauth/pkce/callback',
                    effective_redirect_uri: 'https://override.example/callback' })
  const wrapper = mountApiSources()
  await flushPromises()
  expect(wrapper.text()).toContain('https://override.example/callback')
})
```

- [ ] **Step 2: Run management tests and verify RED**

Run: `npm --prefix frontend test -- --run src/__tests__/settings-view.spec.ts src/__tests__/agent-embed-panel.spec.ts src/__tests__/api-source-oauth.spec.ts`

Expected: missing views, stores, and UI controls.

- [ ] **Step 3: Implement typed stores and focused components**

```typescript
export interface AgentEmbedConfig {
  id: number; agent_id: number; name: string; public_id: string; enabled: boolean
  allowed_origins: string[]; position: 'bottom_right' | 'bottom_left'; script: string | null
}

async function copyScript(embed: AgentEmbedConfig): Promise<void> {
  if (!embed.script) return
  await navigator.clipboard.writeText(embed.script)
  copiedId.value = embed.id
}
```

Settings normalizes on the server and renders field errors. The Embed panel supports multiple configurations, exact-origin rows, left/right position, enable/disable/delete, copy, and a preview using current Base URL. Keep OAuth and Swagger fields in `ApiSourcesView.vue`; do not duplicate them in Agent/Embed forms.

- [ ] **Step 4: Run management, locale, router, and build checks**

Run: `npm --prefix frontend test -- --run src/__tests__/settings-view.spec.ts src/__tests__/agent-embed-panel.spec.ts src/__tests__/api-source-oauth.spec.ts src/__tests__/router-guards.spec.ts src/__tests__/locale-coverage.spec.ts && npm --prefix frontend run build`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/views frontend/src/components/AgentEmbedPanel.vue frontend/src/stores frontend/src/api/contracts.ts frontend/src/router/index.ts frontend/src/layouts/AdminLayout.vue frontend/src/i18n frontend/src/__tests__
git commit -m "feat: manage Agent embeds in admin"
```

---

### Task 5: Add Browser Integration Fixtures and End-to-End Coverage

**Files:**
- Create: `frontend/e2e/fixtures/embed-host-webmcp.html`
- Create: `frontend/e2e/fixtures/embed-host-basic.html`
- Create: `frontend/e2e/embed-widget.spec.ts`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

**Interfaces:**
- Produces: controlled host fixtures with and without WebMCP.
- Verifies: loader → iframe → AG-UI → optional WebMCP → Tool Result → Agent response and authorization popup/grant.

- [ ] **Step 1: Add Playwright and write failing browser scenarios**

Run: `npm install --prefix frontend --save-dev @playwright/test`

```typescript
test('executes an exposed host WebMCP Tool', async ({ page }) => {
  await page.goto('/e2e/fixtures/embed-host-webmcp.html')
  await page.getByRole('button', { name: 'Open chat' }).click()
  const widget = page.frameLocator('iframe[title="Chat4Openapi"]')
  await widget.getByRole('textbox').fill('Select order 42')
  await widget.getByRole('button', { name: 'Send' }).click()
  await expect(page.locator('#selected-order')).toHaveText('42')
})

test('works silently when WebMCP is absent', async ({ page }) => {
  await page.goto('/e2e/fixtures/embed-host-basic.html')
  await page.getByRole('button', { name: 'Open chat' }).click()
  await expect(page.getByText(/WebMCP unavailable/i)).toHaveCount(0)
})
```

- [ ] **Step 2: Run browser tests and verify RED**

Run: `npm --prefix frontend exec playwright test frontend/e2e/embed-widget.spec.ts`

Expected: fixture or flow failure before server/test harness wiring is complete.

- [ ] **Step 3: Implement deterministic fixtures and test harness**

```javascript
await document.modelContext.registerTool({
  name: 'select-order', description: 'Select an order in the host page',
  inputSchema: { type: 'object', properties: { id: { type: 'string' } }, required: ['id'] },
  execute: async ({ id }) => { document.querySelector('#selected-order').textContent = id; return { selected: id } },
}, { exposedTo: ['http://127.0.0.1:8000'] })
```

Serve the fixture from a distinct origin, configure `allow="tools"`, seed one enabled Embed/Agent, stub the deterministic LLM selection in test mode, and include popup/grant replay tests.

- [ ] **Step 4: Run both browser scenarios**

Run: `npm --prefix frontend exec playwright test frontend/e2e/embed-widget.spec.ts`

Expected: PASS in a WebMCP-capable browser; unsupported-project coverage must skip only the WebMCP action test and still run the basic Widget test.

- [ ] **Step 5: Commit**

```powershell
git add frontend/e2e frontend/package.json frontend/package-lock.json
git commit -m "test: cover embedded Agent browser flows"
```

---

### Task 6: Update README and Publish Detailed Wiki Documentation

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Add to git: `docs/images/demo.png`
- Modify Wiki checkout: `Home.md`, `Embedding-Agents.md`, `Authentication.md`, `WebMCP.md`, `Security-and-Operations.md`, `_Sidebar.md`

**Interfaces:**
- Produces: localized README demo image immediately under each workflow image.
- Produces: detailed public administrator/operator documentation in the repository Wiki.

- [ ] **Step 1: Add the README image references**

```markdown
![Chat4Openapi management and chat demo](docs/images/demo.png)
```

```markdown
![Chat4Openapi 管理后台与对话演示](docs/images/demo.png)
```

Place each line immediately after its localized workflow image and keep both README files limited to introduction and quick start.

- [ ] **Step 2: Write the Wiki pages with exact operational examples**

Include the generated snippet, Base URL setup, origin allow-list behavior, iframe architecture, `allow="tools"`, WebMCP `exposedTo`, backend/frontend Tool separation, source-level OAuth fields, effective callback URI, anonymous versus protected Tool behavior, session/grant expiry, revocation, CSP, troubleshooting, and deployment checklist.

Prepare the exact sibling checkout before editing it:

```powershell
$wikiPath = 'E:\SourceCode\git\ChatAPI.wiki'
if (Test-Path (Join-Path $wikiPath '.git')) {
  git -C $wikiPath pull --ff-only
} else {
  git clone https://github.com/apoet/Chat4Openapi.wiki.git $wikiPath
}
```

```html
<script src="https://chat.example.com/embed/PUBLIC_ID.js" async></script>
```

- [ ] **Step 3: Validate README scope, links, and image presence**

Run:

```powershell
Test-Path docs/images/demo.png
rg -n "demo.png|workflow" README.md README.zh-CN.md
rg -n "Architecture|架构|Feature matrix|功能矩阵" README.md README.zh-CN.md
```

Expected: image exists; workflow precedes demo in both files; the detailed-section scan is empty.

- [ ] **Step 4: Commit product documentation and publish Wiki**

```powershell
git add README.md README.zh-CN.md docs/images/demo.png
git commit -m "docs: show Agent workflow demo"
$wikiPath = 'E:\SourceCode\git\ChatAPI.wiki'
git -C $wikiPath add Home.md Embedding-Agents.md Authentication.md WebMCP.md Security-and-Operations.md _Sidebar.md
git -C $wikiPath commit -m "docs: explain Agent embedding and authorization"
git -C $wikiPath push origin master
```

Expected: both commits succeed and the Wiki push updates the existing GitHub Wiki repository.

---

### Task 7: Final Security and Release Gate

**Files:**
- Modify only files required by failures found in this gate.

**Interfaces:**
- Produces: release-ready Embed, authorization, administration, tests, README, and Wiki.

- [ ] **Step 1: Run the complete backend gate**

Run: `conda run -n chatapi ruff check backend && conda run -n chatapi pytest backend/tests -q`

Expected: PASS.

- [ ] **Step 2: Run the complete frontend gate**

Run: `npm --prefix frontend test && npm --prefix frontend run build && npm --prefix frontend exec playwright test frontend/e2e/embed-widget.spec.ts`

Expected: PASS, subject only to the documented WebMCP browser capability skip.

- [ ] **Step 3: Run security-focused source scans**

Run:

```powershell
git grep -n -E "targetOrigin: ['\"]\*|postMessage\([^,]+, ['\"]\*" -- frontend backend
git grep -n -E "access_token|refresh_token|client_secret" -- frontend/src/embed frontend/src/components/EmbedAuthorization.vue
git diff --check HEAD~1
```

Expected: wildcard messaging and frontend token scans are empty; diff check passes.

- [ ] **Step 4: Verify migrations from empty and 0012 databases**

Run: `conda run -n chatapi pytest backend/tests/test_database.py backend/tests/test_embed_migration.py backend/tests/test_final_migration_acceptance.py -q`

Expected: PASS with downgrade/re-upgrade and existing owner preservation.

- [ ] **Step 5: Commit gate fixes if the gate changed files**

```powershell
git add backend frontend README.md README.zh-CN.md docs/images/demo.png
git commit -m "test: complete Agent embed release gate"
```
