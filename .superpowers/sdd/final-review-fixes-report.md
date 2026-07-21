# Final review fixes report

Date: 2026-07-21
Base: `fc7422f`

## Status

Implemented every Critical/Important finding from the final whole-branch review, plus the requested Agent timestamps and database constraints.

## Changes

- Compatibility history: OpenAI and Anthropic requests normalize and persist the complete incoming system/user/assistant transcript, including Anthropic top-level `system`. New compatibility conversations expose the full transcript to the Agent. Existing server conversations append only the non-overlapping suffix.
- Default Agent policy: replaced the short prompt with the complete shared operating policy. Migration `0005` seeds it for fresh databases; `0007` upgrades only blank/whitespace or the exact known legacy short prompt and preserves custom prompts.
- Schema validation: added direct `jsonschema` dependency and validates `load_skills`, `ask_user`, and business Tool arguments before execution. Invalid calls become structured observations; business runners are not invoked.
- Candidate continuation: persists `candidate_scope_source`, retains the initial automatic catalog across later catalog changes, rejects explicit changes, filters stopped/deleted candidates on existing conversations, and drops unavailable loaded Skills and their Tools.
- Shared Tools: unions/deduplicates by Tool ID. A Tool row shared by multiple Skills is exposed once; distinct Tool IDs with the same name produce a deterministic conflict. Migration `0007` removes the prior global Tool-name uniqueness constraint so real collisions can be represented and handled at runtime.
- Failure state: every turn starts as `running` with a cleared failure summary. Provider, credential decryption, malformed response, unexpected runtime, configuration, name-conflict, and iteration-limit failures persist a redacted `latest_failure_summary` and raise structured `AgentError`/API envelopes.
- Persistence/API: added Agent `created_at`/`updated_at`, Conversation `latest_failure_summary`, Agent mode/max-iteration database checks, timestamp response fields, and matching frontend contracts.

## TDD evidence

- First focused RED: 11 behavior failures / 25 passes for shared Tool handling, schema validation, candidate degradation, and compatibility transcripts. One additional collision fixture exposed the pre-existing global Tool-name unique constraint and drove the `0007` schema change.
- Second focused RED: 14 failures / 20 passes for prompt migration, timestamps, checks, automatic scope continuation, transcript delegation, and redacted failure state.
- Additional RED/GREEN cycles covered stopped loaded Skills, existing-conversation provider configuration failure, and the frontend timestamp contract build error.

## Verification

- `conda run -n chatapi pytest backend/tests -q` — 149 passed.
- `conda run -n chatapi ruff check backend/src backend/tests` — All checks passed.
- Migration coverage includes fresh upgrade, existing `0006` upgrade, exact legacy/custom prompt behavior, `0007` downgrade/re-upgrade, database constraints, and removal of global Tool-name uniqueness.
- `D:\nvm\nodejs\npm.cmd test` — 8 files, 59 tests passed.
- `D:\nvm\nodejs\npm.cmd run build` — `vue-tsc --noEmit` and Vite production build succeeded.
- `git diff --check` — clean (line-ending conversion warnings only).

The two existing Vitest `fireEvent.change` advisories remain unrelated and non-failing.

## Follow-up review fixes

- Compatibility alias continuation: `skill-<id>` validates stopped/deleted state only when creating a conversation. Existing conversations delegate availability filtering to `AgentRuntime`, so unavailable single-skill scopes fail as `agent.no_eligible_skills` while persisting `failed` and `latest_failure_summary`; future multi-candidate scopes can continue with remaining eligible Skills.
- Browser scope locking: continuation validation now distinguishes an omitted candidate field from an explicitly supplied empty list. Explicit scopes reject `[]`, automatic scopes accept `[]`, and omitted fields inherit the persisted scope. Compatibility requests with an explicitly empty extension now persist an automatic scope.
- Migration downgrade safety: `0007` deterministically preserves colliding Tool rows by retaining the lowest-ID original name and renaming later collisions to a bounded `__legacy_<id>` form (with a deterministic suffix if needed) before restoring the unique constraint.

### Follow-up TDD evidence

- Initial focused RED: 5 failures / 1 pass for stopped/deleted alias continuation, explicit-empty scope locking, omitted-field continuation, and collision-data downgrade. The omitted-field failure exposed only a test fixture lifetime issue and was corrected to share its sequenced provider.
- Additional RED: 1 failure for an explicit empty compatibility extension being persisted as an explicit scope.
- Focused GREEN: 6 passed, followed by 1 passed for the compatibility empty-extension case. Related runtime/API/migration coverage: 65 passed.

### Final verification after follow-up

- `conda run -n chatapi pytest backend/tests -q` — 155 passed.
- `conda run -n chatapi ruff check backend/src backend/tests` — All checks passed.
- `D:\nvm\nodejs\npm.cmd test` — 8 files, 59 tests passed.
- `D:\nvm\nodejs\npm.cmd run build` — `vue-tsc --noEmit` and Vite production build succeeded.
