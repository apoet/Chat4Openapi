# M12 Report — Scalable Skill Tool Catalog

## Status

Complete.

## Delivered

- Added a single computed `useToolCatalog` index shared by the binding panel and prompt picker. It indexes every non-deleted imported Tool by name, description, path, all Swagger tags, and API-source name.
- Added complete source/tag/effective-enabled filtering followed by source → original Swagger tag grouping. Search runs over the full catalog before the UI applies its 100-row render bound.
- Added a focused, denser `ToolCatalogPanel` with name, method, path, source, tags, enabled marker, source/tag disclosure controls, filters, and explicit disabled rows.
- Merged the full administrator Tool list with the authoritative `/api/admin/skills/eligible-tools` result. All non-deleted Tools remain visible, while binding, references, the `@` picker, and save payloads require authoritative Skill eligibility. Eligibility failures remain visible but fail closed.
- Existing anomalous bindings, including login Tools, show `Unavailable`, remain removable, and are omitted from create/update payloads. Source-disabled and Tool-disabled states remain independently visible.
- Added a categorized, eligibility-only `@` picker that calls the same catalog query/group API and supports ArrowUp, ArrowDown, Enter, Escape, click selection, active-descendant semantics, canonical `{{tool:name}}` insertion, and `scrollIntoView({ block: 'nearest' })` after keyboard movement.
- Added a taller 680px panel with CSS vertical resizing, a keyboard-operable separator, 420–1000px bounds, local height persistence, and guarded storage access.
- Added responsive catalog controls, English/Simplified Chinese parity, and explicit Skill start regression coverage while preserving existing CRUD behavior.

## TDD Evidence

- Initial RED: the new catalog suite reported 5/5 failures because the existing inline list had no five-field search/row bound, disabled binding row, catalog filters, categorized listbox, resize persistence, or storage-failure-safe panel. The existing Skill suite remained 21/21 green.
- GREEN: catalog/Skill/locale reached 29/29 after the shared index, panel, picker, locale, and responsive implementation.
- Review RED: a disabled binding at catalog position 150 was hidden by the ordinary 100-row render bound (1 failed, 5 passed).
- Review GREEN: pinned matching bindings are now included before ordinary limited results; catalog reached 6/6, including tag/source/state filters, both hierarchy levels, dense metadata, and disabled unbinding.
- Added a characterization test for the existing Skill start lifecycle endpoint; final focused coverage is 30/30.
- Review 1 RED: the catalog suite reported 3 failures and 6 passes: an enabled login Tool lacked the `Unavailable` state and was not authoritatively excluded, eligibility-fetch failure incorrectly allowed binding, and a 25-option picker truncated/failed to scroll its active option.
- Review 1 GREEN: authoritative eligibility now gates every new bind/reference/mention/save path, save waits for an in-flight eligibility request, failure remains fail-closed, anomalous bindings remain removable, and keyboard navigation scrolls the active option with `nearest`. The catalog suite reached 9/9 and final focused coverage reached 33/33.

## Fresh Verification

- `D:\\nvm\\nodejs\\npm.cmd test -- --run src/__tests__/tool-catalog.spec.ts src/__tests__/skills-chat.spec.ts src/__tests__/locale-coverage.spec.ts`: PASS — 3 files, 33 tests.
- `D:\\nvm\\nodejs\\npm.cmd test -- --run`: PASS — 10 files, 96 tests.
- `D:\\nvm\\nodejs\\npm.cmd run typecheck`: PASS.
- `D:\\nvm\\nodejs\\npm.cmd run build`: PASS — Vue typecheck plus Vite production build, 172 modules transformed.

## Scope and Safety Scans

- `SkillsView` constructs one `useToolCatalog` instance; the panel and prompt picker both call its `query` function and no duplicate inline filter/group implementation remains.
- The only prompt reference constructor emits the existing parser-compatible `{{tool:name}}` form.
- Storage reads and writes are independently guarded; storage denial retains in-memory editing and resizing.
- Skill Tool loading has one full-catalog `/api/admin/tools` consumer and reuses `/api/admin/skills/eligible-tools` as the authoritative allow-list. A rejected eligibility request leaves an empty eligible-ID set.
- Static scan confirms `skillEligible` gates checkbox additions, reference buttons, picker results, canonical insertion, and save-payload filtering; existing checked unavailable bindings bypass only checkbox disabling so they can be removed.
- Static scan confirms keyboard movement awaits Vue's next tick, resolves the active option ref, and calls `scrollIntoView({ block: 'nearest' })` while retaining `aria-activedescendant`.
- Locale-key parity passes in the focused and full suites; English remains the default locale.
- Changed only M12 Skill catalog UI/store/tests/styles/locales and the required M12 brief/report; no M13 work was added.
- `git diff --check`: PASS (Git emitted line-ending notices only during adjacent diff inspection).
