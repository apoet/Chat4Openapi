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

## Fresh Verification

- `D:\nvm\nodejs\npm.cmd test -- --run`: PASS — 9 files, 83 tests.
- `D:\nvm\nodejs\npm.cmd run typecheck`: PASS.
- `D:\nvm\nodejs\npm.cmd run build`: PASS — Vue typecheck plus Vite production build, 169 modules transformed.
- `git diff --check`: PASS (only Git line-ending notices were emitted by adjacent diff commands).

## Scope and Safety Scans

- Changed only the M11 Tools UI/contracts/store/tests/styles/locales plus this brief/report; no M12 Skill editor work.
- The production frontend contains exactly one `/api/admin/tools/batch` consumer.
- Structured failure rendering maps allow-listed codes to localized copy and never interpolates server `params` or exception details.
- Locale coverage passes as part of the full frontend suite.
