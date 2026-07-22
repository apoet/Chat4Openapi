# M13 Brief — Final Documentation, Migration Gates, and Browser Acceptance

## Scope

- Bring operator/client documentation and environment examples to the final multi-Agent, Tool Session, OAuth, bulk Tool, and scalable Skill catalog contracts.
- Add focused migration acceptance probes for fresh databases, representative `0007` data, downgrade/re-upgrade, legacy default filenames, no-overwrite behavior, and a single Alembic head.
- Run backend/frontend gates serially using Conda and nvm-managed Node.
- Exercise the real application through Playwright CLI against isolated services, ports, SQLite/key files, logs, mock upstreams, and mock OAuth issuer.
- Record reproducible commands, observable evidence, and screenshots only under `output/playwright/`.
- Fix implementation defects only through focused RED/GREEN tests; do not hide defects in documentation.

## Required Browser Acceptance

1. Initialize and log in.
2. Create two Agents with different ordered Skill bindings and one-time keys; prove cross-Agent access is 403.
3. Select and lock a Chat Agent, restore Agent-bound Markdown history, and prove each Agent loads only its own Skills.
4. Create an injected-credential Tool Session and execute an authenticated Tool.
5. Drive deterministic Device Flow + PKCE authorization-required to ready states.
6. Select Tools across filters and reconcile a partial-success bulk action.
7. Search a 1,000-Tool Skill catalog and insert a canonical `@tool` reference.

## Safety and Completion

- Snapshot immediately before every Playwright element ref and again after meaningful DOM/navigation changes.
- Keep browser artifacts under `output/playwright/` and remove only explicitly verified temporary processes/files.
- Finish with fresh migration probes, backend pytest/Ruff, frontend tests/typecheck/build, diff/legacy-name scans, an updated report, one commit, and a clean worktree.
