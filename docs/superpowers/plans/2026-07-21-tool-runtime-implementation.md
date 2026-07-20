# OpenAPI MCP Tool Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import OpenAPI 2.0/3.x operations as managed MCP Tools, execute them safely with one global original-API login per Tool Session, and expose administrator management APIs plus an MCP Streamable HTTP endpoint.

**Architecture:** OpenAPI documents are validated and normalized into a version-independent operation model. FastMCP 3.4.4 generates candidate Tool schemas, while ChatAPI persists lifecycle state and uses its own request-scoped HTTP executor. A singleton global login configuration creates encrypted, expiring Tool User Sessions whose authentication result is injected into every Tool call in that session.

**Tech Stack:** Existing FastAPI/SQLAlchemy/Alembic stack, FastMCP 3.4.4, openapi-spec-validator, PyYAML, HTTPX, cryptography/Fernet, pytest.

## Global Constraints

- Backend administrator identity never authenticates an imported API call.
- One enabled global login Tool authenticates each Tool Session once; that session identity is used by every Tool.
- Persistent API-user profiles do not exist. Session secrets are encrypted and deleted on logout or expiry.
- New imported Tools are disabled by default. Disabled Tools are absent from MCP discovery and cannot execute.
- The configured login Tool is excluded from ordinary Tool discovery and Skill binding.
- External `$ref` targets, arbitrary host overrides, loopback/link-local/private targets, unbounded redirects, and oversized responses are rejected unless the API Source explicitly trusts private networking.
- MCP callers pass `tool_session_id` as a Tool argument when global login is enabled; internal Skill callers receive session injection outside the LLM-visible schema in the next phase.
- All mutations require administrator session plus CSRF, except original-API Tool Session login/logout.

---

### Task 1: Tool Persistence and Migration

**Files:**
- Create: `backend/src/chatapi/models/api_source.py`
- Create: `backend/src/chatapi/models/tool.py`
- Create: `backend/src/chatapi/models/tool_auth.py`
- Create: `backend/src/chatapi/models/tool_session.py`
- Create: `backend/src/chatapi/models/tool_invocation.py`
- Create: `backend/migrations/versions/0002_tool_runtime.py`
- Modify: `backend/src/chatapi/models/__init__.py`
- Test: `backend/tests/test_tool_models.py`

**Interfaces:**
- Produces: `ApiSource`, `Tool`, `GlobalToolAuthConfig`, `ToolUserSession`, `ToolInvocation` SQLAlchemy models.
- `Tool` stores `input_schema`, `execution_schema`, `enabled`, `deleted_at`, and stable `operation_key` as JSON/text fields.

- [ ] Write a migration test asserting all five tables, singleton auth constraint, source/tool foreign keys, and unique `(api_source_id, operation_key)`.
- [ ] Run the test and observe missing-table failure.
- [ ] Add typed models and migration with cascading session/source relationships but retained invocation audit rows.
- [ ] Run migration upgrade/downgrade/upgrade tests and the complete backend suite.
- [ ] Commit with `feat: add Tool Runtime persistence`.

### Task 2: OpenAPI Validation, Normalization, and FastMCP Candidates

**Files:**
- Create: `backend/src/chatapi/tools/openapi_loader.py`
- Create: `backend/src/chatapi/tools/openapi_v2.py`
- Create: `backend/src/chatapi/tools/candidates.py`
- Create: `backend/tests/fixtures/openapi2.yaml`
- Create: `backend/tests/fixtures/openapi3.yaml`
- Test: `backend/tests/test_openapi_import.py`

**Interfaces:**
- Produces: `load_openapi(raw: bytes) -> dict[str, Any]`, `normalize_openapi(spec) -> dict[str, Any]`, and `build_candidates(spec, base_url) -> list[ToolCandidate]`.
- `ToolCandidate` fields are `operation_key`, `name`, `description`, `input_schema`, and `execution_schema`.

- [ ] Write failing tests for JSON/YAML, OpenAPI 2 body/query conversion, internal `$ref` conversion, external `$ref` rejection, duplicate names, and FastMCP-generated parameter schemas.
- [ ] Implement byte-size limits, safe YAML loading, `openapi-spec-validator`, and deterministic OpenAPI 2-to-3 normalization.
- [ ] Use `OpenAPIProvider.list_tools()` only to generate candidate MCP schemas; close its fixed unauthenticated HTTPX client immediately.
- [ ] Join provider Tools back to normalized operations by `operationId`, preserving parameter location and request-body metadata in `execution_schema`.
- [ ] Run import tests and commit with `feat: normalize OpenAPI into MCP Tool candidates`.

### Task 3: Safe Request-Scoped Tool Executor

**Files:**
- Create: `backend/src/chatapi/tools/network_policy.py`
- Create: `backend/src/chatapi/tools/executor.py`
- Create: `backend/src/chatapi/tools/errors.py`
- Test: `backend/tests/test_tool_executor.py`

**Interfaces:**
- Produces: `ToolExecutor.execute(tool, source, arguments, auth) -> ToolExecutionResult`.
- `RequestAuth` contains only request-scoped headers/cookies/query values produced from a Tool Session.

- [ ] Write failing tests for path/query/body placement, fixed host enforcement, private-address rejection, redirect/timeout/response limits, structured non-2xx errors, and JSON/text results.
- [ ] Implement DNS/IP policy with `ipaddress` and `socket.getaddrinfo`; allow private targets only when `ApiSource.allow_private_networks` is true.
- [ ] Implement HTTPX request construction with fixed base URL, 10-second connect, 30-second read, 60-second total Tool limit, three redirects, 1 MiB request and 4 MiB response limits.
- [ ] Run executor tests and commit with `feat: execute imported Tools safely`.

### Task 4: Global Login Configuration and Encrypted Tool Sessions

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/src/chatapi/security/encryption.py`
- Create: `backend/src/chatapi/tool_sessions/service.py`
- Create: `backend/src/chatapi/tool_sessions/auth_mapping.py`
- Test: `backend/tests/test_tool_sessions.py`

**Interfaces:**
- Produces: `create_tool_session(username, password)`, `resolve_tool_session(id)`, `revoke_tool_session(id)`, and `RequestAuth` mapping.
- Browser IDs live in HttpOnly `chatapi_tool_session`; API clients receive an opaque ID and storage keeps only its SHA-256 hash.

- [ ] Write failing tests for encrypted-at-rest credentials, user isolation, idle/absolute expiry, response JSON-path extraction, Bearer/custom-header/cookie injection, token refresh, and one retry after 401/403.
- [ ] Add explicit `cryptography>=45,<50`, load `CHATAPI_ENCRYPTION_KEY` or generate `data/.chatapi.key` with restrictive permissions, and implement Fernet JSON envelopes.
- [ ] Execute the configured login Tool without existing auth, store encrypted login input/result, and remove expired/revoked session ciphertext.
- [ ] Run Tool Session tests and commit with `feat: add global API-user Tool Sessions`.

### Task 5: Administrator Tool APIs and Public Tool Session APIs

**Files:**
- Create: `backend/src/chatapi/schemas/tools.py`
- Create: `backend/src/chatapi/api/admin_tools.py`
- Create: `backend/src/chatapi/api/tool_sessions.py`
- Modify: `backend/src/chatapi/main.py`
- Test: `backend/tests/test_tool_api.py`

**Interfaces:**
- Produces import/list/detail/enable/disable/delete/test APIs, global login configuration API, `/api/tool-session/login|status|logout`, `/v1/tool-sessions`, and direct Tool invocation.

- [ ] Write failing authorization and lifecycle tests, including rejection of disabling/deleting the configured login Tool.
- [ ] Add URL and multipart JSON/YAML import with SSRF/size checks and default-disabled Tools.
- [ ] Add soft deletion with conflict detection, Tool testing through an ephemeral Tool Session, and stable localized error codes.
- [ ] Add browser and API-client Tool Session endpoints and direct invoke endpoint with request-level session input.
- [ ] Run API tests and commit with `feat: expose Tool management and session APIs`.

### Task 6: Dynamic MCP Server

**Files:**
- Create: `backend/src/chatapi/mcp/runtime.py`
- Create: `backend/src/chatapi/mcp/tool.py`
- Modify: `backend/src/chatapi/main.py`
- Test: `backend/tests/test_mcp_runtime.py`

**Interfaces:**
- Produces Streamable HTTP `/mcp`, dynamic enabled-Tool discovery, and invocation through `ToolExecutor`.

- [ ] Write failing in-memory FastMCP client tests proving disabled/login Tools are absent and enabled Tools carry the correct JSON schema.
- [ ] Implement a FastMCP `Tool` subclass whose `run(arguments)` loads fresh DB state, removes `tool_session_id`, resolves request auth, and calls `ToolExecutor`.
- [ ] Refresh the dynamic registry after lifecycle mutations and mount `FastMCP.http_app(path="/")` at `/mcp` with application lifespan composition.
- [ ] Run MCP protocol tests and commit with `feat: expose managed Tools over MCP`.

### Task 7: Tool Management Frontend

**Files:**
- Create: `frontend/src/views/ApiSourcesView.vue`
- Create: `frontend/src/views/ToolsView.vue`
- Create: `frontend/src/views/ToolAuthView.vue`
- Create: `frontend/src/stores/tools.ts`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/layouts/AdminLayout.vue`
- Modify: locale files
- Test: `frontend/src/__tests__/tools-view.spec.ts`

**Interfaces:**
- Produces admin routes `/admin/sources`, `/admin/tools`, `/admin/tool-auth` with import, filtering, preview, lifecycle controls, and global login Tool binding.

- [ ] Write failing UI tests for JSON/YAML upload, default-disabled indicators, enable/disable/delete actions, login Tool selection, and translated empty/error states.
- [ ] Implement typed API store and accessible responsive views using the existing design system.
- [ ] Run frontend tests, typecheck, build, and a real-browser import/lifecycle smoke test.
- [ ] Commit with `feat: add Tool Runtime administration UI`.

## Phase 2 Completion Gate

Phase 2 completes only when OpenAPI 2.0 and 3.x fixtures import into identical managed Tool semantics, enabled Tools appear over MCP, two Tool Sessions remain identity-isolated, the login Tool cannot leak into discovery, unsafe target addresses are rejected, lifecycle management works from the bilingual UI, and all backend/frontend checks pass.
