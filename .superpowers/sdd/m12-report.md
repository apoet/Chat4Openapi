# M12 Report — Scalable Skill Tool Catalog

## Status

Complete.

## Delivered

- Added a single computed `useToolCatalog` index shared by the binding panel and prompt picker. It indexes every non-deleted imported Tool by name, description, path, all Swagger tags, and API-source name.
- Added complete source/tag/effective-enabled filtering followed by source → original Swagger tag grouping. Search runs over the full catalog before the UI applies its 100-row render bound.
- Added a focused, denser `ToolCatalogPanel` with name, method, path, source, tags, enabled marker, source/tag disclosure controls, filters, and explicit disabled rows.
- Switched Skill catalog loading to the administrator Tool list so non-deleted disabled Tools remain visible. New binding/reference actions require an effectively enabled Tool, while existing disabled bindings are pinned through the render bound and remain removable.
- Added a categorized, enabled-only `@` picker that calls the same catalog query/group API and supports ArrowUp, ArrowDown, Enter, Escape, click selection, active-descendant semantics, and canonical `{{tool:name}}` insertion.
- Added a taller 680px panel with CSS vertical resizing, a keyboard-operable separator, 420–1000px bounds, local height persistence, and guarded storage access.
- Added responsive catalog controls, English/Simplified Chinese parity, and explicit Skill start regression coverage while preserving existing CRUD behavior.

## TDD Evidence

- Initial RED: the new catalog suite reported 5/5 failures because the existing inline list had no five-field search/row bound, disabled binding row, catalog filters, categorized listbox, resize persistence, or storage-failure-safe panel. The existing Skill suite remained 21/21 green.
- GREEN: catalog/Skill/locale reached 29/29 after the shared index, panel, picker, locale, and responsive implementation.
- Review RED: a disabled binding at catalog position 150 was hidden by the ordinary 100-row render bound (1 failed, 5 passed).
- Review GREEN: pinned matching bindings are now included before ordinary limited results; catalog reached 6/6, including tag/source/state filters, both hierarchy levels, dense metadata, and disabled unbinding.
- Added a characterization test for the existing Skill start lifecycle endpoint; final focused coverage is 30/30.

## Fresh Verification

- `D:\\nvm\\nodejs\\npm.cmd test -- --run src/__tests__/tool-catalog.spec.ts src/__tests__/skills-chat.spec.ts src/__tests__/locale-coverage.spec.ts`: PASS — 3 files, 30 tests.
- `D:\\nvm\\nodejs\\npm.cmd test -- --run`: PASS — 10 files, 93 tests.
- `D:\\nvm\\nodejs\\npm.cmd run typecheck`: PASS.
- `D:\\nvm\\nodejs\\npm.cmd run build`: PASS — Vue typecheck plus Vite production build, 172 modules transformed.

## Scope and Safety Scans

- `SkillsView` constructs one `useToolCatalog` instance; the panel and prompt picker both call its `query` function and no duplicate inline filter/group implementation remains.
- The only prompt reference constructor emits the existing parser-compatible `{{tool:name}}` form.
- Storage reads and writes are independently guarded; storage denial retains in-memory editing and resizing.
- Skill Tool loading has one `/api/admin/tools` consumer and no remaining `/api/admin/skills/eligible-tools` frontend consumer.
- Locale-key parity passes in the focused and full suites; English remains the default locale.
- Changed only M12 Skill catalog UI/store/tests/styles/locales and the required M12 brief/report; no M13 work was added.
- `git diff --check`: PASS (Git emitted line-ending notices only during adjacent diff inspection).
