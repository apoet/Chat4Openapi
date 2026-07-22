# M10 Brief — Bulk Tool Backend Operations

## Scope

- Add authenticated, CSRF-protected `POST /api/admin/tools/batch` for `enable`, `disable`, and soft `delete`.
- Accept a non-empty list of strict positive integer Tool IDs, stable-deduplicate by first occurrence, and reject more than 200 unique IDs with `tools.batch_limit_exceeded`.
- Return `request_count`, ordered `succeeded`, and ordered `failed` collections. Successful items contain `tool_id`, `action`, and `status`; failures contain `tool_id`, `action`, localized `code`, and non-sensitive `params`.
- Preserve partial success using one outer serialized SQLite write transaction and one nested transaction/savepoint per item. Commit once after all items; an outer flush/commit failure is an endpoint error and rolls back the whole batch.
- Keep M11 frontend work out of scope.

## Shared lifecycle rules

Single-item and batch endpoints call the same Tool action function:

- missing or soft-deleted Tool: `tools.not_found`;
- enable: source must exist, be enabled, and not be deleted (`tools.source_unavailable` otherwise);
- disable/delete: reject an enabled configured login Tool with `tools.login_tool_conflict`;
- disable/delete: stop running Skills bound to the Tool;
- enable/disable are idempotent state assignments;
- delete is a soft delete. Repeated IDs inside one request are deduplicated, while a later request for an already-deleted Tool follows the approved design and fails as `tools.not_found`.

## Transaction boundary

`serialized_write` obtains `BEGIN IMMEDIATE` for SQLite, expires pre-lock ORM state, commits once, and rolls back on outer failures. Each Tool action executes and flushes inside `Session.begin_nested()` so a known rule failure or unexpected per-item exception rolls back only that item. Unexpected item exceptions map to `tools.batch_item_failed` without exception text. Failures establishing or committing the outer transaction are not converted into partial item results.

## Verification

- Focused bulk tests, existing Tool API tests, full backend tests.
- Ruff, `git diff --check`, secret/internal-error and old-route scans.
- All Python commands use the available project Conda environment.
