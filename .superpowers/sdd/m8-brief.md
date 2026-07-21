# M8 Brief — Multi-Agent Administration UI

## Scope

- Replace the singleton Agent settings screen with multi-Agent administration.
- Provide Agent list, create/edit, soft delete, enable/disable, and set-default actions.
- Bind searchable Skills in an explicit order. Bound stopped Skills remain visible and removable.
- Manage multiple API keys with label, prefix, status, expiry, and last-used metadata.
- Display a newly created key secret exactly once in component memory; clear it on close, Agent change, and unmount. Never store it in Pinia or `localStorage`.
- Cover English and Simplified Chinese, responsive layout, and accessible names.
- Do not implement M9 Chat behavior.

## Backend contract constraints

- Agent CRUD and lifecycle live under `/api/admin/agents`.
- A newly created enabled Agent is rejected before Skills can be bound. The UI therefore creates Agents disabled, writes ordered Skill bindings, and exposes enable as a separate lifecycle action.
- Default Agents cannot be disabled or deleted.
- Enabling or setting default requires an enabled Provider and at least one bound running Skill.
- Agent keys can be listed, created, patched, revoked, and deleted. There is no key re-enable endpoint; the UI must not invent one.
- Key plaintext exists only in the create response.

## Design synthesis

Three candidate directions were considered locally because collaboration capacity was unavailable:

1. A dense table with modal editors: efficient scanning, but weak on small screens and poor for ordered binding work.
2. Independent cards with accordion forms: responsive, but makes switching among many Agents cumbersome.
3. Master-detail workspace: compact selectable Agent rail plus a focused editor and key panel.

Use the master-detail workspace. It keeps lifecycle state visible, gives ordered Skills enough room, and collapses naturally to one column. Key creation remains in a separate panel so the one-time secret has a clear lifecycle boundary.

## TDD acceptance checks

- Loads Agents, Providers, and Skills; selects an Agent and loads only its key metadata.
- Creates disabled first, writes ordered Skills, then refreshes.
- Saves all editable Agent fields and ordered Skill IDs with CSRF.
- Supports searchable add, move up/down, and removal of stopped bound Skills.
- Uses real enable/disable/default/delete endpoints and localizes protection errors.
- Creates keys, displays/copies/closes the one-time secret, never persists it, and supports revoke/delete.
- English and Chinese locale trees remain identical and include the M8 narrative/error keys.
