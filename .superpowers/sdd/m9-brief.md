# M9 Brief — Chat Agent Selection and History

## Scope

- Replace direct browser Skill selection with one Agent selector below the composer.
- List enabled, non-deleted Agents and preselect the enabled default Agent for a new chat.
- Send `agent_id` only when creating a conversation. Continuations omit Agent and all candidate Skill fields so the server-owned Conversation association remains authoritative.
- Lock Agent selection as soon as the first turn is pending and keep it locked after a Conversation is persisted. New Chat unlocks and reselects the current default.
- Persist browser-local history v3 with an Agent id/name snapshot, messages, loaded Skill display state, HIL state, and conversation identity. Keep credential-bearing Tool Session state out of local storage.
- Migrate v1/v2 Skill histories one record at a time: preserve valid messages/Markdown/HIL, discard direct Skill selection, and resume a persisted Conversation without a client-supplied Agent.
- Preserve inactive/deleted Agent name snapshots for history, but never offer those Agents for a new chat. Let the server validate restored Conversations and surface a localized friendly failure.
- Preserve origin-session isolation for delayed successes/failures, block Agent changes and duplicate sends while pending, keep English/Simplified Chinese parity, accessibility, and responsive layout.
- Do not implement M10 bulk Tool administration.

## Backend contract constraints

- `POST /api/chat/turns` forbids extra fields. A new Conversation requires positive `agent_id`; a continuation may omit it and resolves immutable `Conversation.agent_id` server-side.
- Browser Chat must never send `candidate_skill_ids`.
- `/api/admin/agents` omits soft-deleted Agents but includes disabled ones; Chat filters to enabled entries and retains only history snapshots for inactive/missing entries.
- The baseline `ChatTurnResponse` does not expose Conversation Agent metadata and there is no browser Conversation-read endpoint. M9 adds the minimal authoritative response fields `agent_id` and `agent_name`: migrated pre-v3 history resumes by omitting `agent_id`, then backfills its v3 snapshot only from the successful server response. It must never guess the current default.
- Browser Tool Session credentials are held in an HTTP-only cookie and forwarded by the existing credentialed request path. They must not be copied into local storage or request JSON.

## TDD acceptance checks

- Two-Agent selector defaults correctly, is accessible, and excludes disabled/deleted options.
- First turn sends `{message, conversation_id: null, agent_id}`; continuation sends only message plus conversation id.
- Selector locks during the first pending turn and after persistence; New Chat unlocks and resets to the current default.
- A late Agent switch or late turn result cannot alter another local session.
- v3 refresh keeps a persisted Conversation locked and shows the saved Agent snapshot.
- v1/v2 migration preserves messages, Markdown, HIL and loaded-Skill display state while removing `skillId`/`skillIds`.
- A successful legacy continuation returns and persists authoritative Agent id/name metadata from the server.
- A malformed history record is dropped without discarding valid siblings.
- An inactive/missing Agent snapshot remains visible only in history; restored server failures are localized and do not unlock or silently reassign the Conversation.
- Focused chat/Markdown/locale tests, the full frontend suite, typecheck, build, diff/security/legacy-candidate scans all pass.
