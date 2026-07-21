# Skills, LLM Chat, and Compatibility API Implementation Plan

**Status:** Core implementation complete. Remaining hardening includes transparent peripheral
provider proxying, incremental upstream streaming/cancellation, and external authenticated client
end-to-end fixtures.

**Goal:** Configure OpenAI/Anthropic-compatible model providers, compose enabled managed Tools into startable Skills, run Tool-aware conversations, and expose OpenAI and Anthropic compatible APIs plus a bilingual chat UI.

**Architecture:** Provider credentials remain encrypted at rest and are decrypted only for outbound model requests. A Skill is a declarative prompt plus an ordered allow-list of enabled Tools and an explicit running state. The chat orchestrator translates one canonical message/tool-call model to provider-specific payloads, injects the request's Tool Session outside the LLM-visible Tool schema, executes only Skill-bound Tools, and continues until a final assistant message or bounded iteration limit. Compatibility endpoints reuse the same orchestrator.

## Global Constraints

- Provider API keys and original-API user credentials never appear in API responses or logs.
- Only enabled, non-deleted Tools may be bound; the configured login Tool is never bindable.
- The Skill editor must provide one-click insertion/reference for every currently enabled eligible Tool.
- Stopped Skills cannot be selected or invoked.
- A Tool Session is request/session scoped and is injected by the orchestrator, never chosen by the model.
- Tool loops have explicit iteration, token, timeout, and output-size bounds.
- English remains the default UI language; every new UI key has Simplified Chinese parity.

### Task 1: Provider, Skill, and Conversation Persistence

- Add `LlmProvider`, `Skill`, `SkillTool`, `Conversation`, and `ChatMessage` models and migration.
- Enforce unique provider/Skill names, ordered Skill bindings, and retained conversation audit metadata without secret content.
- Add migration upgrade/downgrade/upgrade and model constraint tests.

### Task 2: Encrypted LLM Provider Adapters

- Add administrator CRUD/test APIs for OpenAI-compatible and Anthropic-compatible providers.
- Encrypt API keys with the existing `SecretCipher` and return only `has_api_key`/masked metadata.
- Implement canonical streaming/non-streaming provider adapters with HTTPX mock tests.
- Transparently proxy supported peripheral provider endpoints while applying configured base URL and secret headers.

### Task 3: Declarative Skills and Runtime State

- Add Skill CRUD, Tool binding, start, and stop APIs.
- Reject disabled/deleted/login Tools and automatically stop a Skill whose provider becomes unavailable.
- Build LLM-visible Tool schemas from bound Tools while hiding `tool_session_id` from the model.
- Test lifecycle conflicts, ordering, and runtime eligibility.

### Task 4: Tool-Aware Chat Orchestrator

- Implement canonical messages, tool calls, tool results, streaming events, and bounded model/Tool loop.
- Inject the caller's Tool Session into every Tool execution and preserve one identity across all calls.
- Add cancellation, timeout, redaction, request IDs, and structured error mapping.
- Test multi-Tool sequences, two-user isolation, stopped Skills, and 401 refresh behavior.

### Task 5: Compatible APIs

- Implement `/v1/models`, `/v1/chat/completions`, and OpenAI-compatible SSE chunks.
- Implement `/v1/messages` and Anthropic-compatible event streams and headers.
- Support explicit Skill selection and Tool Session input without leaking either into upstream provider payloads.
- Add contract fixtures for streaming and non-streaming compatibility.

### Task 6: Provider and Skill Administration UI

- Add bilingual provider list/editor/test views.
- Add Skill list/editor with provider selection, prompt editing, start/stop controls, and ordered Tool bindings.
- Place enabled eligible Tools in a searchable quick-reference tray; clicking a Tool binds it and inserts a stable reference at the editor cursor.
- Add component tests for quick reference, disabled Tool exclusion, lifecycle actions, and translations.

### Task 7: Chat UI and Original-API Login Gate

- Add the public chat route, conversation surface, streaming rendering, and retry/error states.
- Place the running Skill selector directly below the input as approved.
- If global Tool login is enabled, show original-API login before chat and reuse its one Tool Session for every call.
- Add responsive desktop/mobile and English/Chinese browser tests.

### Task 8: Completion Gate

- Run backend tests/Ruff, frontend tests/typecheck/build, MCP protocol tests, compatibility fixtures, and real-browser flows.
- Verify no plaintext provider/API-user secret in SQLite, logs, compatible responses, or frontend storage.
- Verify OpenAI and Anthropic clients can stream a Skill response that invokes an authenticated imported Tool.
