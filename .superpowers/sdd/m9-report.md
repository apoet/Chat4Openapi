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

## TDD evidence

- Backend authoritative-Agent response RED: `1 failed` (`agent_id` absent); GREEN: `1 passed`.
- Agent selector/default/creation body/pending lock RED: `1 failed` (no Agent combobox); GREEN: `1 passed`.
- New Chat default reset RED: `1 failed` (previous Agent remained selected); GREEN: `1 passed`.
- History v3/legacy authoritative backfill RED: `1 failed` (v2 Skill history remained); GREEN: `1 passed`.
- Inactive historical Agent error RED: `1 failed` (raw `agent.unavailable`); GREEN: `1 passed` with localized text.
- No-enabled-Agent guard RED: `1 failed` (Send remained enabled); GREEN: `1 passed`.

## Verification

- Focused frontend Chat/Markdown/locale: `3 files, 19 tests passed`.
- Full frontend: `9 files, 70 tests passed`.
- Frontend typecheck: passed.
- Frontend production build: passed.
- Backend Chat contract: `11 passed`.
- Full backend: `281 passed`.
- Ruff on changed backend source/tests: `All checks passed!`.
- `git diff --check`: clean (Git emitted only line-ending notices).
- Production frontend scans: no `candidate_skill_ids`, `SkillMultiSelect`, candidate-Skill UI labels/classes, or Chat credential/token references.

All Node commands used `D:\\nvm\\nodejs\\npm.cmd`; Python verification used the existing `chatapi` Conda environment.

## Scope

M10 bulk Tool operations were not implemented.
