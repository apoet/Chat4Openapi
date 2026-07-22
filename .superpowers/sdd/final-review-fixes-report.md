# Final Branch Review Fixes

Date: 2026-07-22
Base: `6ef657b`

## Status

Complete. The final Important findings are covered by shared execution policy, focused regressions, repository-wide rename enforcement, and full backend/frontend verification.

The logout re-review is also complete: Agent-key DELETE and administrator browser logout are idempotent for already-revoked or invisible sessions while unexpected service and database failures still propagate.

## Authentication and execution guards

- Added one execute-time policy resolver shared by Agent execution, direct Tool invocation, and Tool Session execution. It refreshes the Tool, reloads its API Source, rejects missing/deleted/disabled state, and determines authentication from both the enabled global login configuration and an enabled source OAuth configuration.
- OAuth-protected Tools now return a stable authorization-required observation when the Agent has no usable Tool Session. Direct invocation requires a Tool Session before any upstream execution.
- Agent Tool Session failures are deliberately classified without exception messages: missing/unknown sessions request authorization; expired, revoked, or rejected sessions request reauthorization; only unexpected session failures use the generic session error.
- Direct invocation rejects unavailable sources before both session and no-session branches. Coverage exercises missing, deleted, and disabled sources for Agent-key and administrator owners, with and without a bound session, and verifies zero upstream calls.
- Tool Session execution repeats the shared policy check immediately before credential resolution and upstream execution to reduce state-change races.

## Tracked rename gate

- Replaced machine-local Conda environment names in tracked briefs/reports with neutral project-environment wording.
- Renamed two test module aliases that retained the legacy package spelling.
- Added a `git ls-files`-driven regression test. It reads every tracked path, including hidden reports, decodes content without excluding tracked files, and enforces case-insensitive absence of legacy product/package/environment/header/extension spellings. The searched token is assembled in the test so the gate cannot match itself.
- The gate resolves an absolute Git executable before entering a minimal child-process environment, avoiding Conda PATH/DLL leakage. Two consecutive final runs passed.

## TDD evidence

- Initial focused RED: 14 failed and 55 passed. Failures demonstrated OAuth Tools executing without a session, undifferentiated/leaky Agent session errors, revoked/rejected direct-invoke misclassification, unavailable-source execution in both session branches, and 17 tracked legacy-identifier lines.
- Focused GREEN: 77 passed across Agent runtime, Tool Session/direct invocation, and the tracked rename gate.
- The expanded source/owner matrix passed 12 cases: missing/deleted/disabled source × with/without Tool Session × Agent key/administrator.
- A pre-existing 201-row frontend test became slow under parallel full-gate load. It was split into independent over-limit rejection and exact-200 select/clear cases without increasing the timeout; focused execution passed 2/2 and the final full frontend suite passed.
- Logout replay RED was 2 failed and 2 passed: the second Agent-key DELETE and the second stale-cookie browser logout raised reauthorization-required, while cross-owner non-enumeration and unexpected-error propagation already passed. The minimal GREEN catches only not-found and reauthorization-required at those two logout boundaries; focused execution then passed 4/4.

## Fresh verification

- Focused backend: 77 passed.
- Expanded direct-source matrix: 12 passed.
- Related compatible/chat/direct/session/OAuth/migration run: 124 passed; its sole old-contract failure was updated from revoked-as-missing to the required revoked-as-reauthorization behavior, then the affected tests passed 2/2.
- Related credential/session/OAuth run after the logout fix: 79 passed. OAuth has no separate revoke/delete endpoint; OAuth-backed sessions use the same covered Tool Session logout paths.
- Full backend: 340 passed.
- Ruff over backend source, migrations, and tests: all checks passed.
- Full frontend: 10 files, 97 tests passed.
- Frontend typecheck: passed.
- Frontend production build: passed; 172 modules transformed.
- Tracked legacy-identifier scan: zero matches.
- `git diff --check`: passed.

## Safety notes

- Authorization and session observations contain only stable error codes and Tool names; session exception text and configured secrets are not returned to the model or direct caller.
- The direct API keeps its established HTTP envelope: missing session returns the existing session-required response, expired/revoked/rejected sessions return reauthorization-required, and unavailable sources return the existing source-not-found response.
