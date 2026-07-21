# ChatAPI

Chat with your APIs through managed MCP Tools and Skills.

The current implementation contains the platform foundation, Tool Runtime, and built-in Agent
runtime: SQLite migrations, first-run single-administrator setup, secure administrator sessions,
English/Chinese localization, Swagger 2.0 and OpenAPI 3.x import, managed Tool lifecycle, encrypted
original-API Tool Sessions, safe request-scoped execution, a dynamic FastMCP endpoint, encrypted
OpenAI/Anthropic-compatible provider configuration, reusable Skills, compatible chat APIs, and Vue
administration/chat surfaces.

Every conversation runs through the one built-in Agent. The Agent owns the LLM provider, optional
model override, general prompt, operating mode, and iteration limit. Skills are provider-independent
instruction and Tool allow-list packages that the Agent can load dynamically; they do not own a
provider or model.

## Requirements

- Conda
- nvm-windows
- Node.js 20.19.4

## Backend development

Create the Python 3.12 environment and migrate the database:

```powershell
conda env create --solver libmamba -f environment.yml
conda run -n chatapi alembic -c backend/alembic.ini upgrade head
```

If an existing `chatapi` environment needs refreshing:

```powershell
conda run -n chatapi python -m pip install -e "backend[dev]"
```

Start FastAPI:

```powershell
conda run -n chatapi uvicorn chatapi.main:app --app-dir backend/src --reload
```

Run backend verification:

```powershell
conda run -n chatapi python -m pytest backend/tests -q
conda run -n chatapi ruff check backend/src backend/tests
```

## Frontend development

```powershell
nvm use 20.19.4
Set-Location frontend
& 'D:\nvm\nodejs\npm.cmd' install
& 'D:\nvm\nodejs\npm.cmd' run dev
```

Vite starts at `http://127.0.0.1:5173` and proxies `/api`, `/v1`, and `/health` to
`http://127.0.0.1:8000`.

Run frontend verification:

```powershell
& 'D:\nvm\nodejs\npm.cmd' test
& 'D:\nvm\nodejs\npm.cmd' run typecheck
& 'D:\nvm\nodejs\npm.cmd' run build
```

After `npm run build`, FastAPI serves `frontend/dist` and provides SPA fallback for browser routes.
Unknown `/api/*`, `/v1/*`, and `/anthropic/*` paths always remain JSON 404 responses.

## Tool Runtime

1. Import a Swagger/OpenAPI JSON or YAML document under **API sources**.
2. Review imported operations under **Tools**; every new Tool is disabled by default.
3. Enable trusted Tools.
4. Optionally bind one enabled login Tool under **Tool authentication**. This login belongs to the
   original API, never to the backend administrator.
5. External MCP clients connect to `http://127.0.0.1:8000/mcp/`. When Tool authentication is
   enabled, first create a Tool Session through `POST /v1/tool-sessions`, then pass the returned
   `tool_session_id` to MCP Tool calls.

## Skills and chat

1. Add and test an OpenAI-compatible or Anthropic-compatible provider under **Providers**.
2. Open **Agent**, select the provider, and configure the optional model override, system prompt,
   mode, and iteration limit. **Restore defaults** resets Agent runtime settings while preserving the
   selected valid provider; it never changes Skills or Tools.
3. Under **Skills**, bind enabled Tools from the quick-reference tray. Login, disabled, deleted, or
   source-disabled Tools are never offered. A Skill has no provider or model of its own.
4. Start one or more Skills and open **Chat**. The candidate Skill multi-select is below the message
   input. An empty selection means **Agent auto-select** across all running Skills; selecting several
   Skills restricts the catalog while still allowing the Agent to load one or more of them. The
   candidate set is fixed after the first turn of a conversation.
5. If original-API login is enabled, sign in once on the chat gate. Its encrypted Tool Session is
   reused for every Tool call in that browser session.

The Agent runs Tools automatically; there is no Tool approval prompt. In `human_in_loop` mode,
browser Chat may pause only to clarify missing or ambiguous business input, then resumes the same
server conversation when the user answers. `react` mode never pauses. OpenAI- and
Anthropic-compatible endpoints always use non-interactive ReAct behavior regardless of the browser
mode.

Assistant output is Markdown. Browser Chat safely renders common Markdown and GFM tables, disables
raw HTML, sanitizes generated HTML and unsafe URLs, and stores the original Markdown plus candidate
and loaded Skill IDs in browser-local conversation history. Reloading the page restores that history
and its rendered tables.

OpenAI clients can use `/v1/models` and `/v1/chat/completions`; Anthropic clients can use
`/v1/messages`. `agent-default` allows automatic routing across all running Skills. Existing
`skill-<id>` aliases remain supported and restrict the Agent to that one candidate Skill. Requests
using `agent-default` may instead supply the optional `chatapi_skill_ids` extension to restrict the
candidate catalog. These identifiers select Agent routing scope, not a Skill-owned provider, and
compatibility responses never contain interactive `needs_input` state.

## Tool parameter guidance

The **Tools** page allows administrators to override an imported parameter's description and example
value. Parameter name, JSON type, required status, request location, and execution mapping remain
read-only and continue to come from Swagger/OpenAPI. The effective schema merges the overrides at
display and Agent runtime time. Refreshing an API Source preserves overrides for stable argument
names and removes overrides only when their imported argument disappears.

## Database migration

Run migrations before starting a new checkout or after updating an existing installation:

```powershell
conda run -n chatapi alembic -c backend/alembic.ini upgrade head
```

The Agent runtime migration creates the singleton Agent configuration, moves provider/model
ownership away from Skills, and chooses the lowest-ID enabled, non-deleted provider for an existing
installation. Existing Skill prompts and Tool bindings are retained; legacy Skill provider/model
values are intentionally discarded.

## First run

1. Open `http://127.0.0.1:8000` after building the frontend, or use the Vite development URL.
2. Select English or Simplified Chinese.
3. Create the sole backend administrator with a password of at least 12 characters.
4. Sign in to reach the administration overview.

The backend administrator is never used as the identity for imported API Tools. Each Tool user
authenticates once per Tool Session through the globally configured original-API login Tool; all
Tools in that session share the same encrypted, expiring original-API credentials.
