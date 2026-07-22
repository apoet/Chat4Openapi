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
- Wrapped `set_tool_auth` and `start_skill` validation/mutation in the same serialized write boundary. Pre-lock Tool, Source, Skill, binding, and auth identity-map state is expired and re-read after acquiring the SQLite write lock.
- Kept safe-state operations within scope: clearing auth is covered by the serialized `set_tool_auth` path; `stop_skill` only transitions toward the invariant and needs no availability validation.
- M11 frontend selection and bulk-action UI were not changed.

## TDD evidence

- RED: `conda run -n chatapi pytest backend/tests/test_admin_tools_bulk.py -q` — 16 expected failures; the missing route returned 405 and direct transaction tests reported the missing handler.
- GREEN: the same focused command — 16 tests passed.
- Existing Tool and Skill regression suite: `conda run -n chatapi pytest backend/tests/test_admin_tools_bulk.py backend/tests/test_tool_api.py backend/tests/test_skills_api.py -q` — 33 tests passed.
- Full backend: `conda run -n chatapi pytest backend/tests -q` — 305 tests passed.
- Review RED: four real-file SQLite, two-Session/thread/event races failed after a validator Session retained stale ORM objects while batch disable/delete committed first.
- Review GREEN: focused bulk suite — 20 tests passed; bulk + existing Tool/Skill suites — 37 tests passed.
- Review full backend: `conda run -n chatapi pytest backend/tests -q` — 309 tests passed.
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
- stale `set_tool_auth` versus batch disable/delete, preventing enabled auth from referencing a disabled/deleted Tool; and
- stale `start_skill` versus batch disable/delete, preventing a running Skill from retaining an unavailable Tool.

All Python commands used the existing `chatapi` conda environment.
