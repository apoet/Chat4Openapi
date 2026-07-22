# Agent Embed, AG-UI, and WebMCP Design

## Summary

Chat4Openapi will let an administrator bind an enabled Agent to an embeddable JavaScript loader. A traditional website adds one generated `<script>` tag. The loader displays the Chat4Openapi logo and opens a compact, Chat4Openapi-hosted iframe when clicked.

The iframe fixes the conversation to the configured Agent and uses an AG-UI client to communicate with a new AG-UI endpoint. Backend Tools imported from Swagger or OpenAPI continue to execute on the Chat4Openapi server. Separately, when the host page already exposes WebMCP Tools to the Chat4Openapi origin, the iframe discovers them and passes them to the Agent as AG-UI client-provided Tools. WebMCP is optional: unsupported browsers, pages without WebMCP, and pages that expose no Tools continue normally without frontend Tools.

The host website is not required to change its backend, expose its login state, or add anything beyond the generated script. Authentication for backend Tools remains a Chat4Openapi Tool Session concern. Frontend WebMCP Tools execute in the host page and use only the page state and permissions already available there.

## Goals

- Add an administrator-managed system Base URL.
- Generate revocable, Agent-bound embed scripts.
- Render a branded logo and compact iframe Chat on third-party websites.
- Provide streaming Agent conversations over AG-UI.
- Bridge pre-existing host-page WebMCP Tools into AG-UI as frontend Tools.
- Keep backend OpenAPI Tools and frontend WebMCP Tools strictly separate.
- Support anonymous Chat access while preserving authorization requirements for protected backend Tools.
- Reuse the existing per-API-source OAuth 2.0 and Swagger login configuration.
- Insert `docs/images/demo.png` below the workflow image in both README files.

## Non-goals

- Reading, copying, or forwarding the host website's cookies or login tokens.
- Requiring a host-side identity endpoint or backend integration.
- Automatically creating WebMCP Tools from DOM selectors or imported OpenAPI documents.
- Treating WebMCP as a replacement or fallback for backend Tools.
- Treating backend Tools as a replacement or fallback for WebMCP Tools.
- Supporting arbitrary Agent selection inside an embedded conversation.
- Making WebMCP mandatory for embedded Chat.

## Terminology and Tool Boundaries

### Backend Tools

Backend Tools are imported from Swagger/OpenAPI and execute through the existing Chat4Openapi backend Tool executor. Their authorization is managed by Tool Sessions, OAuth 2.0, pre-authorized credentials, or Swagger login. They use the existing canonical Tool names.

### Frontend Tools

Frontend Tools are WebMCP Tools already registered by the host page. They execute in the host page and are intended for page state and page operations, such as reading the current selection, filling a form, or activating an existing UI action. The embed loader does not create them. When exposed to the iframe, they are presented to the Agent under a reserved `web__` namespace.

The two Tool classes have separate catalogs, dispatchers, authorization rules, errors, and audit records. Neither class falls back to the other.

## Architecture

### Embed loader

The public loader endpoint is `GET /embed/{public_id}.js`. It returns versioned, cache-aware JavaScript that:

1. Creates a fixed logo button using assets served by Chat4Openapi.
2. Creates a hidden iframe pointing to `GET /embed/{public_id}`.
3. Adds `allow="tools"` to delegate the WebMCP permissions policy to the iframe.
4. Opens and closes the iframe on logo activation.
5. Adapts the panel to desktop and mobile viewport sizes.
6. Exchanges only defined lifecycle messages with the iframe using exact target origins.

The loader contains the public Embed ID and display configuration only. It never contains an Agent API key, provider key, Tool credential, OAuth secret, or long-lived session token.

### Embedded application

The iframe hosts a dedicated, minimal Chat route rather than the full administration or browser Chat interface. It contains:

- the fixed Agent identity and branding;
- conversation messages and composer;
- authorization prompts for protected backend Tools;
- an AG-UI client;
- a WebMCP bridge;
- no Agent selector and no administration navigation.

### AG-UI connection

The iframe creates an Embed Session and connects to `POST /api/embed/{public_id}/agent`. The endpoint accepts AG-UI `RunAgentInput` and streams AG-UI events over SSE. It advertises support for streaming and client-provided Tools.

Backend Agent execution emits lifecycle, text, error, and Tool Call events. Backend Tools are dispatched internally. Frontend Tools are emitted to the iframe as AG-UI Tool Calls and are never passed to the backend Tool executor.

### WebMCP bridge

The bridge performs progressive capability detection. When WebMCP is unavailable, it submits no frontend Tools and records no user-facing error. When available, it discovers only Tools that the host page has exposed to the Chat4Openapi origin.

For each acceptable WebMCP Tool, the bridge:

1. validates its name, description, and input schema;
2. maps it to an AG-UI Tool definition;
3. prefixes the Agent-visible name with `web__`;
4. retains an in-memory mapping to the original WebMCP Tool;
5. includes it only in the current AG-UI run;
6. executes it when the matching AG-UI Tool Call completes;
7. returns its result as an AG-UI Tool Result.

If a previously advertised frontend Tool disappears, its invocation returns `frontend_tool_unavailable`. It is not redirected to a backend Tool.

## Configuration and Data Model

### AppSetting

Add `base_url` to the singleton `app_settings` row.

- Accept only absolute `http` or `https` URLs with a host.
- Reject credentials, fragments, and query strings.
- Normalize by removing a trailing slash.
- Require HTTPS except for loopback development addresses.
- Disable embed script generation until configured.

The value is managed in a new administrator System Settings page and is authoritative for public script, iframe, asset, and OAuth callback URLs.

### AgentEmbed

Add an `agent_embeds` table:

- `id`: internal positive integer key.
- `agent_id`: required Agent foreign key.
- `name`: administrator label.
- `public_id`: unique, URL-safe, high-entropy identifier.
- `enabled`: active state.
- `allowed_origins`: normalized JSON array of exact HTTPS origins; loopback HTTP is allowed in development. An empty array means any origin.
- `position`: `bottom_right` or `bottom_left`.
- `created_at`, `updated_at`, and `deleted_at`.

An Agent may own multiple Embed configurations so sites can be revoked independently. Creating an Embed does not enable an unavailable Agent. Public use requires both the Embed and Agent to be enabled and the Agent to remain runnable.

### EmbedSession

Add an `embed_sessions` table:

- internal ID and public subject ID;
- Embed and Agent foreign keys;
- normalized parent origin;
- hashed bearer token;
- creation, last-seen, idle-expiry, absolute-expiry, and revocation timestamps.

The iframe stores the bearer token in memory and `sessionStorage` under the Chat4Openapi origin. It does not depend on third-party cookies.

### Conversation ownership

Add nullable `embed_session_id` to `conversations`. A conversation must have exactly one owner class: browser Chat session, Agent API key, or Embed Session. Conversation resume validates the same Embed, Agent, origin, and session owner.

### Tool Session ownership

Extend Tool Session ownership with nullable `embed_session_id`. Administrator sessions, Agent API keys, and Embed Sessions remain mutually exclusive owners. Credentials are scoped to the current Agent and allowed API sources as before, with the Embed and parent origin added to ownership validation.

### EmbedAuthGrant

Add single-use grants for returning authorization from a top-level popup:

- hashed random grant code;
- Embed Session and Tool Session foreign keys;
- API Source ID;
- expiry and consumed timestamps.

Grant codes expire within minutes and are consumed atomically. Tool Session tokens and OAuth tokens never appear in popup URLs or `postMessage` payloads.

## API Source Authentication Configuration

OAuth and Swagger authentication remain properties of an API Source, not an Agent or Embed.

The API Source administration interface exposes:

- OAuth enabled state;
- authorization URL;
- token URL;
- optional Device Authorization URL;
- client ID;
- encrypted client secret;
- scopes;
- redirect URI;
- the recommended callback URL derived from the system Base URL;
- a configuration test action that performs safe validation without authenticating a user.

The recommended callback URL is:

`{base_url}/api/tool-sessions/oauth/pkce/callback`

The explicit redirect URI remains available for providers that require an override. The final effective redirect URI is always displayed so administrators can copy it into the upstream OAuth application.

## Authentication Lifecycle

### Anonymous Embed access

An anonymous visitor may create an Embed Session and chat with the bound Agent. Public backend Tools can execute normally. Anonymous access does not make protected backend Tools public.

### Protected backend Tool

When a backend Tool requires credentials and the Embed Session has no eligible Tool Session, the AG-UI stream emits an authorization-required event containing a non-sensitive API Source summary. The iframe displays an authorization action rather than treating it as a generic Tool failure.

### OAuth 2.0 PKCE

1. The iframe starts authorization for the required API Source and current Embed Session.
2. Chat4Openapi creates encrypted PKCE state bound to the Embed Session, Agent, API Source, and parent origin.
3. The iframe opens a top-level Chat4Openapi popup.
4. The popup redirects to the API Source's authorization URL.
5. The upstream provider returns to the effective redirect URI.
6. Chat4Openapi validates and atomically consumes state, then exchanges the code at the API Source's token URL.
7. Tokens are encrypted into a Tool Session owned by the Embed Session.
8. The callback creates a short-lived, single-use Embed Auth Grant.
9. The callback page sends only the grant code to the exact Chat4Openapi iframe origin and closes.
10. The iframe exchanges the grant and resumes or retries the user task.

Device Flow remains available for compatible non-Widget clients but is not the default Widget flow.

### Swagger login

When an API Source uses a configured Swagger login Tool, the iframe opens a top-level Chat4Openapi login popup. Credentials post directly to Chat4Openapi over HTTPS, execute the configured login Tool once, and produce a Tool Session owned by the Embed Session. The same single-use grant mechanism returns authorization to the iframe. CAPTCHA, MFA, consent pages, and other unsupported interactive challenges are not bypassed.

### Logout and revocation

The Widget can revoke its Tool Session independently of the anonymous Embed Session. Disabling or deleting the Embed, disabling the Agent, revoking the Embed Session, or expiring the Tool Session immediately prevents subsequent protected Tool use.

## Origin and Browser Security

- The iframe response sends a per-Embed `Content-Security-Policy: frame-ancestors ...` header. An empty allow-list maps to the explicit product choice of allowing any HTTPS parent; configured lists use exact origins.
- The server also validates the normalized parent origin during Embed Session creation and resume.
- Cross-window messages validate `origin`, `source`, message type, and payload shape, and always use an exact target origin.
- OAuth and Swagger popups are opened only from a user gesture.
- The Widget does not inspect host cookies, DOM, or local storage. Only host-registered WebMCP Tools may act on the page.
- Embed bearer tokens, Auth Grants, Tool Session references, and AG-UI runs have separate identifiers and bounded lifetimes.
- Client-provided Tool definitions are untrusted input. The server caps count and encoded size and validates name, description, schema depth, and schema size.
- Frontend Tool argument and result sizes, execution time, and concurrent calls are bounded.
- High-risk frontend Tool behavior remains the host page's responsibility; Chat4Openapi renders AG-UI confirmation/interrupt events when the Tool metadata or Agent requests confirmation.

## Endpoints

### Administrator

- `GET /api/admin/settings`
- `PUT /api/admin/settings`
- `GET /api/admin/agents/{agent_id}/embeds`
- `POST /api/admin/agents/{agent_id}/embeds`
- `PUT /api/admin/agents/{agent_id}/embeds/{embed_id}`
- `DELETE /api/admin/agents/{agent_id}/embeds/{embed_id}`
- `GET /api/admin/agents/{agent_id}/embeds/{embed_id}/script`

All mutations require administrator authentication and CSRF protection.

### Public Embed

- `GET /embed/{public_id}.js`: loader script.
- `GET /embed/{public_id}`: embedded Chat application.
- `POST /api/embed/{public_id}/sessions`: create an Embed Session.
- `POST /api/embed/{public_id}/agent`: AG-UI run endpoint using SSE.
- `POST /api/embed/sessions/{session_id}/auth/start`: begin OAuth or Swagger authorization.
- `POST /api/embed/sessions/{session_id}/auth/exchange`: atomically consume an Embed Auth Grant.
- `DELETE /api/embed/sessions/{session_id}`: revoke the current Embed Session.

Public endpoints use the Embed bearer token where applicable. Disabled, deleted, unavailable, origin-denied, expired, or mismatched resources share non-enumerating error boundaries.

## Administrator Experience

### System Settings

Add a navigation entry and form for the Base URL. The page shows normalization and validation errors and explains that the value controls public Embed and OAuth callback URLs.

### API Sources

Keep OAuth 2.0 and Swagger login configuration in the API Source interface. Show the callback URL computed from Base URL beside the editable OAuth fields.

### Agent Embed panel

For a saved Agent, add an Embed panel that lists configurations and supports:

- create, edit, disable, and delete;
- allowed-origin editing;
- left/right position;
- generated script preview and copy;
- Widget preview against the current Base URL;
- clear unavailable-state messages when Base URL or Agent runtime prerequisites are missing.

The generated integration remains one script tag:

```html
<script src="https://chat.example.com/embed/{public_id}.js" async></script>
```

## Widget Experience

- The closed state is a branded, keyboard-accessible Logo button.
- The open state is a compact panel with Agent name, message history, composer, sending state, errors, and close control.
- The Agent is fixed and not selectable.
- Desktop uses the configured lower corner; small screens use a nearly full-screen panel with safe margins.
- An authorization-required event shows the API Source name and a clear login action.
- Popup blocking, cancellation, expired state, and failed exchange have retryable messages.
- WebMCP absence is silent. A specific frontend Tool invocation failure is visible in the conversation only through the Agent's handled response or a concise Tool error.

## Error Handling

- Missing Base URL: administrator validation error; script generation disabled.
- Disabled/unavailable Agent or Embed: non-enumerating public unavailable response.
- Denied parent origin: iframe blocked by `frame-ancestors`; session creation also rejects the origin.
- Invalid Embed token or conversation owner: generic authentication/not-found boundary.
- Invalid frontend Tool definition: filter that Tool and continue the run.
- Removed frontend Tool: `frontend_tool_unavailable` Tool Result.
- Frontend Tool timeout or exception: bounded error Tool Result; no backend dispatch.
- Backend Tool authorization required: structured authorization event.
- OAuth popup blocked: user-actionable retry message.
- OAuth state invalid, expired, replayed, or owner-mismatched: reject without creating or exposing credentials.
- AG-UI stream interruption: retain the conversation state already committed and offer a retry; never replay completed Tool calls automatically.

## Limits

Initial limits are deliberately conservative and may be constants in the first release:

- maximum 64 frontend Tools per run;
- maximum 256 KiB total encoded frontend Tool definitions;
- maximum 64 KiB frontend Tool arguments;
- maximum 1 MiB frontend Tool result;
- maximum 30 seconds per frontend Tool invocation;
- one frontend Tool invocation at a time unless later capability negotiation explicitly enables concurrency;
- Embed Session idle and absolute lifetimes configured server-side;
- Embed Auth Grant lifetime no longer than five minutes.

## Testing

### Backend

- migration and model constraints for Base URL, Embed, Embed Session, conversation ownership, Tool Session ownership, and Auth Grants;
- Base URL validation and settings authorization;
- Embed CRUD, soft deletion, Agent availability, and public ID entropy;
- script generation and absence of secrets;
- dynamic CSP and origin normalization;
- Embed Session creation, hashing, expiry, revocation, and owner isolation;
- AG-UI lifecycle, streaming text, backend Tool dispatch, and client-provided Tool Call events;
- frontend Tool definition validation and limits;
- prevention of frontend Tool dispatch through the backend executor;
- OAuth PKCE state binding, callback, token exchange, Auth Grant atomic consumption, replay prevention, refresh, and revocation;
- Swagger login ownership and logout;
- non-enumerating public errors and concurrency behavior.

### Frontend

- System Settings Base URL form;
- API Source OAuth callback display;
- Embed panel CRUD, script copy, and preview;
- loader Logo, open/close, configured position, keyboard operation, and responsive sizing;
- fixed Agent embedded Chat;
- AG-UI stream rendering and cancellation/error states;
- WebMCP unsupported, supported with no Tools, valid Tools, invalid Tool filtering, dynamic removal, success, timeout, and failure;
- authorization prompt, popup blocking, cancellation, grant exchange, retry, and logout;
- English and Simplified Chinese locale coverage.

### Integration

Add a controlled host-page fixture that registers WebMCP Tools and exposes them to the Embed origin. Verify the complete browser flow from loader to iframe, AG-UI run, WebMCP page operation, Tool Result, and Agent reply. Add a second fixture without WebMCP to confirm the Widget remains functional and silent about the absent capability.

## Documentation

- Keep README content limited to the introduction and quick start.
- Insert `docs/images/demo.png` immediately below the existing workflow image in `README.md` and `README.zh-CN.md`, with localized alt text.
- Add detailed Embed, AG-UI, WebMCP, OAuth, Swagger login, origin, and operational documentation to the GitHub Wiki after implementation.

## Delivery Boundaries

The feature is one coordinated release because its security model spans migrations, backend ownership, AG-UI transport, public loader, iframe application, administration UI, OAuth callback behavior, tests, and documentation. Implementation should still be divided into independently verifiable layers: persistence/settings, Embed management, public loader/session, AG-UI transport, WebMCP bridge, authorization flows, UI integration, and documentation.
