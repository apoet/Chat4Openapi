# Agent Runtime and Markdown Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every conversation through one configurable Agent that dynamically loads multiple candidate Skills, clarifies missing parameters in browser Chat, executes Tools without approval, renders safe Markdown tables, and uses editable Tool parameter guidance.

**Architecture:** Add singleton Agent configuration and per-conversation Agent state to SQLite, then replace the Skill-owned orchestration entry point with an application-owned `route → load → clarify/act → observe → respond` state machine. Browser Chat uses a structured turn API and human-in-loop clarification; OpenAI/Anthropic compatibility endpoints use the same Agent in non-interactive ReAct mode. Skills become provider-free prompt/Tool packages, while effective Tool schemas merge Swagger structure with administrator description/example overrides.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, HTTPX, pytest, Vue 3, Pinia, TypeScript, Vitest, markdown-it, DOMPurify, SQLite.

## Global Constraints

- Python commands run through Conda environment `chatapi`.
- Node.js commands run through the nvm-managed executables under `D:\nvm\nodejs`.
- English and Simplified Chinese are required; English remains the default locale.
- The system has exactly one built-in Agent; multiple Agents and Agent delegation are out of scope.
- Tool calls execute automatically and never require user approval.
- Human-in-loop only clarifies missing, ambiguous, or choice-dependent inputs.
- Browser Chat honors `human_in_loop`; OpenAI/Anthropic compatibility APIs always use non-interactive ReAct behavior.
- Skills do not own an LLM provider or model.
- Empty candidate Skill selection means all running Skills; a non-empty multi-selection restricts routing.
- Raw HTML in assistant Markdown is disabled and sanitized output is mandatory.
- Swagger owns parameter name, type, required state, location, and execution mapping; administrators may override only description and example.
- Preserve all unrelated existing working-tree changes and stage only files belonging to each task.

---

## File Structure

### Backend files to create

- `backend/migrations/versions/0005_agent_runtime.py`: schema migration and existing-provider backfill.
- `backend/src/chatapi/models/agent.py`: singleton `AgentConfig` model.
- `backend/src/chatapi/models/tool_parameter.py`: `ToolParameterOverride` model.
- `backend/src/chatapi/schemas/agents.py`: Agent administration contracts.
- `backend/src/chatapi/schemas/chat.py`: browser turn contracts and Agent statuses.
- `backend/src/chatapi/api/admin_agent.py`: singleton Agent administration API.
- `backend/src/chatapi/chat/agent.py`: Agent state machine and control actions.
- `backend/src/chatapi/chat/context.py`: persisted/canonical message conversion and effective Skill context loading.
- `backend/src/chatapi/tools/effective_schema.py`: merge and reconcile parameter overrides.
- `backend/tests/test_agent_models.py`: migration/model behavior.
- `backend/tests/test_agent_api.py`: Agent administration behavior.
- `backend/tests/test_agent_runtime.py`: routing, loading, clarification, resume, and Tool loop behavior.
- `backend/tests/test_chat_turn_api.py`: browser structured turn endpoint.
- `backend/tests/test_tool_parameter_overrides.py`: effective schema and refresh behavior.

### Frontend files to create

- `frontend/src/stores/agent.ts`: Agent administration state and requests.
- `frontend/src/views/AgentView.vue`: singleton Agent settings page.
- `frontend/src/components/MarkdownMessage.vue`: sanitized Markdown renderer.
- `frontend/src/components/SkillMultiSelect.vue`: accessible candidate Skill multi-select.
- `frontend/src/__tests__/agent-view.spec.ts`: Agent administration tests.
- `frontend/src/__tests__/markdown-message.spec.ts`: Markdown and sanitization tests.

### Existing files to modify

- Backend models, schemas, routers, Skill API, Tool API/refresh, Chat API/runtime, main app, and tests.
- Frontend router, navigation, contracts, Skills/Tools/Chat views, stores, styles, localization, dependencies, and tests.

---

### Task 1: Agent and conversation persistence

**Files:**
- Create: `backend/migrations/versions/0005_agent_runtime.py`
- Create: `backend/src/chatapi/models/agent.py`
- Create: `backend/src/chatapi/models/tool_parameter.py`
- Modify: `backend/src/chatapi/models/conversation.py`
- Modify: `backend/src/chatapi/models/skill.py`
- Modify: `backend/src/chatapi/models/__init__.py`
- Test: `backend/tests/test_agent_models.py`
- Modify: `backend/tests/test_database.py`

**Interfaces:**
- Produces: `AgentConfig`, `ToolParameterOverride`, and Agent state columns on `Conversation`.
- Produces: provider-free `Skill` model used by every later task.

- [ ] **Step 1: Write failing migration/model tests**

Create tests that migrate a database containing an enabled provider and an existing Skill, then assert:

```python
agent = session.get(AgentConfig, 1)
assert agent.provider_id == provider.id
assert agent.mode == "human_in_loop"
assert agent.max_iterations == 8
assert not hasattr(skill, "provider_id")

conversation = Conversation()
session.add(conversation)
session.flush()
assert conversation.candidate_skill_ids == []
assert conversation.loaded_skill_ids == []
assert conversation.agent_status == "running"
assert conversation.pending_clarification is None
```

Also assert a `ToolParameterOverride(tool_id, argument_name)` pair is unique and cascades when its Tool is deleted.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
conda run -n chatapi pytest backend/tests/test_agent_models.py backend/tests/test_database.py -q
```

Expected: collection/import failures for missing Agent models or missing migration columns.

- [ ] **Step 3: Add models and migration**

Implement the singleton with these exact fields:

```python
class AgentConfig(Base):
    __tablename__ = "agent_config"
    __table_args__ = (CheckConstraint("id = 1", name="ck_single_agent_config"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String(160), default="ChatAPI Agent")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    system_prompt: Mapped[str] = mapped_column(Text)
    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_providers.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), default="human_in_loop")
    max_iterations: Mapped[int] = mapped_column(Integer, default=8)
```

Implement parameter overrides:

```python
class ToolParameterOverride(Base):
    __tablename__ = "tool_parameter_overrides"
    __table_args__ = (
        UniqueConstraint("tool_id", "argument_name", name="uq_tool_parameter_override"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tool_id: Mapped[int] = mapped_column(
        ForeignKey("tools.id", ondelete="CASCADE"), index=True
    )
    argument_name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    example: Mapped[Any | None] = mapped_column(JSON, nullable=True)
```

Add `candidate_skill_ids`, `loaded_skill_ids`, `agent_mode`, `agent_status`, and `pending_clarification` to `Conversation`. Use JSON arrays with callable Python defaults and server defaults of `[]` in the migration. Remove `provider_id` and `model` from `Skill` through Alembic batch table alteration so SQLite is supported. Before removing them, create Agent row ID 1 and set `provider_id` to the lowest enabled, non-deleted provider ID.

- [ ] **Step 4: Upgrade a disposable database and run tests**

Run:

```powershell
conda run -n chatapi pytest backend/tests/test_agent_models.py backend/tests/test_database.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit persistence changes**

```powershell
git add backend/migrations/versions/0005_agent_runtime.py backend/src/chatapi/models backend/tests/test_agent_models.py backend/tests/test_database.py
git commit -m "feat: add agent conversation persistence"
```

---

### Task 2: Singleton Agent administration and provider-free Skills

**Files:**
- Create: `backend/src/chatapi/schemas/agents.py`
- Create: `backend/src/chatapi/api/admin_agent.py`
- Modify: `backend/src/chatapi/schemas/skills.py`
- Modify: `backend/src/chatapi/api/admin_skills.py`
- Modify: `backend/src/chatapi/main.py`
- Create: `backend/tests/test_agent_api.py`
- Modify: `backend/tests/test_skills_api.py`

**Interfaces:**
- Produces: `GET /api/admin/agent`, `PUT /api/admin/agent`, and `POST /api/admin/agent/reset`.
- Produces: Skill responses/writes with no `provider_id` or `model`.

- [ ] **Step 1: Write failing API tests**

Test that authenticated administrators can read/update/reset this exact contract:

```json
{
  "id": 1,
  "name": "ChatAPI Agent",
  "enabled": true,
  "system_prompt": "...",
  "provider_id": 1,
  "model": null,
  "mode": "human_in_loop",
  "max_iterations": 8
}
```

Assert `mode="invalid"`, `max_iterations=0`, a disabled provider, and a deleted provider are rejected. Update Skill API tests so create/update payloads contain only `name`, `description`, `system_prompt`, and `tool_ids` and returned Skills contain neither provider nor model fields.

- [ ] **Step 2: Run tests and verify RED**

```powershell
conda run -n chatapi pytest backend/tests/test_agent_api.py backend/tests/test_skills_api.py -q
```

Expected: Agent routes return 404 and old Skill schema expectations fail.

- [ ] **Step 3: Implement contracts and routes**

Use literals and bounds:

```python
class AgentConfigWrite(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    system_prompt: str = Field(min_length=1, max_length=100_000)
    provider_id: int
    model: str | None = Field(default=None, max_length=256)
    mode: Literal["human_in_loop", "react"] = "human_in_loop"
    max_iterations: int = Field(default=8, ge=2, le=32)
```

Define `DEFAULT_AGENT_PROMPT` in `admin_agent.py` for this task; Task 4 moves it to the Agent runtime module when the control protocol exists. `reset` preserves the current valid provider, resets name/prompt/mode/max iterations, and enables the Agent. Validate providers with the same enabled/deleted rules used elsewhere.

Remove Skill provider validation and fields from `_write_skill`, `SkillWriteRequest`, `SkillResponse`, and Skill start validation. Starting a Skill validates only its Tool bindings.

- [ ] **Step 4: Run focused tests**

```powershell
conda run -n chatapi pytest backend/tests/test_agent_api.py backend/tests/test_skills_api.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit Agent administration**

```powershell
git add backend/src/chatapi/api/admin_agent.py backend/src/chatapi/schemas/agents.py backend/src/chatapi/api/admin_skills.py backend/src/chatapi/schemas/skills.py backend/src/chatapi/main.py backend/tests/test_agent_api.py backend/tests/test_skills_api.py
git commit -m "feat: configure the built-in agent"
```

---

### Task 3: Effective Tool parameter guidance

**Files:**
- Create: `backend/src/chatapi/tools/effective_schema.py`
- Modify: `backend/src/chatapi/schemas/tools.py`
- Modify: `backend/src/chatapi/api/admin_tools.py`
- Modify: `backend/src/chatapi/api/admin_skills.py`
- Create: `backend/tests/test_tool_parameter_overrides.py`
- Modify: `backend/tests/test_tool_api.py`

**Interfaces:**
- Produces: `effective_input_schema(db: Session, tool: Tool) -> dict[str, Any]`.
- Produces: `PUT /api/admin/tools/{tool_id}/parameters/{argument_name}`.
- Produces: `reconcile_parameter_overrides(db, tool)` called after source refresh.

- [ ] **Step 1: Write failing merge and reconciliation tests**

Test a Tool with imported `description="Swagger text"`, then create an override and assert:

```python
effective = effective_input_schema(session, tool)
assert effective["properties"]["gene"]["description"] == "HGNC gene symbol"
assert effective["properties"]["gene"]["example"] == "ABCA4"
assert effective["properties"]["gene"]["type"] == "string"
assert effective["required"] == ["gene"]
```

Refresh the Tool with the same argument and assert preservation; refresh without the argument and assert the override is deleted. API tests must reject unknown arguments and must not accept type/location/required fields.

- [ ] **Step 2: Run tests and verify RED**

```powershell
conda run -n chatapi pytest backend/tests/test_tool_parameter_overrides.py backend/tests/test_tool_api.py -q
```

Expected: missing module/route failures.

- [ ] **Step 3: Implement effective schema service and API**

Implement a deep-copy merge:

```python
def effective_input_schema(db: Session, tool: Tool) -> dict[str, Any]:
    schema = deepcopy(tool.input_schema)
    properties = schema.setdefault("properties", {})
    overrides = db.scalars(select(ToolParameterOverride).where(
        ToolParameterOverride.tool_id == tool.id
    )).all()
    for override in overrides:
        parameter = properties.get(override.argument_name)
        if not isinstance(parameter, dict):
            continue
        if override.description is not None:
            parameter["description"] = override.description
        if override.example is not None:
            parameter["example"] = override.example
    return schema
```

The write schema contains only nullable `description` and `example`. Empty/blank descriptions become `None`; a payload with both values null deletes the override. Return the refreshed `ToolSummary` using the effective schema. Make `_response` for Skills and eligible Tools also return effective schemas so Agent/Skill editors see the same guidance.

Call reconciliation immediately after a refreshed Tool receives its latest `input_schema`; delete override rows whose `argument_name` is absent from `properties`.

- [ ] **Step 4: Run focused tests**

```powershell
conda run -n chatapi pytest backend/tests/test_tool_parameter_overrides.py backend/tests/test_tool_api.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit parameter guidance**

```powershell
git add backend/src/chatapi/tools/effective_schema.py backend/src/chatapi/schemas/tools.py backend/src/chatapi/api/admin_tools.py backend/src/chatapi/api/admin_skills.py backend/tests/test_tool_parameter_overrides.py backend/tests/test_tool_api.py
git commit -m "feat: edit tool parameter guidance"
```

---

### Task 4: Built-in Agent state machine

**Files:**
- Create: `backend/src/chatapi/chat/context.py`
- Create: `backend/src/chatapi/chat/agent.py`
- Modify: `backend/src/chatapi/chat/orchestrator.py`
- Create: `backend/tests/test_agent_runtime.py`
- Modify: `backend/tests/test_chat_orchestrator.py`

**Interfaces:**
- Produces: `AgentRuntime.run(AgentTurnRequest) -> AgentTurnResult`.
- Produces: `AgentTurnRequest(conversation_id, user_content, candidate_skill_ids, interactive, tool_session_id)`.
- Produces: statuses `completed`, `needs_input`, and structured failures.

- [ ] **Step 1: Write failing routing/loading test**

Use a sequenced fake LLM that first calls `load_skills` with one Skill, then calls a bound Tool, then returns a Markdown table. Assert the first LLM call receives only Skill catalog metadata plus the `load_skills` control Tool; the second receives only Tools from the loaded Skill; and the final result contains `loaded_skill_ids`.

The core request/result types are:

```python
@dataclass(frozen=True, slots=True)
class AgentTurnRequest:
    user_content: str
    candidate_skill_ids: list[int]
    interactive: bool
    conversation_id: str | None = None
    tool_session_id: str | None = None

@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    conversation_id: str
    status: Literal["completed", "needs_input"]
    content: str
    loaded_skill_ids: list[int]
    pending: dict[str, Any] | None
    input_tokens: int
    output_tokens: int
```

- [ ] **Step 2: Run the routing test and verify RED**

```powershell
conda run -n chatapi pytest backend/tests/test_agent_runtime.py::test_routes_loads_skill_and_executes_only_bound_tools -q
```

Expected: import failure for `AgentRuntime`.

- [ ] **Step 3: Implement routing and dynamic loading**

Move the approved default prompt into `agent.py`. Add control schemas:

```python
LOAD_SKILLS_TOOL = CanonicalTool(
    name="load_skills",
    description="Load one or more Skills required for the current task.",
    input_schema={
        "type": "object",
        "properties": {"skill_ids": {"type": "array", "items": {"type": "integer"}}},
        "required": ["skill_ids"],
    },
)
ASK_USER_TOOL = CanonicalTool(
    name="ask_user",
    description="Pause and ask the user for missing or ambiguous business input.",
    input_schema={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "reason": {"type": "string"},
            "fields": {"type": "array", "items": {"type": "string"}},
            "choices": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["question", "reason", "fields"],
    },
)
```

Build the initial system context from Agent prompt plus a JSON Skill catalog containing IDs, names, and descriptions. Validate candidate IDs are running and non-deleted. Empty candidates query all running Skills. After `load_skills`, persist unique ordered IDs and expose effective schemas only for enabled Tools bound to those Skills.

- [ ] **Step 4: Write and verify a failing clarification/resume test**

The fake LLM calls `load_skills`, then `ask_user`. Assert interactive execution returns `needs_input`, stores `pending_clarification` including the Tool call ID, and performs no business Tool call. Resume with `GRCh38`; assert the next LLM context includes an internal Tool result containing that answer and finishes normally.

```powershell
conda run -n chatapi pytest backend/tests/test_agent_runtime.py::test_human_in_loop_pauses_and_resumes_without_tool_approval -q
```

Expected: FAIL because `ask_user` is not handled.

- [ ] **Step 5: Implement clarification and canonical history**

In interactive `human_in_loop` mode expose `ASK_USER_TOOL`. Persist control calls in `ChatMessage.content` as `{text, tool_calls}` and observations as `{text, tool_call_id, name}`. On resume, convert the user's answer into an internal `tool` observation for the pending `ask_user` call, clear pending state, and continue. Do not expose `ASK_USER_TOOL` when `interactive=False` or Agent mode is `react`.

`context.py` must reconstruct `CanonicalMessage` objects from persisted content, JSON-serialize Tool results for OpenAI through the existing adapter, and prepend current Agent/loaded Skill system messages without duplicating stored incoming messages.

- [ ] **Step 6: Write and implement multi-Skill and failure tests**

Add tests for two loaded Skills in a compound task, invalid loads, stopped candidates, Tool failure recovery, and max iteration exhaustion. The runtime converts Tool errors into observations so the LLM may recover; only exhaustion or unavailable configuration raises `AgentError(code, params)`.

Run:

```powershell
conda run -n chatapi pytest backend/tests/test_agent_runtime.py backend/tests/test_chat_orchestrator.py -q
```

Expected: all selected tests pass. Keep `ChatOrchestrator` as a compatibility shim that constructs `AgentTurnRequest`; remove Skill-owned provider lookup from it.

- [ ] **Step 7: Commit Agent runtime**

```powershell
git add backend/src/chatapi/chat/agent.py backend/src/chatapi/chat/context.py backend/src/chatapi/chat/orchestrator.py backend/tests/test_agent_runtime.py backend/tests/test_chat_orchestrator.py
git commit -m "feat: run conversations through built-in agent"
```

---

### Task 5: Browser turn API and compatibility adapters

**Files:**
- Create: `backend/src/chatapi/schemas/chat.py`
- Modify: `backend/src/chatapi/chat/api.py`
- Create: `backend/tests/test_chat_turn_api.py`
- Modify: `backend/tests/test_compatible_api.py`

**Interfaces:**
- Produces: `POST /api/chat/turns` browser contract.
- Preserves: `/v1/chat/completions`, `/v1/messages`, and streaming envelopes.
- Produces: generic model ID `agent-default` and existing `skill-<id>` aliases.

- [ ] **Step 1: Write failing browser turn tests**

Post:

```json
{
  "message": "查询一个基因",
  "conversation_id": null,
  "candidate_skill_ids": [1, 2]
}
```

Assert a clarification response contains `status="needs_input"`, its conversation ID, loaded Skill IDs, Markdown message, and pending fields. Send a second turn with the same conversation ID and assert completion. Test candidate changes on an existing conversation return `409 chat.candidate_scope_locked`.

- [ ] **Step 2: Run tests and verify RED**

```powershell
conda run -n chatapi pytest backend/tests/test_chat_turn_api.py backend/tests/test_compatible_api.py -q
```

Expected: browser route 404 and old compatibility tests fail after switching expectations to Agent output.

- [ ] **Step 3: Implement the browser endpoint**

Define:

```python
class ChatTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    conversation_id: str | None = None
    candidate_skill_ids: list[int] = Field(default_factory=list, max_length=32)

class ChatTurnResponse(BaseModel):
    status: Literal["completed", "needs_input"]
    conversation_id: str
    message: str
    loaded_skill_ids: list[int]
    pending: dict[str, Any] | None = None
```

Build `AgentTurnRequest(interactive=True)` and forward the Tool Session cookie/header. Map `AgentError` to localized `ApiError` envelopes.

- [ ] **Step 4: Delegate compatibility protocols to Agent**

Map `model="agent-default"` to an empty candidate list and `model="skill-7"` to `[7]`. Accept optional `chatapi_skill_ids` only when the model is `agent-default`; reject conflicting scopes. Always set `interactive=False`. Keep response object shapes and SSE events unchanged, using `AgentTurnResult.content` and token counts.

`GET /v1/models` returns `agent-default` first and then each running Skill alias. Each Skill alias describes candidate scoping, not a model provider.

- [ ] **Step 5: Run focused API tests**

```powershell
conda run -n chatapi pytest backend/tests/test_chat_turn_api.py backend/tests/test_compatible_api.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit chat APIs**

```powershell
git add backend/src/chatapi/schemas/chat.py backend/src/chatapi/chat/api.py backend/tests/test_chat_turn_api.py backend/tests/test_compatible_api.py
git commit -m "feat: expose agent chat turn api"
```

---

### Task 6: Agent administration UI and Skill decoupling

**Files:**
- Create: `frontend/src/stores/agent.ts`
- Create: `frontend/src/views/AgentView.vue`
- Create: `frontend/src/__tests__/agent-view.spec.ts`
- Modify: `frontend/src/api/contracts.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/layouts/AdminLayout.vue`
- Modify: `frontend/src/views/SkillsView.vue`
- Modify: `frontend/src/stores/skills.ts`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/__tests__/skills-chat.spec.ts`

**Interfaces:**
- Consumes: Agent administration API from Task 2.
- Produces: `/admin/agent` settings page and provider-free Skill editor.

- [ ] **Step 1: Write failing Agent page and Skill form tests**

Assert navigation contains Agent, the page loads providers plus configuration, mode defaults to Human-in-loop, save sends every Agent field, and reset calls the reset route. Update Skill tests to assert there is no provider selector and Skill save payload omits `provider_id` and `model`.

- [ ] **Step 2: Run tests and verify RED**

```powershell
& 'D:\nvm\nodejs\npm.cmd' test -- --run src/__tests__/agent-view.spec.ts src/__tests__/skills-chat.spec.ts
```

Run from `frontend`. Expected: missing Agent page/navigation and old Skill provider UI failures.

- [ ] **Step 3: Implement contracts, store, route, and page**

Add:

```ts
export interface AgentConfig {
  id: 1
  name: string
  enabled: boolean
  system_prompt: string
  provider_id: number | null
  model: string | null
  mode: 'human_in_loop' | 'react'
  max_iterations: number
}
```

The store implements `load()`, `save(payload)`, and `reset()` with administrator CSRF. The page uses existing form styles, loads enabled providers, disables save when no provider is selected, and explains that Tool calls do not require approval. Add English/Chinese strings for each field and error.

Remove provider/model state, controls, payload fields, and validation from the Skill editor/store/contracts.

- [ ] **Step 4: Run focused frontend tests**

```powershell
& 'D:\nvm\nodejs\npm.cmd' test -- --run src/__tests__/agent-view.spec.ts src/__tests__/skills-chat.spec.ts
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit administration UI**

```powershell
git add frontend/src/stores/agent.ts frontend/src/views/AgentView.vue frontend/src/__tests__/agent-view.spec.ts frontend/src/api/contracts.ts frontend/src/router/index.ts frontend/src/layouts/AdminLayout.vue frontend/src/views/SkillsView.vue frontend/src/stores/skills.ts frontend/src/i18n frontend/src/styles.css frontend/src/__tests__/skills-chat.spec.ts
git commit -m "feat: manage agent separately from skills"
```

---

### Task 7: Tool parameter description/example editor

**Files:**
- Modify: `frontend/src/api/contracts.ts`
- Modify: `frontend/src/stores/tools.ts`
- Modify: `frontend/src/views/ToolsView.vue`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/__tests__/tools-view.spec.ts`

**Interfaces:**
- Consumes: effective Tool summaries and parameter override endpoint from Task 3.
- Produces: inline description/example editing with structural fields read-only.

- [ ] **Step 1: Write a failing parameter editor test**

Render a Tool containing `geneSymbol` and assert type, required status, and request location are text rather than inputs. Click Edit parameter, update description/example, save, and assert:

```ts
expect(fetchMock).toHaveBeenCalledWith(
  '/api/admin/tools/8/parameters/geneSymbol',
  expect.objectContaining({
    method: 'PUT',
    body: JSON.stringify({ description: 'HGNC gene symbol', example: 'ABCA4' }),
  }),
  expect.anything(),
)
```

- [ ] **Step 2: Run test and verify RED**

```powershell
& 'D:\nvm\nodejs\npm.cmd' test -- --run src/__tests__/tools-view.spec.ts
```

Expected: no Edit parameter control.

- [ ] **Step 3: Implement editor state and store request**

Extend `ToolParameterView` with `example: unknown`. Add one inline editor at a time, with description textarea, JSON-capable example input, Save, and Cancel. Parse examples as JSON when valid; otherwise send the entered string. Structural badges remain outside the edit form and cannot be changed.

After save, replace/reload the Tool summary so the effective schema is immediately visible. Add localized labels and compact parameter-editor styles.

- [ ] **Step 4: Run focused tests**

```powershell
& 'D:\nvm\nodejs\npm.cmd' test -- --run src/__tests__/tools-view.spec.ts
```

Expected: all Tool view tests pass.

- [ ] **Step 5: Commit parameter editor**

```powershell
git add frontend/src/api/contracts.ts frontend/src/stores/tools.ts frontend/src/views/ToolsView.vue frontend/src/i18n frontend/src/styles.css frontend/src/__tests__/tools-view.spec.ts
git commit -m "feat: edit tool parameter descriptions"
```

---

### Task 8: Multi-Skill browser Agent conversations

**Files:**
- Create: `frontend/src/components/SkillMultiSelect.vue`
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/api/contracts.ts`
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/__tests__/skills-chat.spec.ts`

**Interfaces:**
- Consumes: `/api/chat/turns` from Task 5.
- Produces: browser-local v2 sessions with candidate/loaded Skills and clarification state.

- [ ] **Step 1: Write failing multi-select and history migration tests**

Assert no selected chips displays “Agent auto-select”; select two Skills and assert the request sends `candidate_skill_ids: [1, 2]`. Seed legacy local storage containing `skillId: 1`, remount, and assert the component restores one selected Skill and rewrites storage with `skillIds: [1]`.

- [ ] **Step 2: Run tests and verify RED**

```powershell
& 'D:\nvm\nodejs\npm.cmd' test -- --run src/__tests__/skills-chat.spec.ts
```

Expected: old single select and `/v1/chat/completions` request assertions fail.

- [ ] **Step 3: Implement accessible multi-select and v2 storage**

`SkillMultiSelect` exposes `v-model:number[]`, a button/listbox, checkboxes, removable chips, and an empty auto-select label. Limit selections to 32.

Change local sessions to:

```ts
interface LocalChatSessionV2 {
  version: 2
  id: string
  conversationId: string | null
  title: string
  skillIds: number[]
  loadedSkillIds: number[]
  status: 'completed' | 'needs_input'
  pending: Record<string, unknown> | null
  messages: ChatMessage[]
  updatedAt: string
}
```

Migrate v1 sessions during load. Candidate selection is editable only before the first message; New Chat starts with a fresh selection copied from the current UI but a new identity.

- [ ] **Step 4: Write failing clarification and resume test**

Mock the first turn as `needs_input`, assert the clarification card and loaded Skill label render, then reply and assert the second request contains only the new message plus the same conversation ID. Reload and assert pending state and transcript restore.

- [ ] **Step 5: Implement structured turns and clarification display**

Replace `/v1/chat/completions` with `/api/chat/turns`. Store the user turn before sending, then append the returned Agent message, status, loaded IDs, pending state, and conversation ID. A clarification is an assistant message with a distinct CSS class; the same composer sends its answer.

- [ ] **Step 6: Run focused tests**

```powershell
& 'D:\nvm\nodejs\npm.cmd' test -- --run src/__tests__/skills-chat.spec.ts
```

Expected: all Chat tests pass.

- [ ] **Step 7: Commit browser Agent flow**

```powershell
git add frontend/src/components/SkillMultiSelect.vue frontend/src/views/ChatView.vue frontend/src/api/contracts.ts frontend/src/i18n frontend/src/styles.css frontend/src/__tests__/skills-chat.spec.ts
git commit -m "feat: support multi-skill agent conversations"
```

---

### Task 9: Safe Markdown tables and Varcards2-Gene contract

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/src/components/MarkdownMessage.vue`
- Create: `frontend/src/__tests__/markdown-message.spec.ts`
- Modify: `frontend/src/views/ChatView.vue`
- Modify: `frontend/src/styles.css`
- Modify: `backend/tests/test_agent_runtime.py`
- Modify data through existing Skill administration API: `Varcards2-Gene.system_prompt`

**Interfaces:**
- Produces: safe assistant Markdown rendering with GFM tables.
- Produces: Varcards2-Gene locus answers with a `Field | Result` table.

- [ ] **Step 1: Install renderer dependencies through nvm-managed npm**

From `frontend` run:

```powershell
& 'D:\nvm\nodejs\npm.cmd' install markdown-it dompurify
& 'D:\nvm\nodejs\npm.cmd' install -D @types/markdown-it
```

Expected: package and lock files contain the three dependencies.

- [ ] **Step 2: Write failing Markdown security/table tests**

Render:

```markdown
| Field | Result |
|---|---|
| Gene | ABCA4 |

<img src=x onerror="alert(1)">
[bad](javascript:alert(1))
```

Assert a `table`, `thead`, and ABCA4 cell exist, while `img`, `onerror`, and `javascript:` do not. Assert user messages remain plain text in ChatView.

- [ ] **Step 3: Run test and verify RED**

```powershell
& 'D:\nvm\nodejs\npm.cmd' test -- --run src/__tests__/markdown-message.spec.ts
```

Expected: missing component failure.

- [ ] **Step 4: Implement MarkdownMessage**

Configure `markdown-it` with `{ html: false, linkify: true, breaks: true }`. Sanitize rendered HTML through DOMPurify with a table/code/link-oriented allow-list. Post-process anchors so external links use `target="_blank"` and `rel="noopener noreferrer"`. Render the sanitized result in a `.markdown-body` wrapper. Replace assistant message interpolation in ChatView with this component; retain plain interpolation for users.

Add responsive table overflow, borders, header background, alternating row color, code blocks, blockquotes, and link styles scoped under `.markdown-body`.

- [ ] **Step 5: Add and test Varcards2-Gene table rule**

Update the Skill prompt through the admin API to include this exact response rule:

```text
For a gene locus query, return a Markdown table with columns Field and Result.
Include Gene symbol, Chromosome, and Cytogenetic location when the Tool returns them.
Do not infer a reference build; state "Not provided by the API" when absent.
Add a short data-source note after the table.
```

In the Agent runtime test, assert this Skill prompt is present after dynamic loading and the fake final response contains a Markdown table. Do not hard-code table formatting in Python; the contract belongs to the Skill prompt.

- [ ] **Step 6: Run Markdown and Agent tests**

```powershell
& 'D:\nvm\nodejs\npm.cmd' test -- --run src/__tests__/markdown-message.spec.ts src/__tests__/skills-chat.spec.ts
conda run -n chatapi pytest backend/tests/test_agent_runtime.py -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit Markdown support**

```powershell
git add frontend/package.json frontend/package-lock.json frontend/src/components/MarkdownMessage.vue frontend/src/__tests__/markdown-message.spec.ts frontend/src/views/ChatView.vue frontend/src/styles.css backend/tests/test_agent_runtime.py
git commit -m "feat: render safe markdown agent responses"
```

---

### Task 10: Migration, compatibility, and real end-to-end verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example` only if runtime configuration gained an environment setting.
- Modify tests found failing during the full regression only when behavior is intentionally changed by the approved spec.

**Interfaces:**
- Verifies all prior task interfaces together.

- [ ] **Step 1: Apply the migration to the application database**

```powershell
conda run -n chatapi alembic -c backend/alembic.ini upgrade head
```

Expected: database revision is `0005_agent_runtime`; Agent ID 1 points to the first enabled provider and Skills have no provider/model columns.

- [ ] **Step 2: Run complete backend verification**

```powershell
conda run -n chatapi pytest backend/tests -q
conda run -n chatapi ruff check backend/src backend/tests
```

Expected: zero failing tests and `All checks passed!`.

- [ ] **Step 3: Run complete frontend verification**

From `frontend`:

```powershell
& 'D:\nvm\nodejs\npm.cmd' test
& 'D:\nvm\nodejs\npm.cmd' run build
```

Expected: zero failing Vitest tests and a successful Vite production build.

- [ ] **Step 4: Verify compatibility APIs against Agent routing**

Call `/v1/models`, `/v1/chat/completions` with `agent-default`, `/v1/chat/completions` with `skill-1`, and `/v1/messages`. Assert valid protocol envelopes, no interactive `needs_input` response, and Agent-generated content.

- [ ] **Step 5: Verify the real browser scenario with Playwright CLI**

Open `http://127.0.0.1:5173/chat`, leave candidate Skills empty or select `Varcards2-Gene`, send `查询ABCA4位点`, and verify:

- Agent loads `Varcards2-Gene`;
- the response renders as an HTML table;
- the table contains `ABCA4`, chromosome `1`, and `1p22.1`;
- no Tool approval appears;
- refresh restores the transcript, rendered table, candidate Skill IDs, and loaded Skill indicator from browser storage.

Also run a deliberately ambiguous prompt against a Skill with a required choice and verify human-in-loop returns a clarification, the answer resumes the same conversation, and Tool execution begins only after sufficient input exists.

- [ ] **Step 6: Update documentation**

Document the Agent menu, provider ownership, modes, multi-Skill behavior, browser-only clarification, compatibility model aliases, Markdown output, Tool parameter overrides, migration command, and the exact development startup commands using Conda/nvm.

- [ ] **Step 7: Inspect diff and commit integration documentation**

```powershell
git diff --check
git status --short
git add README.md .env.example
git commit -m "docs: describe agent runtime workflow"
```

If `.env.example` did not change, omit it from `git add`. Expected: the final status contains no untracked implementation files and retains only unrelated pre-existing changes, if any.
