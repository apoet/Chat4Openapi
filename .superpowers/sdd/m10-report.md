# M10 Report — Bulk Tool Backend Operations

## Delivered

- Added CSRF-protected administrator endpoint `POST /api/admin/tools/batch`.
- Added strict request validation for `enable|disable|delete`, a non-empty list of positive strict integer IDs, stable first-occurrence deduplication, and the 200-unique-ID limit with `tools.batch_limit_exceeded`.
- Added ordered partial-success responses with `request_count`, per-item `tool_id`, `action`, success `status`, and localized failure `code`/safe `params`.
- Added one outer `serialized_write` transaction and per-item nested savepoints. Successful items commit once; a rule or unexpected item failure rolls back only that item; an outer flush/commit failure rolls back the whole batch.
- Added `tools.batch_item_failed` as the sanitized unexpected per-item failure. Internal exception messages are not returned.
- Added shared `apply_tool_action()` lifecycle logic used by both batch and single Tool endpoints.
- Enabling requires an active, enabled API source. Disable/delete preserve login-Tool protection and stop running Skills bound to the affected Tool. Delete remains a soft delete.
- Wrapped source enable/disable/delete and single Tool enable/disable/delete in serialized SQLite writes so source constraints are re-read after lock acquisition and competing writers do not use stale ORM state.
- M11 frontend selection and bulk-action UI were not changed.

## TDD evidence

- RED: `conda run -n chatapi pytest backend/tests/test_admin_tools_bulk.py -q` — 16 expected failures; the missing route returned 405 and direct transaction tests reported the missing handler.
- GREEN: the same focused command — 16 tests passed.
- Existing Tool and Skill regression suite: `conda run -n chatapi pytest backend/tests/test_admin_tools_bulk.py backend/tests/test_tool_api.py backend/tests/test_skills_api.py -q` — 33 tests passed.
- Full backend: `conda run -n chatapi pytest backend/tests -q` — 305 tests passed.
- Ruff: `conda run -n chatapi ruff check backend` — passed.
- `git diff --check` — passed (only Git line-ending notices).

## Covered behavior

- administrator and CSRF enforcement;
- invalid action, empty list, non-positive IDs, and rejection of booleans, strings, and floats;
- the 201st unique ID and stable duplicate removal;
- ordered success/failure partitions and repeated enable/disable success;
- missing/deleted Tool, disabled/deleted source, and login Tool constraints;
- disabling and soft deleting Tools bound to running Skills;
- rollback of a mutation flushed inside a failed item savepoint, followed by successful later items;
- sanitization of unexpected item errors;
- rollback of every item when the final commit fails; and
- serialized SQLite source-disable versus batch-enable competition without a stale-state enable.

All Python commands used the existing `chatapi` conda environment.
