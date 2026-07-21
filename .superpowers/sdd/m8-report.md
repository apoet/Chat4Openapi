# M8 Report — Multi-Agent Administration UI

## Delivered

- Replaced the singleton Agent settings page with a responsive master-detail administration workspace.
- Added Agent list, create/edit, enable/disable, set-default, and soft-delete controls.
- Added enabled Provider selection and localized backend protection errors.
- Added searchable, explicitly ordered Skill bindings with add/remove/up/down controls. Bound stopped Skills remain visible and removable.
- Missing/deleted bound Skills remain visible as localized `Unavailable Skill #id` placeholders and can be removed on the next save.
- Added multi-key creation and metadata display for label, prefix, effective status, expiry, and precise last-used time.
- Added backend-supported key metadata editing for label and expiry using `PATCH`; no unsupported re-enable action is shown.
- Added the backend-supported key actions: revoke and delete. No unsupported re-enable action is shown.
- Reconciled two-step Agent saves: metadata responses enter Pinia immediately, binding failures refresh authoritative state, partially-created Agents become the current selection, and duplicate saves are blocked while pending.
- Added selection and key-load generations so late initial/list responses cannot replace newer state.
- Kept a newly created key secret only in `AgentKeyPanel` component memory. It is stripped before key metadata enters Pinia and cleared on close, Agent change, and component unmount. Agent selection and further key creation remain locked until the one-time secret is closed.
- Bound key creation responses to Agent id, generation, and mount lifetime. A late response after unmount/selection change is immediately deleted (with revoke fallback) and is never displayed under another Agent.
- Added a native dialog with initial focus, Escape dismissal, focus restoration, copy success/failure feedback, and `aria-current` Agent selection semantics.
- Added complete English and Simplified Chinese strings, accessible control names, and responsive layouts.
- Removed the legacy singleton Agent store and `/api/admin/agent` client routes.

## TDD evidence

- Original M8 RED: focused suite initially had 8 expected failures out of 9 tests (7 Agent administration behaviors plus the new locale coverage); locale tree parity remained green.
- Review RED: `npm test -- --run src/__tests__/agent-view.spec.ts src/__tests__/agents-store.spec.ts src/__tests__/locale-coverage.spec.ts` — 7 expected failures out of 14 tests, covering the four Important findings and requested regressions.
- Review GREEN: the same focused command — 3 files, 14 tests passed.
- Full frontend: `npm test` — 9 files, 64 tests passed.
- Type checking: `npm run typecheck` — passed.
- Production build: `npm run build` — passed.
- Lint: no lint script is defined in `frontend/package.json`.
- `git diff --check` — passed (only Git line-ending notices).

All Node commands used `D:\\nvm\\nodejs\\npm.cmd`.

## Security and migration scan

- No production test secret literal was found outside tests.
- Agent key secret references are limited to the response contract, a local component `ref`, clipboard copy, and destructuring that removes the secret before Pinia storage. A delayed-response regression test also asserts the secret never reaches Pinia or the wrong Agent view.
- No Agent key code reads or writes `localStorage` or `sessionStorage`; existing locale and M9 Chat storage are unrelated.
- No legacy `/api/admin/agent`, `useAgentStore`, or reset/default-singleton labels remain in frontend source.

## Backend contract findings

1. Agent create cannot atomically create an enabled Agent with Skill bindings: `POST /api/admin/agents` validates running bindings before the separate `PUT /{id}/skills` can occur. The UI safely creates disabled, then writes bindings, and leaves enable as an explicit action.
2. Agent API keys have revoke and delete endpoints but no re-enable endpoint. The UI intentionally does not offer key enable.
3. Agent metadata and ordered Skill bindings are separate writes, so an update can partially succeed if the second request fails. The UI now preserves the successful metadata response, refreshes/reconciles authoritative state, selects a newly-created Agent by its returned id, and reports the partial failure. A truly atomic save would still require a backend contract change.

M9 Chat behavior was not changed.
