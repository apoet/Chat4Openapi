# Task 2 Report: Multi-Agent Persistence

## Outcome

Implemented migration `0008_multi_agent` and the foundational `Agent`,
`AgentSkill`, and `AgentApiKey` ORM models. The migration replaces the singleton
table with multi-Agent persistence, binds active Skills in stable ID order, and
associates every historical Conversation (including soft-deleted rows) with the
migrated default Agent.

## TDD evidence

- Initial focused run: 1 failed, 7 passed. The new migration test failed because
  `agents` did not exist.
- After the first migration slice: the singleton migration test passed.
- Conversation immutability test initially failed because a persisted
  `agent_id` could be reassigned; it passed after adding the ORM guard.
- Review follow-up reproduced a relationship assignment gap: changing
  `conversation.agent` did not immediately raise. A relationship-side validator
  made that path fail immediately while retaining initial assignment support.
- Final focused migration/model/database run: 12 passed.

## Implementation notes

- Copies all singleton configuration fields, including custom prompt, provider,
  model, mode, iteration limit, and timestamps, into Agent ID 1.
- Creates a SQLite partial unique index that guarantees at most one non-deleted
  default Agent.
- Creates ordered `agent_skills` rows for every non-deleted Skill using stable
  ascending Skill IDs and zero-based positions.
- Creates `agent_api_keys` with indexed prefixes, unique hashes, lifecycle
  timestamps, and cascading Agent ownership. Key generation, hashing, and
  authentication are intentionally deferred.
- Adds a non-null Conversation foreign key, backfills every historical row, and
  prevents reassignment through either the foreign-key or relationship attribute
  after ORM persistence.
- Downgrade reconstructs the singleton configuration from the active default
  Agent; downgrade/re-upgrade preserves configuration and re-associates history.
- `AgentConfig = Agent` and legacy API schema names are temporary compatibility
  aliases so the existing singleton runtime remains executable during M2. The
  primary model/schema names are now Agent-based.

## Verification

- Focused migration/model/database tests: 12 passed.
- Backend full suite: 167 passed.
- Ruff lint: passed.
- Ruff format check for all touched Python files: passed.
- Diff whitespace check: passed.
- Tracked legacy package-name scan: no matches.

## Concerns and deferred work

- M3 must replace the temporary ID-1 runtime default and compatibility aliases
  with explicit Agent selection, then remove the singleton semantics.
- Default switching/deletion policy and API behavior are application concerns
  intentionally outside this migration-only task.
- The partial unique index does not guarantee that a default exists. M3 must
  maintain the at-least-one active default invariant transactionally in the
  application.
- Agent key generation, storage hashing workflow, and authentication belong to
  M4 and were not implemented here.

## Review follow-up

- Added regression coverage for both direct `agent_id` and relationship-based
  reassignment after commit.
- Both paths now raise `ValueError("conversation agent cannot be changed")`;
  rollback and reload confirm the stored association remains unchanged.
- New Conversations can still establish their initial association using either
  `agent_id` or `agent`.
