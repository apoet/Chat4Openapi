# ChatAPI

Chat with your APIs through managed MCP Tools and Skills.

The current implementation contains the platform foundation, Tool Runtime, and the core Skills/chat
runtime: SQLite migrations, first-run single-administrator setup, secure administrator sessions,
English/Chinese localization, Swagger 2.0 and OpenAPI 3.x import, managed Tool lifecycle, encrypted
original-API Tool Sessions, safe request-scoped execution, a dynamic FastMCP endpoint, encrypted
OpenAI/Anthropic-compatible provider configuration, startable Skills, compatible chat APIs, and Vue
administration/chat surfaces.

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
conda run -n chatapi ruff check backend
```

## Frontend development

```powershell
nvm use 20.19.4
Set-Location frontend
npm install
npm run dev
```

Vite proxies `/api` and `/health` to `http://127.0.0.1:8000`.

Run frontend verification:

```powershell
npm test
npm run typecheck
npm run build
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
2. Under **Skills**, select a provider and click enabled Tools in the quick-reference tray. Login,
   disabled, deleted, or source-disabled Tools are never offered for Skill binding.
3. Start the Skill and open **Chat**. The running Skill selector is below the message input.
4. If original-API login is enabled, sign in once on the chat gate. Its encrypted Tool Session is
   reused for every Tool call in that browser session.

OpenAI clients can use `/v1/models` and `/v1/chat/completions`; Anthropic clients can use
`/v1/messages`. Both protocols accept `skill-<id>` as the model and support streaming responses.

## First run

1. Open `http://127.0.0.1:8000` after building the frontend, or use the Vite development URL.
2. Select English or Simplified Chinese.
3. Create the sole backend administrator with a password of at least 12 characters.
4. Sign in to reach the administration overview.

The backend administrator is never used as the identity for imported API Tools. Each Tool user
authenticates once per Tool Session through the globally configured original-API login Tool; all
Tools in that session share the same encrypted, expiring original-API credentials.
