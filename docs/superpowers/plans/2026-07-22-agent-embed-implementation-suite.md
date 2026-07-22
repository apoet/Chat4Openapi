# Agent Embed Implementation Suite

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved Base URL, Agent-bound JavaScript Widget, anonymous AG-UI Chat, optional host WebMCP bridge, protected Tool authorization, administration, README demo, and Wiki documentation.

**Architecture:** Execute three independently reviewable plans in dependency order. Foundation establishes persistence and public trust boundaries; runtime adds AG-UI and WebMCP; authentication/administration completes protected Tool flows and product delivery.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Vue 3, TypeScript, AG-UI 0.0.57, WebMCP draft APIs, Vitest, pytest, Playwright.

## Global Constraints

- Follow the approved design at `docs/superpowers/specs/2026-07-22-agent-embed-agui-webmcp-design.md`.
- Execute plans and tasks in the order listed below; later plans consume interfaces from earlier plans.
- Use Conda environment `chat4openapi` for Python and nvm-managed Node.js 20.19.4 for frontend work.
- Review and commit after every task; never combine unrelated dirty workspace changes.
- Do not publish the Wiki until implementation and release gates pass.

---

## Execution Order

- [ ] **Plan 1: Foundation** — `docs/superpowers/plans/2026-07-22-agent-embed-foundation-implementation.md`
- [ ] **Plan 2: AG-UI, WebMCP, and Widget** — `docs/superpowers/plans/2026-07-22-agui-webmcp-widget-implementation.md`
- [ ] **Plan 3: Authentication, administration, tests, README, and Wiki** — `docs/superpowers/plans/2026-07-22-embed-auth-admin-docs-implementation.md`

## Cross-Plan Acceptance

- [ ] Base URL is administrator-managed and drives all public and callback URLs.
- [ ] A generated one-line script opens a fixed-Agent iframe Widget.
- [ ] Anonymous Chat works without weakening protected backend Tool authorization.
- [ ] Backend OpenAPI Tools and frontend WebMCP Tools never fall back to one another.
- [ ] Unsupported or absent WebMCP is silent.
- [ ] OAuth and Swagger configuration remains on API Sources; Embed authorization returns only one-time grants.
- [ ] Configured origins receive exact CSP and server validation; empty origins implement the approved any-secure-parent behavior.
- [ ] README remains concise and shows `docs/images/demo.png`; detailed documentation is live in the GitHub Wiki.
