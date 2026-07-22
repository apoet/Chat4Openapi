# M13 Report — Final Delivery

## Status

Complete. The final documentation, migration acceptance probes, isolated browser acceptance, cleanup, and post-E2E serial gates passed. No product implementation defect was found, so M13 contains documentation and acceptance-test changes only.

## Delivered files

- `README.md`: canonical Conda/nvm setup; initialize/admin; multi-Agent/default/ordered Skill operation; one-time Agent keys; OpenAI/Anthropic compatibility and canonical Tool Session header; public browser subjects/history; bulk Tool behavior; scalable Skill catalog and `@` references; Tool Session/OAuth modes; backup/migration/no-overwrite behavior; security boundaries and limits.
- `.env.example`: browser-session lifetime and durable encryption-key guidance.
- `docs/tool-session-authentication.md`: Device Flow, PKCE, allow-listed Header/Cookie injection, Swagger login constraints, lifecycle endpoints, binding rules, refresh behavior, errors, and security guidance.
- `backend/tests/test_final_migration_acceptance.py`: four real-SQLite migration acceptance probes.
- `.superpowers/sdd/m13-brief.md` and this report: force-tracked delivery record.

## Migration acceptance

Command:

```powershell
conda run -n chatapi python -m pytest backend/tests/test_final_migration_acceptance.py -q
```

Result: `4 passed in 12.87s`.

The probes establish:

1. A fresh database upgrades to the sole head `0012_conversation_owners` and exposes the expected final tables.
2. Representative `0007` administrators/session hashes, encrypted provider secrets, source snapshot, Tool schemas/overrides, Skills/bindings, customized Agent settings, conversation/messages, and legacy Tool Session data upgrade to head. Applicable rows and secrets survive; ownerless history is retained for audit but revoked and soft-deleted, and ownerless legacy Tool Sessions are removed as required by `0009`.
3. `head -> 0007 -> head` succeeds and preserves the default Agent fields/history audit contract; ownerless history is revoked/soft-deleted after re-upgrade.
4. Legacy default database/key filenames migrate atomically only when the destination is absent; existing destinations are never overwritten and custom paths are untouched.

## Isolated browser acceptance

Playwright CLI ran in headed Chromium through the required wrapper and an nvm-provided `npx` (`10.8.2`). Every element reference came from a current snapshot. The application and deterministic upstream/OAuth issuer used distinct ports `18113` and `18213`, a temporary SQLite database, temporary encryption key, and separate logs.

Observed evidence:

- `01-admin-after-initialize-login.png`: first-run administrator creation, login, and control-plane render.
- `02-agents-skill-bindings-and-one-time-key.png`: Alpha/Beta Agents, separate running Skill bindings, enabled/default state, and once-only key dialog. Alpha key requesting Beta's `agent-3` returned `403 auth.agent_key_forbidden`.
- `03-chat-alpha-markdown-history-lock.png`: default Alpha selection, locked selector after first turn, local history, safe Markdown heading/table, and `Loaded: Alpha Credential Skill`.
- `04-chat-beta-skill-isolation.png`: new-chat Beta selection, Beta lock/history, Beta-only loaded Skill, and Beta Tool output.
- Compatible Tool Session creation returned `ready`; an Alpha request carrying `X-Chat4Openapi-Tool-Session` loaded Skill `1`, executed `alpha_protected`, and observed `{"authenticated":true,"credential":"injected"}` from an upstream that rejected missing credentials.
- `05-thousand-tool-search-at-reference.png`: `Showing 100 of 1000 Tools`, complete search for `catalog_tool_0998`, automatic binding, and exact `{{tool:catalog_tool_0998}}` insertion.
- `06-bulk-partial-result.png`: cross-state selection and ordered partial reconciliation: `Disabled 1 of 2 Tools. 1 failed.`; the configured login Tool remained selected with its policy error while the ordinary Tool became disabled.
- `07-pkce-ready.png`: browser authorization redirect/callback reached deterministic `ready`. Device Flow returned `pending` with `M13-CODE`/interval `1`, then polled `pending -> ready`.
- `08-chat-reload-restored-snapshots.png`: after creating Alpha and Beta chats, a real page reload restored both Agent name snapshots, active locked Beta selection, Markdown table, and loaded-Skill display.

The screenshots were retained only long enough to verify and record these observations, then the explicitly scoped `output/playwright/m13` artifacts were removed during final cleanup.

## Defect handling

No production defect required a RED/GREEN fix. Two harness corrections were recorded rather than misclassified as product failures:

- Alembic's `env.py` correctly consumes `sqlalchemy.url` from its Config, so the isolated migration used a programmatic Config override instead of relying on the application environment variable.
- The deterministic mock was corrected to accept the runtime's canonical Skill-catalog message shape and to distinguish the `load_skills` observation from a business Tool observation.

## Cleanup

- Closed every Playwright CLI browser session.
- Stopped only the verified listeners on `18113` and `18213`; `netstat` confirmed both ports free.
- Removed the isolated database, key, logs, mock issuer/upstream, seed/migration helpers, Playwright state, bytecode, and screenshot directory.
- No temporary secret or one-time key is part of the commit.

## Final serial gates

Fresh after E2E and cleanup:

```text
conda run -n chatapi python -m pytest backend/tests -q
  313 passed in 64.18s

conda run -n chatapi ruff check backend/src backend/migrations backend/tests
  All checks passed!

D:\nvm\nodejs\npm.cmd test -- --run --testTimeout=15000
  10 files / 96 tests passed

D:\nvm\nodejs\npm.cmd run typecheck
  passed

D:\nvm\nodejs\npm.cmd run build
  172 modules transformed; production build passed

git diff --check
  passed

legacy product-name/default-path scan
  no matches in runtime, migrations, final docs, or the final migration acceptance test
```

The final commit SHA is reported in the handoff because a commit cannot embed its own stable hash.
