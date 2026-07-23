# Tool Session Authentication

Tool Sessions carry the upstream business user's identity separately from Agent4API access. An Agent API key authenticates a compatible client; an administrator cookie authenticates browser administration. Neither is injected into imported APIs.

Each Tool Session is bound to one Agent, exactly one owner (the creating Agent key, administrator session, Embed session, or public Chat browser session), and one or more API sources. Cross-Agent, cross-key, cross-browser-session, and cross-source reuse is rejected. Session states are `authorization_required`, `pending`, `ready`, `expired`, `revoked`, and `failed`.

## Before choosing a mode

Import and enable the API source and required Tools. Each API source selects
one interactive authentication mode: OAuth 2.0 or a login Tool. Saving one
mode disables the other for that source. Configure OAuth through
`PUT /api/admin/sources/{source_id}/oauth`, or traditional login through
`PUT /api/admin/sources/{source_id}/tool-auth`. OAuth endpoint URLs and client
material are stored encrypted. For injected credentials, the requested
Header/Cookie names must be declared by the source's OpenAPI security schemes
or the legacy-compatible allow-list extension.

Administrator writes require the administrator cookie plus `X-CSRF-Token`. CLI/headless calls use `Authorization: Bearer <Agent API Key>`. Examples below assume:

```powershell
$base = "http://127.0.0.1:8000"
$agentHeaders = @{ Authorization = "Bearer $env:CHAT4OPENAPI_AGENT_KEY"; "Content-Type" = "application/json" }
```

## OAuth Device Authorization Grant

Use Device Flow for a CLI or headless client. Start authorization with the key-bound Agent:

```powershell
$start = Invoke-RestMethod -Method Post -Uri "$base/api/tool-sessions/oauth/device/start" -Headers $agentHeaders -Body '{"api_source_id":1}'
$start | Select-Object tool_session_id,status,user_code,verification_uri,verification_uri_complete,interval,expires_at
```

Show the verification URI and user code to the business user. Poll no faster than the returned `interval`:

```powershell
$session = Invoke-RestMethod -Method Get -Uri "$base/api/tool-sessions/$($start.tool_session_id)/status" -Headers $agentHeaders
```

`authorization_pending` remains `pending`; issuer `slow_down` increases the enforced interval. HTTP 429 includes the retry delay when the client polls early. Stop on `ready`, `expired`, `failed`, or revoked state. Device codes and OAuth tokens are encrypted and never returned in status responses.

## Authorization Code with PKCE

PKCE start is an administrator-browser operation because it redirects a user agent. With the administrator cookie and CSRF header:

```text
POST /api/tool-sessions/oauth/pkce/start
{"api_source_id":1,"agent_id":2}
```

Open the returned `authorization_url`. The issuer redirects to:

```text
GET /api/tool-sessions/oauth/pkce/callback?state=...&code=...
```

The callback atomically consumes the high-entropy state, exchanges the code, stores encrypted credentials, and sets the HTTP-only `chat4openapi_tool_session` cookie. State is single-use. PKCE verifier and transient secrets are erased on success, failure, expiry, or cancellation.

Public Chat uses the same PKCE exchange through
`POST /api/chat/oauth/pkce/start`. Its credentials are bound to the current
HTTP-only browser Chat session. The callback notifies and closes only the
same-origin popup; it does not expose a Tool Session token. Chat then resumes
the paused conversation through
`POST /api/chat/turns/{conversation_id}/resume`.

OAuth source configuration supports four token endpoint authentication methods:

- `auto` (the default, including legacy configurations) sends credentials in
  the form first, then retries once with HTTP Basic authentication only after
  `invalid_client` or HTTP 401.
- `client_secret_basic` sends credentials only in the HTTP Basic
  `Authorization` header.
- `client_secret_post` sends credentials in the request form.
- `none` sends only `client_id` for public PKCE clients.

Automatic fallback does not retry grant errors such as `invalid_grant`.

## Pre-authorized Header or Cookie injection

Use injection when an external authentication system has already obtained a supported credential:

```powershell
$body = @{
  api_source_id = 1
  headers = @{ Authorization = "Bearer upstream-token" }
  cookies = @{}
  expires_at = "2026-07-23T00:00:00Z"
} | ConvertTo-Json -Depth 5
$created = Invoke-RestMethod -Method Post -Uri "$base/api/tool-sessions/credentials" -Headers $agentHeaders -Body $body
$env:CHAT4OPENAPI_TOOL_SESSION = $created.tool_session_id
```

The response exposes the opaque Tool Session token, not the injected credential. Only configured names are accepted. Header values with control characters and unsafe transport headers are rejected. Cookie names must be HTTP token-safe and values must satisfy cookie-octet rules; submit Cookies through the `cookies` map, never a raw `Cookie` header.

## Swagger login automation

Swagger login supports traditional username/password login Tools configured
under the API source's **Authentication → Tool authentication** mode:

```powershell
$body = @{ username = "business-user"; password = $env:UPSTREAM_PASSWORD } | ConvertTo-Json
$created = Invoke-RestMethod -Method Post -Uri "$base/v1/tool-sessions" -Headers $agentHeaders -Body $body
```

The login Tool runs once and its mapped Token/Header/Cookie is scoped to that Tool's API source. Declared expiry and JWT `exp` can only shorten the Session. Swagger login does not solve or bypass CAPTCHA, MFA, consent pages, or other interactive challenges; use Device Flow, PKCE, or external injection instead.

Browser-oriented Swagger login opens a source-scoped popup only when a Tool
from that source needs authorization. Public Chat and Embed bind the resulting
credential to their own browser session. The legacy
`POST /api/tool-session/login` endpoint remains available for compatible
single-source clients.

## Use, inspect, refresh, and revoke

Every OpenAI- or Anthropic-compatible request requires the Agent key. Add the Tool Session only when upstream-authenticated Tools may run:

```powershell
$chatHeaders = $agentHeaders.Clone()
$chatHeaders["X-Chat4Openapi-Tool-Session"] = $env:CHAT4OPENAPI_TOOL_SESSION
```

The header is bound to the same Agent key on every request. A different key—even for the same Agent—cannot reuse it. Tool execution rechecks Agent, key/session owner, source, credential, and expiry before the upstream request.

Programmatic lifecycle endpoints are:

- `GET /api/tool-sessions/{tool_session_id}` — status for the authenticated owner.
- `POST /api/tool-sessions/oauth/refresh` with `tool_session_id` and `api_source_id` — explicit OAuth refresh.
- `DELETE /v1/tool-sessions/{tool_session_id}` or `DELETE /api/tool-sessions/{tool_session_id}` — revoke.

OAuth refresh may also occur immediately before a Tool call and replay once after an upstream 401. It never starts a redirect, polls authorization, or waits for a person. A 403 is returned without refresh/replay.

## Failure and security behavior

- No Tool Session: `tool_authorization_required` when the selected Tool needs credentials.
- Expired/rejected credential: `tool_reauthorization_required`; authorize before retrying chat.
- Invalid owner/session references share non-enumerating authentication/not-found boundaries.
- Revoking/expiring/deleting an Agent key immediately invalidates its Sessions.
- Idle and absolute expiries are enforced before issuer or Tool network traffic. Refresh cannot extend the original absolute lifetime.
- OAuth endpoints obey the API source's network policy, reject URL credentials/fragments, and do not follow issuer redirects.
- Access/refresh tokens, client secrets, injected values, login passwords, Device codes, and PKCE verifiers are encrypted at rest, omitted from responses after creation, and never written to application logs.

Back up `data/.chat4openapi.key` (or the stable configured Fernet key) together with the database. Losing or mismatching it makes encrypted provider and Tool Session data unrecoverable.
