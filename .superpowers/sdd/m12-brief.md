# M12 Brief — Scalable Skill Tool Catalog

## Scope

- Replace the Skill editor's inline Tool list and mention search with one memoized catalog index shared by binding and prompt references.
- Index every non-deleted imported Tool across name, description, HTTP method/path, Swagger tags, and API-source name; keep 1,000+ Tool search complete while limiting rendered rows.
- Add source, Swagger-tag, and enabled-state filters plus collapsible source/tag hierarchy.
- Show dense metadata and an explicit disabled marker. Existing disabled bindings remain visible and removable; only enabled Tools may be newly bound or inserted as canonical `{{tool:name}}` prompt references.
- Add an accessible `@tool` menu with category context, ArrowUp/ArrowDown/Enter/Escape controls, and click insertion.
- Make the right panel taller and vertically resizable, persist a bounded preferred height, and tolerate unavailable or throwing `localStorage`.
- Preserve existing Skill CRUD/start/stop behavior, English/Chinese locale parity, accessibility, and responsive layout. Do not implement M13.

## TDD slices

1. Pure catalog indexing searches all five fields across 1,000+ Tools and applies source/tag/enabled filters without truncating matches before grouping.
2. Catalog panel renders dense metadata, disabled bindings, filters, collapse state, binding/unbinding rules, and bounded results.
3. Prompt picker consumes the same catalog query/group result and implements category context, keyboard navigation, click/Enter insertion, and Escape.
4. Panel height persistence clamps values and remains usable when storage reads or writes throw.
5. Existing Skill CRUD/start tests, locale coverage, responsive styles, and build/type gates remain green.

## Verification

- Focused catalog/Skill/locale tests and full frontend tests through `D:\\nvm\\nodejs\\npm.cmd`.
- Frontend typecheck and production build.
- Shared-index, canonical-reference, storage-safety, locale-parity, M13-scope, and `git diff --check` scans.
