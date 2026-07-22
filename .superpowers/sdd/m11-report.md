# M11 Report — Tool Selection and Bulk Actions

## Status

Complete.

## Delivered

- Added a persistent Tool selection model that survives search, status/source filtering, and source/tag collapse changes.
- Added true-visible selection, clear selection, accessible per-Tool checkboxes, and a hard 200-Tool client limit that rejects over-limit selection without truncating or splitting requests.
- Added bulk enable, disable, and soft-delete requests through `POST /api/admin/tools/batch`, including the administrator CSRF token.
- Reconciled ordered partial results immediately: successful enable/disable statuses update in place, successful deletes disappear, successes leave selection, and failures remain selected.
- Added immutable in-flight request snapshots, duplicate-submit prevention, per-request checkbox locking, and preservation of unrelated selections made while a request is pending.
- Added a keyboard-operable delete confirmation with Tool and distinct API-source counts; cancel/Escape sends no request.
- Added localized summaries, safe per-item error messages, generic request errors, English/Chinese locale parity, responsive styles, and live-region semantics.

## TDD Evidence

- RED: selection test could not find `Select visible`; GREEN after the persistent selection UI/model was introduced.
- RED: 201 visible Tools were selected without an error; GREEN after enforcing the exact 200-Tool client limit.
- RED: partial disable test could not find a bulk action; GREEN after adding contracts, store request/reconciliation, and the bulk action bar.
- RED: delete test sent the request immediately and had no dialog; GREEN after adding counted confirmation, cancel/Escape, and focus behavior.
- RED: collapsed source/tag Tools were included by visible selection; GREEN after tracking disclosure state in the true-visible set.
- Regression coverage also verifies CSRF/body shape, safe partial failures, endpoint failure/retry, late responses, unrelated selection preservation, successful deletion, and status updates.

## Review Follow-up

- RED: a Tool removed by a successful single-item delete remained in bulk selection counts; GREEN after deriving counts, limits, confirmation, and snapshots from existing Tools and pruning stale IDs whenever the store list changes.
- RED: single-item edit/enable/delete controls for a pending batch ID remained actionable; GREEN after adding per-ID UI locks plus function-level guards while leaving unrelated Tools selectable and operable.
- RED: delete confirmation did not inert the background, trap Tab, or restore trigger focus; GREEN after moving to native `dialog` `showModal`/`close`, explicit background inertness, focus cycling, Escape/cancel handling, and trigger focus restoration.
- Confirmation now remains modal and non-dismissible while its delete request is pending; both dialog actions and background Tool mutations are blocked until reconciliation completes.

## Fresh Verification

- `D:\nvm\nodejs\npm.cmd test -- --run src/__tests__/tools-view.spec.ts`: PASS — 1 file, 36 tests.
- `D:\nvm\nodejs\npm.cmd test -- --run`: PASS — 9 files, 86 tests.
- `D:\nvm\nodejs\npm.cmd run typecheck`: PASS.
- `D:\nvm\nodejs\npm.cmd run build`: PASS — Vue typecheck plus Vite production build, 169 modules transformed.
- `git diff --check`: PASS (only Git line-ending notices were emitted by adjacent diff commands).

## Scope and Safety Scans

- Changed only the M11 Tools UI/contracts/store/tests/styles/locales plus this brief/report; no M12 Skill editor work.
- The production frontend contains exactly one `/api/admin/tools/batch` consumer.
- Structured failure rendering maps allow-listed codes to localized copy and never interpolates server `params` or exception details.
- Locale coverage passes as part of the full frontend suite.
