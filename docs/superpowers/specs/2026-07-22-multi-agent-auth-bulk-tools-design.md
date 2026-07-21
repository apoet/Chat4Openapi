# Chat4Openapi Multi-Agent, Authentication, and Bulk Tool Design

**Date:** 2026-07-22  
**Status:** Approved in conversation; awaiting written-spec review

## 1. Goals

This change extends the existing Agent runtime with:

- multiple independently configured Agents;
- an Agent selector in Chat instead of direct Skill selection;
- per-Agent ordered Skill bindings;
- multiple inbound API keys per Agent;
- authenticated OpenAI- and Anthropic-compatible APIs;
- business-identity Tool Sessions supporting OAuth and legacy authentication;
- bulk enable, disable, and soft-delete operations for Tools;
- a larger, denser, searchable Tool panel in the Skill editor; and
- a complete product and package rename from ChatAPI to Chat4Openapi.

The existing SQLite data, imported APIs, Tools, Skills, conversations, and history must survive the migration.

## 2. Product Rename

The canonical product name is `Chat4Openapi`. The old name is not retained as a compatibility alias because the product has not been publicly released.

Rename all product-owned identifiers:

- Python import package: `chatapi` to `chat4openapi`;
- Python distribution and executable/module examples;
- frontend package metadata, document title, visible branding, and default Agent name;
- environment variables to `CHAT4OPENAPI_*`;
- request headers to `X-Chat4Openapi-*`;
- compatible-API extension fields to `chat4openapi_*`;
- encryption-key and default SQLite filenames;
- Alembic configuration, tests, fixtures, documentation, logs, and examples.

The generic database table names remain unchanged. On startup, if an old default database or encryption-key filename exists and the new filename does not, perform a one-time safe file migration. Never overwrite a new file. The final verification performs a case-insensitive repository scan and fails if the old product name remains in tracked code or documentation.

## 3. Multi-Agent Persistence

Replace the singleton Agent configuration with a multi-row `agents` model. Each Agent contains:

- ID and display name;
- enabled and soft-deleted state;
- exactly one default designation across active Agents;
- provider ID and optional model override;
- system prompt;
- mode: `human_in_loop` or `react`;
- maximum iteration count;
- created, updated, and deleted timestamps.

Add `agent_skills` with `agent_id`, `skill_id`, and `position`, unique on `(agent_id, skill_id)`. This relationship is the only Skill catalog an Agent may dynamically load. Stopped Skills remain bound but are excluded at runtime.

Add non-null `agent_id` to conversations. A conversation's Agent is immutable after its first turn. An explicit attempt to change it returns `409 chat.agent_locked`.

Migration behavior:

- migrate the existing singleton to the first Agent without losing its configuration;
- mark it as the default Agent;
- bind all non-deleted Skills in stable order, preserving the existing all-Skills behavior;
- associate all existing conversations with it;
- preserve candidate/loaded Skills, pending clarification, messages, failures, and history.

The database and application together ensure there is one active default Agent. Setting a new default is transactional. The current default cannot be disabled or deleted until another enabled Agent becomes default.

## 4. Agent Administration

The Agent administration page becomes a list plus editor. It supports:

- create and edit;
- enable and disable;
- soft delete;
- set as default;
- provider, model, prompt, mode, and iteration configuration;
- searchable multi-selection and ordering of bound Skills; and
- management of multiple Agent API keys.

Enabling an Agent requires an enabled, non-deleted provider and at least one bound, running Skill. A stopped Skill keeps its binding but is unavailable to the runtime.

A provider referenced by any active Agent cannot be disabled or deleted. The error includes the referencing Agent IDs so the administrator can reconfigure them.

## 5. Chat and Compatible APIs

The Chat page removes the Skill multi-selector and adds a single Agent selector below the input. A new conversation initially selects the default Agent. Only enabled, non-deleted, runnable Agents are listed.

The Agent is locked after the first message. New Chat permits selecting another Agent. Browser history stores the Agent ID and a display-name snapshot. Old local history preserves messages but discards the old direct Skill selection; server conversation state supplies the migrated Agent association.

The selected Agent dynamically loads only its bound, running Skills. Browser Chat no longer sends candidate Skill IDs.

Compatible API model behavior:

- `agent-default` means the Agent bound to the presented API key;
- `agent-<id>` is accepted only when it matches the key-bound Agent;
- `skill-<id>` remains a candidate-scope alias, but the Skill must be bound to the key-bound Agent;
- `chat4openapi_skill_ids` remains an optional scope extension within the key-bound Agent's Skill catalog.

Complete incoming OpenAI/Anthropic transcripts and system prompts continue through the existing canonical Agent history behavior.

## 6. Agent API Keys

Each Agent supports multiple API keys for rotation and distinct integrations. A key stores:

- ID, Agent ID, label, prefix, and secret hash;
- enabled state;
- optional expiry;
- created, updated, and last-used timestamps; and
- soft deletion/revocation state.

The plaintext key is returned once at creation. It is never stored or returned again. Compatible APIs require `Authorization: Bearer <Agent API Key>`:

- missing, invalid, expired, or revoked keys return 401;
- a valid key used to request another Agent returns 403;
- key revocation immediately invalidates Tool Sessions created by that key.

Browser Chat continues to use the authenticated browser session and never exposes Agent API keys.

## 7. Business Identity and Tool Sessions

Agent API keys authenticate access to Chat4Openapi. They do not represent the end user's identity in the upstream business API. Authenticated Tools therefore use a separate, encrypted, short-lived Tool Session.

Each Tool Session is bound to:

- an Agent;
- the Agent API key that created it, or the authenticated browser session;
- one or more allowed API sources and their encrypted credentials;
- status, expiry, and last-used time.

Statuses are `authorization_required`, `pending`, `ready`, `expired`, `revoked`, and `failed`.

Supported credential establishment modes, in preferred order:

1. **OAuth 2.0 Device Authorization Grant** for CLI and headless clients. Return the verification URI, user code, polling interval, and expiry.
2. **Authorization Code with PKCE** for web administration and business frontends. User interaction occurs at the upstream authorization server, not inside a Tool call.
3. **External authentication and credential injection** for upstream systems without OAuth. Both a manual UI and a programmatic API accept pre-obtained Token/Cookie values.
4. **Swagger login automation** only for traditional login endpoints without CAPTCHA, MFA, or other interactive challenges.

OAuth and CAPTCHA interaction always occurs before the compatible chat request. An OpenAI/Anthropic request cannot pause for a redirect. It supplies `X-Chat4Openapi-Tool-Session`. Missing credentials produce `tool_authorization_required`; expired or rejected credentials produce `tool_reauthorization_required`.

Credential injection is allow-listed per API source. Only configured Header and Cookie names are accepted. Host, content-length, forwarding, and other transport-sensitive headers are always prohibited. Secrets are encrypted, never returned after creation, and never written to logs. A JWT expiry may cap the Tool Session expiry, but decoding a JWT is not treated as identity verification.

## 8. Tool Session APIs

Provide authenticated endpoints for:

- starting OAuth Device Flow;
- starting Authorization Code + PKCE;
- receiving the OAuth callback;
- creating a Session from injected credentials;
- invoking configured Swagger automatic login;
- reading Session status; and
- revoking a Session.

These endpoints require either the bound Agent API key or the authenticated browser administrator/session context. Cross-Agent, cross-key, and cross-source reuse is rejected.

## 9. Bulk Tool Administration

The Tools page adds row selection and a bulk action bar. Selection persists across source/tag expansion and search changes. `Select visible` affects only currently visible rows; hidden filtered rows are never selected implicitly. Successful items are removed from selection while failed items remain selected for retry.

Bulk operations are:

- enable;
- disable; and
- soft delete.

Delete requires confirmation showing the Tool count and affected API sources. A request contains at most 200 unique positive Tool IDs.

The backend uses partial-success semantics and returns request count, succeeded items, and per-item failures with localized error codes and parameters. Repeated enable/disable is idempotent success. Missing or deleted Tools are failures. A single failure does not roll back unrelated successful items.

## 10. Skill Tool Panel

The Skill editor's right-hand Tool panel becomes taller, vertically resizable, and denser. The preferred height is stored locally but failure to access browser storage does not break editing.

Each compact row shows Tool name, HTTP method, path, API source, tags, and enabled state. Search matches name, description, path, tags, and source. Filters cover API source, Swagger tags, and enabled state. Source and original Swagger hierarchy remain collapsible.

The `@tool` prompt reference picker and the right-hand binding panel use the same search/group index. Non-deleted stopped Tools remain visible with an explicit state marker; normal Skill-start validation still determines whether the Skill can run.

## 11. API Surface

Agent administration includes list/create, get/update/delete, enable/disable, set-default, ordered Skill bindings, and Agent-key management endpoints.

Tool administration adds one bulk endpoint for enable, disable, and soft delete.

Tool Session endpoints cover OAuth starts/callback, credential injection, Swagger login, status, and revocation.

Representative errors include:

- `agents.default_required`;
- `agents.default_cannot_disable`;
- `agents.default_cannot_delete`;
- `agents.provider_unavailable`;
- `agents.no_running_skills`;
- `chat.agent_locked`;
- `auth.agent_key_required`;
- `auth.agent_key_invalid`;
- `auth.agent_key_forbidden`;
- `tool_authorization_required`;
- `tool_reauthorization_required`; and
- `tools.batch_limit_exceeded`.

## 12. Security and Failure Handling

- API keys are high-entropy, hashed at rest, and shown once.
- OAuth verifier, access, and refresh tokens are encrypted at rest.
- Authentication errors never expose whether a full secret exists.
- Agent/key/Tool Session binding is checked on every compatible request and Tool execution.
- Revocation takes effect before subsequent Tool execution.
- Partial bulk results never expose internal exception text.
- HIL remains limited to business-parameter clarification; it never approves Tool calls or performs OAuth interaction.

## 13. Testing and Acceptance

Automated coverage includes:

- singleton-to-multi-Agent migration and existing conversation association;
- Agent CRUD, default switching, Skill binding/order, and provider protection;
- API key one-time display, hashing, expiry, revocation, and cross-Agent isolation;
- all four Tool Session credential modes, refresh, expiry, and revocation;
- Chat Agent selection, conversation locking, HIL, history migration, and refresh;
- OpenAI/Anthropic key-to-Agent binding and cross-Agent 403 behavior;
- Tool bulk partial success, idempotency, limits, and UI selection behavior;
- large Tool catalog search/filter/grouping, compact presentation, resizing, and `@tool` reference;
- complete package/product rename and absence of the old product name; and
- fresh and existing SQLite migration upgrade/downgrade/re-upgrade paths.

Browser acceptance uses two Agents with different Skill bindings, verifies that each can only load its own Skills, exercises bulk Tool operations, and completes an authenticated Tool call using a pre-authorized Tool Session. The compatible API acceptance verifies required API-key authentication and a headless authorization-required response.

## 14. Non-Goals

- Solving or bypassing CAPTCHA/MFA inside Chat4Openapi.
- Persisting plaintext upstream passwords, API keys, Tokens, or Cookies.
- Changing Tool execution into an approval workflow.
- Letting Chat directly select Skills.
- Synchronizing browser conversation history across user accounts.
