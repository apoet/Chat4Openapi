# M9 Report — Chat Agent Selection and History

## Delivered

- Replaced browser Chat's direct Skill multi-selector with an accessible single-Agent selector below the composer. It lists only enabled, non-deleted Agents and preselects the enabled default for each New Chat.
- New Conversations send `agent_id`; continuations send only `message` and `conversation_id`. Browser Chat no longer sends `candidate_skill_ids`, and the deleted `SkillMultiSelect` has no production references.
- Agent selection locks while a turn is pending and once a Conversation exists. New Chat unlocks and reselects the current default. With no eligible Agent, Send is disabled.
- Extended the browser Chat response with authoritative `agent_id` and `agent_name`, read from the persisted Conversation and Agent. This closes the legacy-history contract gap without trusting client history.
- Migrated local history to v3 with `agentId` and `agentName` snapshots, messages, loaded-Skill display metadata, HIL status/pending state, and Conversation identity. Valid siblings survive malformed records.
- v1/v2 `skillId`/`skillIds` histories preserve messages, Markdown, loaded-Skill/HIL state, discard direct Skill selection, and initially carry no client Agent. They resume with only `conversation_id` and backfill Agent metadata solely from a successful server response.
- Inactive/deleted Agent snapshots remain visible and locked in history but are never selectable for a new chat. Server rejection of an unavailable historical Agent is localized in English and Simplified Chinese.
- Delayed turn successes and failures remain bound to their originating local session; navigating to New Chat or another history item cannot overwrite its Agent, messages, or error.
- Existing sanitized assistant Markdown, plain user content, clarification rendering, and loaded-Skill display remain intact.
- Browser Tool Session credentials remain in the existing HTTP-only cookie and credentialed request path. No Tool Session token, Agent API key, Authorization value, or other credential is written to local history or Chat request JSON.
- Added responsive Agent selector styling and kept English/Simplified Chinese locale keys in parity.

## Security review remediation

- Browser Chat now obtains its Agent catalog from anonymous `GET /api/chat/bootstrap`. The response contains only a public browser subject plus runnable Agent summaries (`id`, `name`, `is_default`); it has no prompt, provider, binding, key, or admin fields.
- Bootstrap establishes a high-entropy `HttpOnly`, `SameSite=Lax` browser-chat cookie. Only its SHA-256 hash is stored in `browser_chat_sessions`; bootstrap is the sole creator/rotator. Browser turns with a missing or unknown cookie return stable `chat.browser_session_required`, while expired or revoked cookies return `chat.browser_session_expired`, before subject creation or runtime execution.
- Conversations now have an immutable, database-constrained owner: exactly one `agent_key_id` or `browser_chat_session_id`. The sole exception is preserved, soft-deleted legacy ownerless rows. Migration `0012_conversation_owners` marks previously active ownerless rows revoked and unresumable without deleting them.
- Compatible API continuations require the exact active Agent API key that created the Conversation, even when another key belongs to the same Agent. Browser continuations require the exact browser subject. Both checks happen before Agent runtime execution.
- Browser Tool Session/admin/API-key credential context remains available solely to authorize Tool credentials and is separate from Conversation identity.
- Response Agent metadata is read only after owner validation. Ownership mismatches share the non-enumerating `agent.conversation_not_found` boundary.
- Local history is namespaced by the bootstrap `subject_id`; page-lifetime expiry triggers a fresh bootstrap, selects the new namespace, and prompts the user to start a New Chat and resend. The rejected turn is never replayed automatically, and the old namespace remains untouched.
- Legacy global history has one-time claim semantics: the first subject writes its namespaced copy before removing the global key. A failed namespaced write leaves the global history available for retry, while later subjects cannot re-import a successful claim.
- History parsing now explicitly accepts only unversioned/v1, v2, and v3 records. Unknown versions are isolated from the UI and preserved without field/value loss through subsequent local saves rather than interpreted as legacy or dropped.
- Removed the unused `ChatOrchestrator` compatibility shim and its dedicated tests; production and test trees contain no remaining references.

## TDD evidence

- Backend authoritative-Agent response RED: `1 failed` (`agent_id` absent); GREEN: `1 passed`.
- Agent selector/default/creation body/pending lock RED: `1 failed` (no Agent combobox); GREEN: `1 passed`.
- New Chat default reset RED: `1 failed` (previous Agent remained selected); GREEN: `1 passed`.
- History v3/legacy authoritative backfill RED: `1 failed` (v2 Skill history remained); GREEN: `1 passed`.
- Inactive historical Agent error RED: `1 failed` (raw `agent.unavailable`); GREEN: `1 passed` with localized text.
- No-enabled-Agent guard RED: `1 failed` (Send remained enabled); GREEN: `1 passed`.
- Public bootstrap RED: `2 failed` (404); GREEN: `2 passed` with anonymous/non-admin coverage and field allowlisting.
- Missing/forged/expired browser turn sessions RED: turns either created a subject, rotated a cookie, or entered normal Conversation handling; GREEN: stable required/expired 401 responses, no model call, no subject creation, and no `Set-Cookie`. Bootstrap rotation and original-subject restoration remain covered (`4 passed`).
- Exact same-Agent API-key isolation RED: foreign key reached the runtime; GREEN: denied before runtime, with revoked/deleted owner-key continuation coverage (`3 passed`).
- Frontend subject namespace RED: bootstrap and subject-specific history tests failed; GREEN: public bootstrap/no-admin and cross-subject history isolation passed.
- Page-lifetime expiry recovery RED: the raw backend error remained visible; GREEN: the client re-bootstraps, switches namespaces, prompts New Chat/resend, and performs exactly one turn request with no automatic replay.
- Legacy one-time claim RED: the global key remained available and a second subject re-imported it; GREEN: successful claim removes it only after the namespaced write, and simulated quota failure preserves it (`2 passed`).
- Unknown history version coverage preserves a v4 payload unchanged and keeps it out of the rendered history.

## Verification

- Focused browser-turn backend: `18 passed`.
- Focused frontend Chat: `21 passed`.
- Full frontend: `9 files, 76 tests passed`.
- Frontend typecheck: passed.
- Frontend production build: passed.
- Full backend: `289 passed`.
- Focused owner/migration model suite: `5 passed`; Alembic schema, legacy ownerless-row handling, downgrade/re-upgrade, and migration round-trip tests also passed as part of the full backend suite.
- Ruff on changed backend source/tests: `All checks passed!`.
- `git diff --check`: clean (Git emitted only line-ending notices).
- Production scans: no frontend `candidate_skill_ids`, `SkillMultiSelect`, Chat credential/token references, `ChatOrchestrator`, or `chat.orchestrator` references.

All Node commands used `D:\\nvm\\nodejs\\npm.cmd`; Python verification used the existing `chatapi` Conda environment.

## Scope

M10 bulk Tool operations were not implemented.
