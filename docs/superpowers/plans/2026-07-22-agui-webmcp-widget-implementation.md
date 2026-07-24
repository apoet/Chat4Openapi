# AG-UI WebMCP Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream the bound Agent through AG-UI in an embedded Vue Chat and invoke only host-provided WebMCP Tools as client-side Tools.

**Architecture:** Add a small server-side AG-UI adapter around the existing Agent runtime and keep backend versus frontend Tool dispatch explicit. The iframe uses the official AG-UI `HttpAgent`; a zero-dependency bridge progressively observes WebMCP Tools exposed by the host and returns their results through normal AG-UI Tool messages.

**Tech Stack:** FastAPI SSE, existing Agent runtime, Vue 3, TypeScript 5, `@ag-ui/client@0.0.57`, `@ag-ui/core@0.0.57`, Vitest, jsdom.

## Global Constraints

- Execute the Agent bound to the Embed; the Widget has no Agent selector.
- Backend OpenAPI Tools and frontend WebMCP Tools have distinct catalogs and dispatchers; neither falls back to the other.
- Agent-visible WebMCP names use the reserved `web__` prefix.
- Unsupported WebMCP, no registered Tools, or no Tools exposed to the Chat4Openapi origin is silent.
- Accept at most 64 frontend Tools and 256 KiB encoded definitions per run.
- Accept at most 64 KiB arguments and 1 MiB results; time out execution after 30 seconds; execute one frontend Tool at a time.
- Node.js is managed by nvm; run `nvm use 20.19.4` before npm commands.
- Python is managed by Conda; run backend commands with `conda run -n agent4api`.
- Every task follows RED → GREEN → focused regression → review → commit.

---

## File and Responsibility Map

- `backend/src/chat4openapi/agui/contracts.py`: validated AG-UI input and client Tool types.
- `backend/src/chat4openapi/agui/events.py`: JSON SSE event encoding.
- `backend/src/chat4openapi/agui/runtime.py`: existing Agent runtime adapter and dispatch boundary.
- `backend/src/chat4openapi/api/embed_agent.py`: authenticated AG-UI endpoint.
- `frontend/src/embed/webmcp.ts`: capability discovery, name mapping, execution bounds.
- `frontend/src/embed/agent.ts`: `HttpAgent` creation and event subscription.
- `frontend/src/views/EmbedChatView.vue`: fixed-Agent compact Chat.
- `frontend/src/components/EmbedChatPanel.vue`: presentation and responsive interaction.
- `frontend/src/router/index.ts`: public `/embed/:publicId` route.

---

### Task 1: Add AG-UI Contracts and Event Encoding

**Files:**
- Create: `backend/src/chat4openapi/agui/__init__.py`
- Create: `backend/src/chat4openapi/agui/contracts.py`
- Create: `backend/src/chat4openapi/agui/events.py`
- Test: `backend/tests/test_agui_contracts.py`
- Test: `backend/tests/test_agui_events.py`

**Interfaces:**
- Produces: `AguiRunInput`, `AguiTool`, `AguiMessage` Pydantic models.
- Produces: `encode_sse(event: dict[str, Any]) -> str` and standard event factories.

- [ ] **Step 1: Write failing size, prefix, and encoding tests**

```python
def test_client_tool_requires_web_prefix():
    with pytest.raises(ValidationError):
        AguiTool(name="delete", description="x", parameters={"type": "object"})

def test_encode_sse_uses_compact_json():
    assert encode_sse({"type": "RUN_FINISHED", "runId": "r", "threadId": "t"}) == (
        'data: {"type":"RUN_FINISHED","runId":"r","threadId":"t"}\n\n'
    )
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n agent4api pytest backend/tests/test_agui_contracts.py backend/tests/test_agui_events.py -q`

Expected: import failure for `chat4openapi.agui`.

- [ ] **Step 3: Implement bounded protocol models and factories**

```python
class AguiTool(BaseModel):
    name: str = Field(pattern=r"^web__[A-Za-z0-9_.-]{1,128}$", max_length=133)
    description: str = Field(max_length=4_096)
    parameters: dict[str, Any]

def encode_sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"
```

Reject more than 64 Tools, encoded catalogs above 256 KiB, schema depth above 16, and individual schemas above 64 KiB. Define exact factories for `RUN_STARTED`, `TEXT_MESSAGE_START/CONTENT/END`, `TOOL_CALL_START/ARGS/END`, `CUSTOM`, `RUN_FINISHED`, and `RUN_ERROR`.

- [ ] **Step 4: Run protocol tests**

Run: `conda run -n agent4api pytest backend/tests/test_agui_contracts.py backend/tests/test_agui_events.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/chat4openapi/agui backend/tests/test_agui_contracts.py backend/tests/test_agui_events.py
git commit -m "feat: define AG-UI embed protocol"
```

---

### Task 2: Adapt the Agent Runtime to Client-Provided Tools

**Files:**
- Create: `backend/src/chat4openapi/agui/runtime.py`
- Modify: `backend/src/chat4openapi/chat/agent.py`
- Modify: `backend/src/chat4openapi/llm/client.py`
- Test: `backend/tests/test_agui_runtime.py`

**Interfaces:**
- Produces: `AguiRuntime.run(input: AguiRunInput, owner: EmbedSession) -> AsyncIterator[dict[str, Any]]`.
- Produces: `ClientToolCallRequired` carrying `tool_call_id`, `name`, and `arguments`.
- Consumes: existing `AgentRuntime`, backend `ToolExecutor`, and Embed conversation owner.

- [ ] **Step 1: Write failing dispatch-separation tests**

```python
async def test_web_tool_is_emitted_and_never_sent_to_backend_executor(runtime, executor):
    events = [event async for event in runtime.run(run_with_tool("web__select_row"), embed_session)]
    assert [e["type"] for e in events if e["type"].startswith("TOOL_CALL_")] == [
        "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END"
    ]
    executor.execute.assert_not_called()

async def test_backend_tool_still_uses_executor(runtime, executor):
    await collect(runtime.run(run_with_backend_tool("orders_get"), embed_session))
    executor.execute.assert_awaited_once()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `conda run -n agent4api pytest backend/tests/test_agui_runtime.py -q`

Expected: missing AG-UI runtime and client Tool branch.

- [ ] **Step 3: Implement explicit Tool classification**

```python
def classify_tool(name: str, client_tools: dict[str, AguiTool]) -> Literal["client", "backend"]:
    if name.startswith("web__"):
        if name not in client_tools:
            raise AgentError("frontend_tool_unavailable")
        return "client"
    return "backend"
```

When a client Tool is selected, emit the three Tool Call events and end that run. On the next run, accept the matching AG-UI `tool` message and continue reasoning. Preserve existing conversation persistence and use `embed_session_id` as its sole owner.

- [ ] **Step 4: Run runtime and existing Agent tests**

Run: `conda run -n agent4api pytest backend/tests/test_agui_runtime.py backend/tests/test_agent_runtime.py backend/tests/test_chat_turn_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/chat4openapi/agui/runtime.py backend/src/chat4openapi/chat/agent.py backend/src/chat4openapi/llm/client.py backend/tests/test_agui_runtime.py
git commit -m "feat: bridge client Tools into Agent runs"
```

---

### Task 3: Expose the Authenticated AG-UI SSE Endpoint

**Files:**
- Create: `backend/src/chat4openapi/api/embed_agent.py`
- Modify: `backend/src/chat4openapi/main.py`
- Test: `backend/tests/test_embed_agent_api.py`

**Interfaces:**
- Produces: `POST /api/embed/{public_id}/agent` accepting standard `RunAgentInput` and returning `text/event-stream`.
- Consumes: `require_embed_session` and `AguiRuntime.run`.

- [ ] **Step 1: Write failing authentication and stream tests**

```python
def test_agui_endpoint_streams_standard_lifecycle(client, embed_session_headers, embed):
    response = client.post(f"/api/embed/{embed.public_id}/agent", headers=embed_session_headers,
        json=run_input("hello"))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"type":"RUN_STARTED"' in response.text
    assert '"type":"RUN_FINISHED"' in response.text

def test_agui_endpoint_hides_owner_mismatch(client, other_session_headers, embed):
    assert client.post(f"/api/embed/{embed.public_id}/agent", headers=other_session_headers,
                       json=run_input("hello")).status_code == 404
```

- [ ] **Step 2: Run API tests and verify RED**

Run: `conda run -n agent4api pytest backend/tests/test_embed_agent_api.py -q`

Expected: 404 for the endpoint.

- [ ] **Step 3: Implement the streaming route**

```python
@router.post("/api/embed/{public_id}/agent")
async def run_embed_agent(public_id: str, payload: AguiRunInput,
                          session: EmbedSession = Depends(require_embed_session)):
    async def events():
        async for event in get_agui_runtime().run(payload, session):
            yield encode_sse(event)
    return StreamingResponse(events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
```

- [ ] **Step 4: Run endpoint and owner-isolation tests**

Run: `conda run -n agent4api pytest backend/tests/test_embed_agent_api.py backend/tests/test_embed_sessions.py backend/tests/test_agent_runtime.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/chat4openapi/api/embed_agent.py backend/src/chat4openapi/main.py backend/tests/test_embed_agent_api.py
git commit -m "feat: stream embedded Agents over AG-UI"
```

---

### Task 4: Build the WebMCP Bridge and AG-UI Client

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/src/embed/webmcp.ts`
- Create: `frontend/src/embed/agent.ts`
- Modify: `frontend/src/env.d.ts`
- Test: `frontend/src/__tests__/webmcp-bridge.spec.ts`
- Test: `frontend/src/__tests__/embed-agent.spec.ts`

**Interfaces:**
- Produces: `discoverWebMcpTools(parentOrigin: string): Promise<ClientTool[]>` and `executeWebMcpTool(name, args, signal): Promise<string>`.
- Produces: `createEmbedAgent(config: EmbedAgentConfig): HttpAgent`.
- Consumes: delegated `document.modelContext`, `@ag-ui/client`, and `@ag-ui/core`.

- [ ] **Step 1: Install locked AG-UI dependencies and write failing bridge tests**

Run:

```powershell
nvm use 20.19.4
npm install --prefix frontend @ag-ui/client@0.0.57 @ag-ui/core@0.0.57
```

Then add:

```typescript
it('silently returns no tools without both WebMCP capabilities', async () => {
  expect(await discoverWebMcpTools('https://host.example')).toEqual([])
})

it('maps tools exposed by the parent origin into the web namespace', async () => {
  installModelContextWithExecution([{ name: 'select-row', description: 'Select a row', inputSchema: '{"type":"object"}' }])
  expect((await discoverWebMcpTools('https://host.example'))[0].name).toBe('web__select-row')
})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm --prefix frontend test -- --run src/__tests__/webmcp-bridge.spec.ts src/__tests__/embed-agent.spec.ts`

Expected: missing bridge/client modules.

- [ ] **Step 3: Implement progressive discovery and bounded execution**

```typescript
export async function discoverWebMcpTools(parentOrigin: string): Promise<Tool[]> {
  const context = document.modelContext
  if (!context || typeof context.getTools !== 'function' || typeof context.executeTool !== 'function') return []
  const registered = await context.getTools({ fromOrigins: [parentOrigin] })
  return registered.slice(0, 64).flatMap((tool) => {
    try {
      return [{ name: `web__${tool.name}`, description: tool.description,
        parameters: JSON.parse(tool.inputSchema) as Record<string, unknown> }]
    } catch { return [] }
  })
}

export function createEmbedAgent(config: EmbedAgentConfig): HttpAgent {
  return new HttpAgent({ url: config.url, agentId: config.agentId, threadId: config.threadId,
    headers: { Authorization: `Bearer ${config.token}` } })
}
```

Keep the original WebMCP name/origin in a private map and invoke the browser's experimental `document.modelContext.executeTool(originalName, args)` compatibility adapter. Race execution against a 30-second timeout, reject arguments/results above the fixed bounds, listen for `toolchange`, and serialize executions through one promise queue. The July 2026 draft normatively defines `getTools()` while `executeTool()` remains pending in the explainer, so browsers without both functions advertise no frontend Tools. Do not polyfill WebMCP and do not inspect the host DOM.

- [ ] **Step 4: Run bridge/client tests and typecheck**

Run: `npm --prefix frontend test -- --run src/__tests__/webmcp-bridge.spec.ts src/__tests__/embed-agent.spec.ts && npm --prefix frontend run typecheck`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/package.json frontend/package-lock.json frontend/src/embed frontend/src/env.d.ts frontend/src/__tests__/webmcp-bridge.spec.ts frontend/src/__tests__/embed-agent.spec.ts
git commit -m "feat: bridge WebMCP through AG-UI"
```

---

### Task 5: Build the Fixed-Agent Embedded Chat

**Files:**
- Create: `frontend/src/views/EmbedChatView.vue`
- Create: `frontend/src/components/EmbedChatPanel.vue`
- Create: `frontend/src/__tests__/embed-chat.spec.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Modify: `frontend/src/__tests__/locale-coverage.spec.ts`

**Interfaces:**
- Produces: public route `/embed/:publicId` with fixed Agent name, messages, composer, cancel, errors, and close action.
- Consumes: Embed session API, `createEmbedAgent`, and `discoverWebMcpTools`.

- [ ] **Step 1: Write failing fixed-Agent and silent-WebMCP tests**

```typescript
it('renders the bound agent without an agent selector', async () => {
  mockEmbedSession({ agent: { id: 7, name: 'Site Assistant' } })
  const wrapper = mountEmbed('/embed/public-id')
  await flushPromises()
  expect(wrapper.text()).toContain('Site Assistant')
  expect(wrapper.find('[data-testid="agent-select"]').exists()).toBe(false)
})

it('does not show an error when WebMCP is unavailable', async () => {
  const wrapper = mountEmbed('/embed/public-id')
  await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
})
```

- [ ] **Step 2: Run the component tests and verify RED**

Run: `npm --prefix frontend test -- --run src/__tests__/embed-chat.spec.ts`

Expected: missing route and components.

- [ ] **Step 3: Implement the compact Chat lifecycle**

```typescript
async function send(): Promise<void> {
  const text = draft.value.trim()
  if (!text || sending.value) return
  messages.value.push({ id: crypto.randomUUID(), role: 'user', content: text })
  draft.value = ''
  await agent.runAgent({ tools: await discoverWebMcpTools(parentOrigin.value) }, subscriber)
}
```

Initialize from the loader handshake, persist the bearer only in `sessionStorage`, render streamed text, execute completed `web__` calls and append Tool messages for the continuation run, and emit an exact-origin close message. Use a corner panel on desktop and safe-margin near-full-screen layout below 640 px.

- [ ] **Step 4: Run component, locale, type, and production build checks**

Run: `npm --prefix frontend test -- --run src/__tests__/embed-chat.spec.ts src/__tests__/locale-coverage.spec.ts && npm --prefix frontend run build`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/views/EmbedChatView.vue frontend/src/components/EmbedChatPanel.vue frontend/src/router/index.ts frontend/src/styles.css frontend/src/i18n frontend/src/__tests__
git commit -m "feat: add embedded Agent chat widget"
```

---

### Task 6: Runtime Regression Gate

**Files:**
- Modify only files required by failures found in this gate.

**Interfaces:**
- Produces: an AG-UI Widget that works with and without host WebMCP.

- [ ] **Step 1: Run all backend tests and lint**

Run: `conda run -n agent4api ruff check backend && conda run -n agent4api pytest backend/tests -q`

Expected: PASS.

- [ ] **Step 2: Run all frontend tests and build**

Run: `npm --prefix frontend test && npm --prefix frontend run build`

Expected: PASS.

- [ ] **Step 3: Verify Tool namespace isolation**

Run: `git grep -n "web__" -- backend/src frontend/src`

Expected: matches only AG-UI validation/dispatch and the WebMCP bridge; no `web__` branch appears in `tools/executor.py`.

- [ ] **Step 4: Commit gate fixes if the gate changed files**

```powershell
git add backend frontend
git commit -m "test: verify embedded AG-UI runtime"
```
