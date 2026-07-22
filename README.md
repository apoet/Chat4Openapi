# Chat4Openapi

Chat4Openapi turns Swagger/OpenAPI operations into managed Tools and lets independently configured Agents load ordered Skill catalogs to answer browser, OpenAI-compatible, and Anthropic-compatible requests.

The application is a single FastAPI/Vue deployment backed by SQLite. It includes first-run administrator setup, multi-Agent administration, one-time Agent API keys, encrypted business-identity Tool Sessions, OAuth Device Flow and PKCE, Swagger login, bulk Tool operations, scalable Skill Tool catalogs, safe Markdown, and English/Simplified Chinese UI.

## Requirements and installation

- Conda with the `libmamba` solver
- nvm-windows
- Node.js `20.19.4`
- Python `3.12`

Create the canonical Conda environment and install the backend:

```powershell
conda env create --solver libmamba -f environment.yml
conda run -n chat4openapi python -m pip install -e "backend[dev]"
```

Select Node with nvm and install the frontend:

```powershell
nvm use 20.19.4
Set-Location frontend
npm install
Set-Location ..
```

Copy `.env.example` to `.env`, review the database, cookie, session, and encryption settings, then migrate before every first start or upgrade:

```powershell
conda run -n chat4openapi alembic -c backend/alembic.ini upgrade head
```

Build the frontend and start the combined application:

```powershell
Set-Location frontend
npm run build
Set-Location ..
conda run -n chat4openapi uvicorn chat4openapi.main:app --app-dir backend/src --host 127.0.0.1 --port 8000
```

For frontend development, run `npm run dev` after `nvm use 20.19.4`. Vite listens on `http://127.0.0.1:5173` and proxies application routes to `http://127.0.0.1:8000`.

## Initialize and administer

1. Open `http://127.0.0.1:8000`. The first-run wizard creates the sole backend administrator. Usernames are 3–128 characters using letters, numbers, `.`, `_`, or `-`; passwords are 6–256 characters.
2. Sign in. Administrator state uses secure HTTP-only cookies; every administrator mutation also requires the CSRF token supplied by the application.
3. Add an enabled OpenAI-compatible or Anthropic-compatible provider.
4. Import a Swagger 2.0 or OpenAPI 3.x document under **API sources**. New Tools are disabled until explicitly trusted.
5. Create Agents under **Agents**. Each Agent owns its provider, optional model override, prompt, mode, maximum iterations, and an explicitly ordered list of bound Skills. An Agent can be enabled only with an available provider and at least one running bound Skill.
6. Choose one enabled Agent as default. Default switching is transactional; the current default cannot be disabled or deleted until another Agent becomes default.

Stopped Skills remain bound and visible but cannot load at runtime. Every Agent can load only its own running bound Skills, in the configured order.

## Agent API keys and compatible APIs

Create multiple keys per Agent for rotation or separate integrations. A key's full `c4o_...` secret is shown exactly once; copy it before closing the dialog. Only a hash and short prefix are stored. Revocation, expiry, disablement, deletion, or Agent unavailability invalidates later requests and any Tool Sessions owned by that key.

All compatible endpoints require the key as `Authorization: Bearer <Agent API Key>`:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/messages`

`agent-default` and matching `agent-<id>` select the key-bound Agent. `skill-<id>` and the optional `chat4openapi_skill_ids` request field only narrow that Agent's bound Skill catalog; they cannot cross into another Agent. Asking for another Agent returns `403 auth.agent_key_forbidden` without revealing whether it exists.

OpenAI-compatible example:

```powershell
$headers = @{
  Authorization = "Bearer $env:CHAT4OPENAPI_AGENT_KEY"
  "Content-Type" = "application/json"
}
$body = @{ model = "agent-default"; messages = @(@{ role = "user"; content = "List my orders" }) } | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/chat/completions -Headers $headers -Body $body
```

Anthropic-compatible example:

```powershell
$headers = @{
  Authorization = "Bearer $env:CHAT4OPENAPI_AGENT_KEY"
  "Content-Type" = "application/json"
}
$body = @{ model = "agent-default"; max_tokens = 512; messages = @(@{ role = "user"; content = "List my orders" }) } | ConvertTo-Json -Depth 6
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/messages -Headers $headers -Body $body
```

If the selected Tools require upstream business credentials, create a Tool Session before the chat request and add the canonical header:

```powershell
$headers["X-Chat4Openapi-Tool-Session"] = $env:CHAT4OPENAPI_TOOL_SESSION
```

Tool calls never start an OAuth redirect or wait for Device authorization. Missing credentials return `tool_authorization_required`; expired or rejected credentials return `tool_reauthorization_required`. Complete authorization first as described in [Tool Session authentication](docs/tool-session-authentication.md).

## Browser Chat

Browser Chat obtains a public browser subject in a high-entropy HTTP-only cookie. This is separate from the administrator session and Agent API keys. A new chat lists runnable Agents and initially selects the default Agent; after the first message, the Agent is locked for that conversation. **New Chat** permits a different selection.

History is stored locally under the browser subject and contains the Agent ID/name snapshot, messages, loaded-Skill display state, and server conversation ID—but never API keys, Tool Session tokens, or injected credentials. Refresh restores the Agent-bound history and sanitized Markdown/GFM tables. Historical inactive Agents remain visible but cannot be selected for a new conversation.

`human_in_loop` may ask only for missing or ambiguous business inputs. It never approves Tool calls or performs authentication. Compatible APIs always run non-interactively.

## Tools and Skills

- **Tools** supports persistent row selection across search/filter/disclosure changes. **Select visible** selects only rendered rows. Bulk enable, disable, and soft delete accept at most 200 unique positive IDs and return ordered partial results: successful items are reconciled immediately and removed from selection; failed items remain selected for retry. Delete confirmation shows Tool and affected-source counts.
- Tool parameter overrides may change only descriptions and examples. Imported name, type, required state, location, and execution mapping remain authoritative.
- **Skills** uses one full-catalog index for source, original Swagger tag, enabled state, name, description, path, tag, and source search. Only the first 100 ordinary matches render at once, while existing unavailable bindings stay visible for removal. A Skill can bind at most 128 Tools.
- Type `@` in a Skill prompt to search eligible Tools and insert the canonical `{{tool:name}}` reference. Disabled/login/source-disabled Tools remain visible where useful but cannot be newly bound or referenced.

## Tool Session authentication

Tool Sessions represent the upstream business user, not the Chat4Openapi administrator or Agent key. They are bound to one Agent, one authenticated owner, and allowed API sources. Supported modes are:

1. OAuth 2.0 Device Authorization Grant for CLI/headless clients.
2. Authorization Code with PKCE for browser administration/frontends.
3. Pre-authorized allow-listed Header or Cookie injection.
4. Swagger login automation for ordinary non-interactive login endpoints without CAPTCHA, MFA, or other challenges.

See [docs/tool-session-authentication.md](docs/tool-session-authentication.md) for exact endpoints, examples, lifecycle, and failure behavior.

## Backup and migration

Stop the application and back up the SQLite database together with its encryption key before upgrading. By default these are `data/chat4openapi.db` and `data/.chat4openapi.key`. The database alone is not sufficient to recover encrypted provider, Tool Session, or OAuth secrets.

```powershell
New-Item -ItemType Directory -Force backup | Out-Null
Copy-Item data/chat4openapi.db backup/chat4openapi.db
Copy-Item data/.chat4openapi.key backup/.chat4openapi.key
conda run -n chat4openapi alembic -c backend/alembic.ini upgrade head
```

The current migration chain preserves API sources, Tools, parameter overrides, providers, Skills, ordered bindings, Agents, keys, and conversations. Rows that predate conversation-owner isolation are preserved for audit, marked revoked, and soft-deleted because they cannot be resumed securely.

On default paths only, startup/Alembic atomically migrates the legacy database and key filenames to the names above when—and only when—the destination does not exist. It never overwrites a current file. If both old and new files exist, both remain untouched so the operator can reconcile them. Custom paths are never moved automatically.

Downgrades are for controlled validation, not a backup strategy. Always restore both database and key from the same backup set if rollback is required.

## Security boundaries and limits

- Provider keys, upstream credentials, OAuth client/access/refresh material, and PKCE verifiers are encrypted at rest; Agent API keys and opaque session tokens are hashed. Plaintext secrets are not logged or returned after creation.
- Set `CHAT4OPENAPI_SECURE_COOKIES=true` behind HTTPS. Do not expose the default development listener directly to an untrusted network.
- API-source URL fetches and redirects apply SSRF controls. Private/non-routable targets are blocked unless that source is explicitly opted in. URL credentials/fragments and unsafe redirects are rejected.
- OpenAPI documents are limited to 5 MiB. Tool requests are limited to 1 MiB, responses to 4 MiB, and redirects to 3.
- Bulk Tool requests contain 1–200 unique positive strict-integer IDs. Skills contain at most 128 Tool bindings. Agent iterations are 2–32. Chat messages and Agent/Skill prompts are capped at 100,000 characters.
- Injected credential names must be declared by the API source. Transport-sensitive headers such as Host, Content-Length, forwarding, connection, proxy, transfer, and raw Cookie are prohibited; Cookie names/values are validated separately.
- OAuth and CAPTCHA interaction is never performed during a Tool call. Swagger login is unsuitable for CAPTCHA/MFA/interactive flows.

## Verification

Run gates serially from the repository root:

```powershell
conda run -n chat4openapi python -m pytest backend/tests -q
conda run -n chat4openapi ruff check backend/src backend/migrations backend/tests
nvm use 20.19.4
Set-Location frontend
npm test -- --run --testTimeout=15000
npm run typecheck
npm run build
Set-Location ..
git diff --check
```

After `npm run build`, FastAPI serves `frontend/dist` with SPA fallback. Unknown `/api/*`, `/v1/*`, and `/anthropic/*` paths remain JSON 404 responses.
