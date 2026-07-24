# Auto-Agentify One-Click Live Progress Design

## Goal

Turn the existing Auto-Agentify panel into a one-click action beside the existing API Source import action. The action reuses the current import form, asks only for an enabled LLM provider in a modal, then runs generation as a recoverable background job with a detailed live event stream.

The event stream must show useful business-capability analysis conclusions, core workflows, value, candidate Skills, deduplication, selection, and Agent synthesis. It must not expose model chain-of-thought, provider secrets, full OpenAPI content, or unbounded model output.

## User Experience

### Entry Point

Keep the existing **Import source** action unchanged. Add **One-click generate** immediately after it in the same action row.

Both actions share the current form state:

- Source name;
- optional Base URL;
- URL or file input;
- private-network permission.

The actions use identical input-validity rules. One-click generation is disabled until the current import form is valid.

### Confirmation Modal

Selecting **One-click generate** opens a modal containing:

- a summary of the Source name and URL/file being submitted;
- an enabled-provider selector;
- Cancel and Confirm actions.

The modal does not duplicate the import fields. Confirming creates a background job and changes the modal to its execution view.

### Execution View

The execution view contains:

- overall progress bar and percentage;
- current phase;
- live metrics such as discovered operations and planned Skill/Agent counts;
- a chronological detailed event stream;
- business-capability cards or events;
- terminal success or failure content.

The user may close the modal while execution continues. The page's one-click action displays a running indicator. Reopening the modal restores the persisted event history, current metrics, and live subscription.

On success, the modal displays the generated Source, enabled Tool count, Skills, Agents, business values, and use cases. The page refreshes Source-related data and clears the import form. On failure, the modal keeps the original page input and offers a safe retry.

## Background Job Model

Add `auto_agentify_jobs` with:

- opaque public job ID;
- creator administrator ID;
- provider ID;
- input mode and non-sensitive input summary;
- `queued`, `running`, `completed`, or `failed` status;
- phase and integer progress from 0 through 100;
- bounded metrics JSON;
- final result JSON or structured error code/parameters;
- created, started, updated, and completed timestamps.

Add `auto_agentify_job_events` with:

- job foreign key;
- monotonically increasing sequence unique within the job;
- event kind;
- phase and progress;
- localization message key;
- bounded, safe parameters JSON;
- optional bounded business-capability payload;
- creation timestamp.

Each ordinary administrator can read only their own jobs. A system administrator follows the same ownership rule through these endpoints. One active job per administrator is allowed. A repeated start request while a job is queued or running returns the active job instead of creating a second generation.

Retain at most 500 events per job. Per-operation chatter is aggregated into capability groups and counts.

## API

Replace the synchronous UI workflow with job endpoints:

- `POST /api/admin/auto-agentify/jobs/url`
- `POST /api/admin/auto-agentify/jobs/file`
- `GET /api/admin/auto-agentify/jobs/latest`
- `GET /api/admin/auto-agentify/jobs/{public_id}`
- `GET /api/admin/auto-agentify/jobs/{public_id}/events`

The POST endpoints validate the form, enforce CSRF, create the job, schedule independent execution, and immediately return a job snapshot.

The latest endpoint returns the creator's most recent queued/running job or terminal job result so the modal can recover after closing and reopening.

The events endpoint returns `text/event-stream`. Each SSE message uses the persisted sequence as its event ID. The endpoint accepts the standard `Last-Event-ID` header and an `after` query fallback, sends only later events, emits heartbeat comments while idle, and closes after the terminal event.

The current synchronous endpoints may remain temporarily for compatibility but the administration UI no longer calls them.

## Runner Lifecycle

The background runner:

1. receives an immutable input captured by the POST endpoint;
2. opens its own database session;
3. moves the job from queued to running;
4. executes Auto-Agentify with a progress reporter;
5. stores each safe progress event and updates the job snapshot;
6. stores the terminal result or structured error;
7. closes all resources independently of the request.

Uploaded bytes exist only in the runner's in-memory input and are never stored in job events or ordinary logs. URL jobs store the URL as non-secret metadata. Generated Source persistence continues to store the OpenAPI snapshot under the existing Source behavior.

Application startup marks leftover queued/running jobs as failed with `auto_agentify.interrupted`. It does not replay them because replay could repeat model calls or create duplicate configuration. The UI offers a retry using retained page input.

## Progress and Events

Use explicit phases and monotonic progress:

1. `queued` — 0%
2. `loading_document` — 2–8%
3. `parsing_openapi` — 8–15%
4. `cataloging_operations` — 15–22%
5. `analyzing_capabilities` — 22–62%
6. `synthesizing_plan` — 62–72%
7. `validating_plan` — 72–80%
8. `persisting_configuration` — 80–98%
9. `completed` — 100%

The progress reporter accepts structured events. It does not accept arbitrary log strings from OpenAPI descriptions or raw model output.

Example event kinds:

- `document_loaded`;
- `openapi_validated`;
- `operations_discovered`;
- `capability_batch_started`;
- `capability_discovered`;
- `capability_batch_completed`;
- `capabilities_merged`;
- `capability_discarded`;
- `skill_selected`;
- `agent_synthesized`;
- `plan_correction_started`;
- `plan_validated`;
- `persistence_started`;
- `configuration_created`;
- `completed`;
- `failed`.

## Business-Capability Visibility

Batch analysis returns strict capability summaries containing:

- capability name;
- bounded business description;
- bounded business value;
- core workflow steps;
- exact operation keys;
- candidate Skill names;
- high-impact/write indicator.

Persist and display safe conclusions such as:

- the interface group currently being analyzed and its operation count;
- a discovered business capability;
- core workflow steps;
- business value;
- candidate Skills;
- a cross-module capability;
- duplicate capabilities merged;
- low-value or redundant candidates removed;
- final selected Skill count;
- synthesized core Agent and its Skill/Tool coverage.

This content is model output validated by Pydantic, reference-checked against the operation catalog, length-limited, and event-count-limited. OpenAPI descriptions remain untrusted data. The UI labels this content as generated analysis, not verified business fact.

No event may contain:

- chain-of-thought or hidden reasoning;
- provider keys or request authorization;
- full OpenAPI documents;
- complete model prompts or responses;
- arbitrary exception details;
- direct personal credentials.

## Atomicity and Event Semantics

Business analysis events are committed incrementally before configuration persistence so SSE readers can see them immediately.

Source, Tools, Skills, and Agents remain one atomic serialized transaction. During that transaction, the public event is only `persistence_started`. Actual created-object events are emitted after the transaction commits. If it rolls back, the job emits a failure and never claims that objects were created.

Progress never decreases. Replayed SSE events retain their original IDs. The frontend deduplicates by event ID and treats the job snapshot as authoritative for status, progress, metrics, and final result.

## Error Handling

Persist structured terminal failures for:

- invalid or unsupported OpenAPI;
- unsafe URL, download failure, redirect failure, timeout, or oversized input;
- unavailable provider;
- provider timeout or upstream failure;
- invalid capability summary;
- invalid generation plan after one correction;
- persistence conflict or rollback;
- process interruption.

Failure events contain localization keys and bounded safe parameters. The original import form remains unchanged so a retry can resubmit it. Uploaded file contents are not recoverable after a full page reload or server restart; the UI clearly asks the user to reselect the file when necessary.

SSE reconnects automatically. The server uses heartbeat comments while no events are available. Once a terminal event is delivered, the browser closes the stream.

## Frontend Components

Refactor `AutoAgentifyPanel.vue` into a modal-focused component with three states:

- confirmation;
- running/recovering;
- terminal result.

`ApiSourcesView.vue` owns the import form and passes an immutable form snapshot into the modal. It also owns form clearing and Source refresh after success.

A focused composable manages:

- job creation;
- snapshot loading;
- SSE connection and reconnection;
- event deduplication;
- terminal cleanup.

No provider fetch occurs until the modal opens, preserving the existing Source page request behavior.

## Testing

### Backend

Cover:

- URL and file job creation;
- immediate job response and independent runner session;
- creator ownership;
- one active job per creator;
- persisted sequence ordering;
- `Last-Event-ID` and `after` replay;
- heartbeat and terminal stream closure;
- document, parsing, catalog, batch, capability, synthesis, validation, persistence, completion, and failure events;
- strict capability structure and operation-key validation;
- capability merging and discarded-candidate events;
- 500-event limit;
- monotonic progress;
- no secret, full document, raw model response, or chain-of-thought leakage;
- close/reopen recovery through latest job and replay;
- startup interruption handling;
- atomic Source/Tool/Skill/Agent rollback;
- existing 20-Skill and 10-Agent limits.

### Frontend

Cover:

- one-click action immediately after Import Source;
- shared form validation;
- modal Source summary and provider-only selection;
- confirmation before task creation;
- URL and multipart file job requests;
- progress bar, metrics, detailed events, business-capability content, and generated-analysis label;
- modal close and reopen recovery;
- SSE reconnection and event deduplication;
- success refresh/form clear;
- failure retry/form retention;
- English and Simplified Chinese locale parity.

Run the full backend suite, frontend suite, TypeScript check, production build, and Ruff before completion.

## Acceptance Criteria

With a valid current import form, the administrator clicks **One-click generate**, selects a provider, and confirms. The modal begins showing detailed persisted progress immediately, including bounded business-capability conclusions and synthesis events. Closing the modal does not stop generation; reopening restores history and live progress. Success creates the same bounded, immediately usable configuration as before. Failure leaves no partial generated configuration and provides a safe retry path.
