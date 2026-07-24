# Auto-Agentify One-Click Live Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a one-click generation action directly after API Source import and run Auto-Agentify as a recoverable background job with SSE progress, detailed business-capability conclusions, and atomic final persistence.

**Architecture:** Persist job snapshots and ordered safe events in SQLite, run generation in an independent async task/session, and stream persisted events through an authenticated SSE endpoint with replay. Refactor the frontend generator into a provider-confirmation modal backed by a focused job/SSE composable while retaining the existing synchronous endpoints for compatibility.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, asyncio, SSE/StreamingResponse, pytest; Vue 3, TypeScript, vue-i18n, Vitest.

## Global Constraints

- The **One-click generate** action appears immediately after **Import source** and reuses the current valid URL/file form.
- The modal asks only for an enabled provider before confirmation.
- Closing the modal does not cancel the job; reopening restores persisted history and live progress.
- Business analysis exposes bounded conclusions, workflows, values, candidate Skills, merging, selection, and Agent coverage, never chain-of-thought.
- One creator can have only one queued/running job.
- Events are creator-scoped, monotonically ordered, replayable, and capped at 500 per job.
- Source, Tool, Skill, and Agent creation remains one atomic transaction.
- Uploaded bytes, provider keys, full OpenAPI documents, raw prompts, and raw model responses never enter job events.
- A stale queued/running job becomes `auto_agentify.interrupted` after process restart.
- Existing limits remain at 20 Skills and 10 Agents.
- Preserve the unrelated untracked `.tmp/` directory.

---

## File Structure

- `backend/src/chat4openapi/models/auto_agentify_job.py`: job and ordered event persistence.
- `backend/migrations/versions/0019_auto_agentify_jobs.py`: schema, constraints, ownership indexes, and active-job unique index.
- `backend/src/chat4openapi/schemas/auto_agentify.py`: capability, job snapshot, event, and start-response contracts.
- `backend/src/chat4openapi/auto_agentify/progress.py`: safe progress event value, monotonic/capped repository, and interruption recovery.
- `backend/src/chat4openapi/auto_agentify/planner.py`: strict capability summaries and analysis/synthesis callbacks.
- `backend/src/chat4openapi/auto_agentify/service.py`: stage callbacks around parsing, cataloging, planning, validation, and atomic persistence.
- `backend/src/chat4openapi/auto_agentify/jobs.py`: job creation, independent task runner, task registry, and terminal status.
- `backend/src/chat4openapi/api/admin_auto_agentify.py`: job start/snapshot/latest/SSE endpoints plus compatibility endpoints.
- `backend/tests/test_auto_agentify_jobs.py`: model, ownership, concurrency, runner, recovery, and event tests.
- `backend/tests/test_auto_agentify_sse.py`: replay, event IDs, terminal closure, and heartbeat tests.
- `frontend/src/composables/useAutoAgentifyJob.ts`: job creation, snapshot recovery, EventSource lifecycle, deduplication, and terminal state.
- `frontend/src/components/AutoAgentifyPanel.vue`: modal confirmation, progress, detailed event/capability rendering, and result.
- `frontend/src/views/ApiSourcesView.vue`: adjacent actions, form snapshot, close/reopen, refresh, and form clearing.
- `frontend/src/api/contracts.ts`: job/event/capability contracts.
- `frontend/src/i18n/en-US.ts`, `frontend/src/i18n/zh-CN.ts`: modal, phases, events, generated-analysis labels, and errors.
- `frontend/src/__tests__/auto-agentify.spec.ts`: complete one-click/modal/live/recovery tests.

---

### Task 1: Persisted Job and Event Domain

**Files:**
- Create: `backend/src/chat4openapi/models/auto_agentify_job.py`
- Create: `backend/migrations/versions/0019_auto_agentify_jobs.py`
- Modify: `backend/src/chat4openapi/models/__init__.py`
- Modify: `backend/src/chat4openapi/schemas/auto_agentify.py`
- Create: `backend/tests/test_auto_agentify_jobs.py`

**Interfaces:**
- Produces `AutoAgentifyJob`, `AutoAgentifyJobEvent`, `AutoAgentifyJobResponse`, `AutoAgentifyJobEventResponse`.
- Job statuses: `queued | running | completed | failed`.
- Event sequences are positive integers unique per job.

- [ ] **Step 1: Write failing model and migration tests**

```python
def test_job_enforces_one_active_job_per_creator(db):
    db.add_all([job(admin_id=1, status="queued"), job(admin_id=1, status="running")])
    with pytest.raises(IntegrityError):
        db.commit()

def test_job_event_sequence_is_unique_within_job(db):
    saved = persist_job(db)
    db.add_all([event(saved.id, 1), event(saved.id, 1)])
    with pytest.raises(IntegrityError):
        db.commit()
```

- [ ] **Step 2: Run RED**

Run: `conda run -n chatapi pytest backend/tests/test_auto_agentify_jobs.py -q`

Expected: FAIL because the job models do not exist.

- [ ] **Step 3: Implement models and migration**

Use:

```python
class AutoAgentifyJob(Base):
    __tablename__ = "auto_agentify_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','completed','failed')"),
        CheckConstraint("progress BETWEEN 0 AND 100"),
        Index(
            "uq_auto_agentify_active_creator",
            "creator_admin_id",
            unique=True,
            sqlite_where=text("status IN ('queued','running')"),
        ),
    )
```

Store `metrics`, `result`, `error_params`, event `params`, and event `capability` as JSON. Use a UUID hex public ID and foreign keys to `admin_users` and `llm_providers`.

- [ ] **Step 4: Run GREEN and migration acceptance**

Run:

```powershell
conda run -n chatapi pytest backend/tests/test_auto_agentify_jobs.py backend/tests/test_final_migration_acceptance.py -q
```

Expected: PASS.

---

### Task 2: Safe Monotonic Progress Repository

**Files:**
- Create: `backend/src/chat4openapi/auto_agentify/progress.py`
- Modify: `backend/tests/test_auto_agentify_jobs.py`

**Interfaces:**
- Produces `ProgressEvent`, `JobProgressReporter.emit(event)`, `mark_interrupted_jobs(db)`.
- `emit` commits immediately before final persistence, clamps neither invalid progress nor unsafe payloads, and raises on regressions.

- [ ] **Step 1: Write failing repository tests**

```python
@pytest.mark.asyncio
async def test_reporter_persists_monotonic_bounded_events(db, saved_job):
    reporter = JobProgressReporter(db, saved_job.id)
    await reporter.emit(ProgressEvent("operations_discovered", "cataloging_operations", 20, "autoAgentify.events.operations", {"count": 8}))
    with pytest.raises(ValueError, match="progress cannot decrease"):
        await reporter.emit(ProgressEvent("bad", "parsing_openapi", 10, "x", {}))
    assert db.scalars(select(AutoAgentifyJobEvent)).one().sequence == 1

def test_interruption_recovery_marks_active_jobs_failed(db):
    mark_interrupted_jobs(db)
    assert saved_job.status == "failed"
    assert saved_job.error_code == "auto_agentify.interrupted"
```

- [ ] **Step 2: Run RED**

Run: `conda run -n chatapi pytest backend/tests/test_auto_agentify_jobs.py -q`

Expected: FAIL because `JobProgressReporter` is missing.

- [ ] **Step 3: Implement the reporter**

```python
@dataclass(frozen=True, slots=True)
class ProgressEvent:
    kind: str
    phase: str
    progress: int
    message_key: str
    params: dict[str, JsonValue]
    capability: dict[str, JsonValue] | None = None
```

Validate allowed phases, `0 <= progress <= 100`, localization-key prefix, bounded strings/lists, operation-key references supplied by the caller, and a 500-event maximum. Update job metrics/status snapshot in the same commit as each event.

- [ ] **Step 4: Run GREEN**

Run: `conda run -n chatapi pytest backend/tests/test_auto_agentify_jobs.py -q`

Expected: PASS.

---

### Task 3: Capability Analysis and Service Progress Hooks

**Files:**
- Modify: `backend/src/chat4openapi/schemas/auto_agentify.py`
- Modify: `backend/src/chat4openapi/auto_agentify/planner.py`
- Modify: `backend/src/chat4openapi/auto_agentify/service.py`
- Modify: `backend/tests/test_auto_agentify_planner.py`
- Modify: `backend/tests/test_auto_agentify_api.py`

**Interfaces:**
- Adds `CapabilitySummary` and `CapabilityBatch`.
- Adds optional `reporter: ProgressReporter | None` to planner/service entry points.
- Planner emits batch start, validated capabilities, merge/selection, correction, and Agent synthesis events.

- [ ] **Step 1: Write failing capability and progress tests**

```python
@pytest.mark.asyncio
async def test_large_catalog_emits_safe_capability_conclusions():
    events = CollectingReporter()
    await planner.plan(..., reporter=events)
    capability = next(event for event in events if event.kind == "capability_discovered")
    assert capability.capability["name"] == "Project lifecycle"
    assert capability.capability["workflow"] == ["Create", "Assign", "Track", "Close"]
    assert "hidden reasoning" not in json.dumps(capability.capability)

@pytest.mark.asyncio
async def test_service_emits_parse_catalog_plan_and_post_commit_events():
    result = await service.generate(..., reporter=events)
    assert [event.kind for event in events] == expect_ordered_subsequence([
        "openapi_validated", "operations_discovered", "plan_validated",
        "persistence_started", "configuration_created", "completed",
    ])
```

- [ ] **Step 2: Run RED**

Run:

```powershell
conda run -n chatapi pytest backend/tests/test_auto_agentify_planner.py backend/tests/test_auto_agentify_api.py -q
```

Expected: FAIL because reporter arguments and strict capability contracts are missing.

- [ ] **Step 3: Implement strict capability output**

Use:

```python
class CapabilitySummary(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2_000)
    value: str = Field(min_length=1, max_length=2_000)
    workflow: list[str] = Field(min_length=1, max_length=12)
    operation_keys: list[str] = Field(min_length=1, max_length=200)
    candidate_skills: list[str] = Field(min_length=1, max_length=20)
    high_impact: bool
```

Validate every operation key against the batch catalog. Emit only model fields from this schema. For catalogs at or below 200 operations, run a capability-analysis call before final plan synthesis so the business process is always visible, not only for large documents.

- [ ] **Step 4: Add service stages without violating atomicity**

Refactor `AutoAgentifyService.generate` to accept `db: Session` and emit pre-transaction events. Emit `persistence_started` immediately before `serialized_write`; emit created-object summaries and `completed` only after commit.

- [ ] **Step 5: Run GREEN**

Run:

```powershell
conda run -n chatapi pytest backend/tests/test_auto_agentify_catalog.py backend/tests/test_auto_agentify_planner.py backend/tests/test_auto_agentify_api.py -q
```

Expected: PASS.

---

### Task 4: Independent Runner and SSE API

**Files:**
- Create: `backend/src/chat4openapi/auto_agentify/jobs.py`
- Modify: `backend/src/chat4openapi/api/admin_auto_agentify.py`
- Modify: `backend/src/chat4openapi/main.py`
- Create: `backend/tests/test_auto_agentify_sse.py`
- Modify: `backend/tests/test_auto_agentify_jobs.py`

**Interfaces:**
- Produces `AutoAgentifyJobManager.start_url`, `start_file`, `run`, and task registry.
- Produces job POST/latest/snapshot/SSE endpoints.

- [ ] **Step 1: Write failing API/runner tests**

```python
@pytest.mark.asyncio
async def test_start_returns_before_runner_finishes_and_reuses_active_job(client):
    first = await post_job(client)
    second = await post_job(client)
    assert first.status_code == second.status_code == 202
    assert first.json()["public_id"] == second.json()["public_id"]

@pytest.mark.asyncio
async def test_other_creator_cannot_read_job(other_client, public_id):
    assert (await other_client.get(f"/api/admin/auto-agentify/jobs/{public_id}")).status_code == 404
```

- [ ] **Step 2: Write failing SSE replay test**

```python
@pytest.mark.asyncio
async def test_sse_replays_after_last_event_and_closes_at_terminal(client, completed_job):
    response = await client.get(
        f"/api/admin/auto-agentify/jobs/{completed_job.public_id}/events",
        headers={"Last-Event-ID": "2"},
    )
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 3" in response.text
    assert "id: 2" not in response.text
    assert '"kind":"completed"' in response.text
```

- [ ] **Step 3: Run RED**

Run:

```powershell
conda run -n chatapi pytest backend/tests/test_auto_agentify_jobs.py backend/tests/test_auto_agentify_sse.py -q
```

Expected: FAIL with missing job endpoints.

- [ ] **Step 4: Implement manager and endpoints**

Create tasks with `asyncio.create_task`, retain them in a module-level set until completion, derive an independent sessionmaker from the request session bind, and pass immutable URL/file input into the task. Catch `ApiError` into safe structured terminal errors and unexpected exceptions into `auto_agentify.failed`.

Implement SSE with `StreamingResponse`, fresh short-lived sessions per poll, event IDs, `Last-Event-ID`/`after`, heartbeat comments, creator ownership, and terminal close.

- [ ] **Step 5: Integrate startup recovery**

At application lifespan startup, call `mark_interrupted_jobs` before serving requests. Tests override the session dependency/bind so recovery is also independently testable.

- [ ] **Step 6: Run GREEN**

Run:

```powershell
conda run -n chatapi pytest backend/tests/test_auto_agentify_jobs.py backend/tests/test_auto_agentify_sse.py backend/tests/test_auto_agentify_api.py -q
```

Expected: PASS.

---

### Task 5: One-Click Modal and Live Event UI

**Files:**
- Create: `frontend/src/composables/useAutoAgentifyJob.ts`
- Rewrite: `frontend/src/components/AutoAgentifyPanel.vue`
- Modify: `frontend/src/views/ApiSourcesView.vue`
- Modify: `frontend/src/api/contracts.ts`
- Modify: `frontend/src/__tests__/auto-agentify.spec.ts`

**Interfaces:**
- `AutoAgentifyPanel` consumes one immutable form snapshot and emits `close` and `generated`.
- `useAutoAgentifyJob` exposes `job`, `events`, `connect`, `startUrl`, `startFile`, `recoverLatest`, and `disconnect`.

- [ ] **Step 1: Write failing adjacent-action/modal test**

```typescript
it('places one-click generation immediately after import and asks only for provider', async () => {
  const wrapper = mount(ApiSourcesView, ...)
  const actions = wrapper.find('[data-testid="source-import-actions"]').findAll('button')
  expect(actions.map((button) => button.text())).toEqual(['Import source', 'One-click generate'])
  await actions[1].trigger('click')
  expect(wrapper.get('[role="dialog"]').text()).toContain('Analysis provider')
  expect(wrapper.find('[data-testid="auto-url"]').exists()).toBe(false)
})
```

- [ ] **Step 2: Write failing live/recovery tests**

```typescript
it('renders capability events, deduplicates SSE IDs, and restores after reopen', async () => {
  await confirmJob(wrapper)
  eventSource.emit('3', capabilityEvent)
  eventSource.emit('3', capabilityEvent)
  expect(wrapper.findAll('[data-event-id="3"]')).toHaveLength(1)
  expect(wrapper.text()).toContain('Project lifecycle')
  await wrapper.get('[aria-label="Close generator"]').trigger('click')
  await wrapper.get('[data-testid="auto-submit"]').trigger('click')
  expect(wrapper.text()).toContain('Project lifecycle')
})
```

- [ ] **Step 3: Run RED**

Run: `npm test -- --run src/__tests__/auto-agentify.spec.ts` from `frontend`.

Expected: FAIL because the action position, modal props, job endpoints, and EventSource handling are absent.

- [ ] **Step 4: Implement contracts, composable, modal, and Source view**

Use `EventSource` with same-origin credentials, event ID deduplication, terminal disconnect, and a snapshot fetch after reconnect. The modal renders localization keys with parameters and capability payloads under a “Generated analysis” label. `ApiSourcesView` clears the form and reloads Sources only on completed result.

- [ ] **Step 5: Run GREEN and typecheck**

Run:

```powershell
npm test -- --run src/__tests__/auto-agentify.spec.ts src/__tests__/api-source-oauth.spec.ts src/__tests__/locale-coverage.spec.ts
npm run typecheck
```

Expected: PASS.

---

### Task 6: Localization, Documentation, and Full Verification

**Files:**
- Modify: `frontend/src/i18n/en-US.ts`
- Modify: `frontend/src/i18n/zh-CN.ts`
- Modify: `README.md`
- Modify: `README.zh-CN.md`

- [ ] **Step 1: Add locale-parity strings**

Cover confirmation, progress phases, all event kinds, generated-analysis disclaimer, active-job indicator, reconnecting, interrupted retry, success, and failure.

- [ ] **Step 2: Update documentation**

Explain the adjacent one-click action, provider confirmation, background execution, modal recovery, detailed business-capability events, SSE replay, and restart interruption behavior.

- [ ] **Step 3: Run full verification**

```powershell
conda run -n chatapi pytest backend/tests -q
conda run -n chatapi ruff check backend/src backend/tests
Set-Location frontend
npm test
npm run build
```

Expected: all backend and frontend tests pass, Ruff reports no errors, TypeScript succeeds, and Vite builds production assets.

- [ ] **Step 4: Audit repository state**

```powershell
git diff --check
git status --short --branch
git diff --stat main...HEAD
```

Expected: no whitespace errors; only planned Auto-Agentify files plus the pre-existing untracked `.tmp/`.

---

## Completion Audit

- [ ] Adjacent one-click action shares the import form.
- [ ] Provider-only confirmation modal starts URL/file jobs.
- [ ] Detailed business-capability analysis is visible without chain-of-thought.
- [ ] Closing/reopening restores persisted history and live SSE.
- [ ] SSE replay, deduplication, heartbeat, ownership, and terminal closure are proven.
- [ ] One active job per creator and startup interruption are proven.
- [ ] Final configuration remains bounded, immediately usable, and atomic.
- [ ] Uploaded bytes, keys, documents, prompts, and raw responses do not leak.
- [ ] Backend tests, Ruff, frontend tests, typecheck/build, and repository audit pass.
