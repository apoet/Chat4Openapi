# M11 Brief — Tool Selection and Bulk Actions

## Scope

- Add an accessible checkbox for every rendered Tool and a responsive bulk-action bar.
- Keep selection by Tool ID across search, enabled-state filtering, API-source routing, and source/tag collapse. `Select visible` adds only the currently filtered Tool set; `Clear selection` clears every selected ID.
- Enforce the backend contract's maximum of 200 unique Tool IDs in the UI. Never silently truncate or split a user action.
- Consume `POST /api/admin/tools/batch` for enable, disable, and soft delete with the administrator CSRF token.
- Reconcile against the immutable request snapshot: successful IDs leave selection, failed IDs remain selected for retry, deleted successes disappear, and enable/disable successes update immediately from authoritative result status.
- Present a structured localized success/failure summary and localized per-item errors without rendering internal exception text.
- Require delete confirmation that names the selected Tool count and affected API-source count. Cancel sends no request.
- Disable related selection/action controls while a batch is pending, prevent duplicate submission, and prevent late responses from mutating IDs selected after the request started.
- Preserve existing search, API-source navigation, collapse/expand, description editing, parameter editing, and single-item actions. Do not implement M12.

## TDD slices

1. Selection persists across filter/search/collapse; `Select visible`, clear, and the 200-ID limit are exact.
2. Partial disable success sends CSRF, updates succeeded state, keeps only failures selected, and localizes errors.
3. Delete confirmation reports Tool/source counts; cancel is side-effect free and successful deletes disappear.
4. Pending controls prevent duplicates and late results reconcile only the captured request snapshot.
5. English/Simplified Chinese parity, keyboard names, responsive styling, and existing Tools regressions.

## Verification

- Focused and full frontend tests.
- Frontend typecheck and production build through `D:\\nvm\\nodejs\\npm.cmd`.
- Locale parity, M12-scope, internal-error, endpoint, and `git diff --check` scans.
