# Auto-Agentify Design

## Goal

After an administrator configures an LLM provider, they can submit a Swagger 2.0 or OpenAPI 3.x document by URL or JSON/YAML file. Agent4API analyzes the API's business capabilities and automatically creates a small set of useful Skills and the core Agents that best demonstrate the API's value.

The generated configuration is immediately usable:

- only Tools referenced by generated Skills are enabled;
- generated Skills are running;
- generated Agents are enabled and bound to the provider selected for the analysis;
- one generation creates at most 20 Skills and 10 Agents.

The limits are maximums, not targets. The analyzer should prefer the smallest coherent set that captures the API's most valuable workflows.

## User Experience

The API Sources page gains a "Generate with AI" entry point. The workflow has three states:

1. **Input configuration**
   - Select one enabled LLM provider.
   - Select URL or file input.
   - Enter an API Source name.
   - Optionally override the API base URL.
   - Optionally allow private-network access, using the existing network-safety behavior.
2. **Analysis and creation**
   - Show the current phase: parsing the API, identifying business capabilities, or creating configuration.
3. **Result**
   - Show counts for the Source, enabled Tools, Skills, and Agents.
   - List each generated Skill and Agent with its business-value explanation and bindings.

If generation fails, the form retains its input so the administrator can retry. Provider credentials are never returned to or populated in the browser.

## Architecture

### API Surface

Add authenticated, CSRF-protected admin endpoints under `/api/admin/auto-agentify`:

- a JSON endpoint for URL-based generation;
- a multipart endpoint for file-based generation.

Both endpoints call the same application service and return the same result contract. The endpoints accept a provider ID, Source name, optional base URL, and the existing private-network flag.

### Auto-Agentify Service

Create a focused service responsible for orchestration:

1. Load and validate the selected enabled provider.
2. Fetch or read the OpenAPI document using the existing 5 MB limit.
3. Parse and normalize the document with the existing OpenAPI loader.
4. Build Tool candidates without committing them.
5. Build a compact operation catalog for LLM analysis.
6. Request a structured generation plan from the selected provider.
7. Validate and, when necessary, correct the plan.
8. Persist the Source, Tools, Skills, and Agents in one serialized database transaction.
9. Return a generation summary.

The service reuses existing OpenAPI parsing, candidate building, network-target validation, provider secret encryption, and model client components. Import and persistence helpers should be extracted where needed so regular API import and Auto-Agentify share behavior rather than duplicate it.

### Operation Catalog

The catalog contains only information needed to understand and bind operations:

- stable operation key;
- operation ID or generated Tool name;
- HTTP method and path;
- tags;
- summary and description;
- compact input-schema information.

The OpenAPI document is untrusted content. Model instructions delimit the catalog as data and explicitly prohibit following instructions embedded in descriptions or examples.

## Analysis Strategy

For documents with no more than 200 operations, the service makes one structured planning request.

For documents with more than 200 operations:

1. deterministically group operations by tags and path prefixes;
2. analyze groups in bounded batches to identify candidate business capabilities;
3. make a final synthesis request over the batch summaries and stable operation keys.

The final output always uses the same strict schema and limits.

### Skill Plan

Each proposed Skill contains:

- name;
- business description;
- system prompt;
- referenced Tool operation keys;
- value explanation.

Skills represent coherent business capabilities, not one Skill per endpoint. A Skill must reference at least one known operation.

### Agent Plan

Each proposed Agent contains:

- name;
- core responsibility;
- system prompt;
- referenced Skill names;
- mode: `react` or `human_in_loop`;
- maximum iterations;
- value explanation;
- representative use cases.

Agents should expose valuable cross-operation workflows rather than mechanically mirror OpenAPI tags. An Agent must reference at least one generated Skill. Agents containing Skills with write, delete, or other high-impact operations default to `human_in_loop`; query and analysis Agents default to `react`.

Every generated Agent binds to the provider selected for analysis and uses that provider's default model.

## Validation and Correction

The LLM result is parsed into strict Pydantic models. Server-side validation enforces:

- no more than 20 Skills;
- no more than 10 Agents;
- at least one Skill and one Agent;
- unique generated Skill and Agent names within the plan;
- every Skill references existing operation keys;
- every Agent references generated Skill names;
- every Skill and Agent has non-empty prompts and value descriptions;
- Agent modes and iteration counts satisfy existing model constraints.

An invalid first response triggers one correction request containing only the rejected structured result and specific validation errors. If the second response is invalid, generation stops with a structured error and nothing is persisted.

The server limits are authoritative and cannot be bypassed by a client or model response.

## Persistence

Persistence runs as one serialized transaction:

1. Create the API Source and all Tools.
2. Resolve Skill operation keys to the newly created Tool IDs.
3. Enable only Tools referenced by at least one generated Skill.
4. Create Skills, bind their Tools in plan order, and mark the Skills as running.
5. Create Agents, bind Skills in plan order, bind the selected provider, and enable the Agents.

Tools not selected by any Skill remain disabled.

Existing objects are never overwritten. If a generated name conflicts with an active existing Skill or Agent, append a normalized Source-name suffix and then a short numeric suffix when needed. Resubmitting the same document creates a new Source and a new generated configuration; the result page makes this explicit.

Any error rolls back the complete transaction so no partial Source, Tool, Skill, or Agent remains.

## Result Contract

The response contains:

- the created API Source;
- total imported and enabled Tool counts;
- generated Skill summaries, including IDs, Tool bindings, and value explanations;
- generated Agent summaries, including IDs, Skill bindings, mode, provider binding, value explanation, and use cases.

Value explanations and use cases are generation-result metadata. They do not need new persistent columns in the first version; the response returns them from the validated plan while the durable business description and behavior live in existing description and system-prompt fields.

## Errors and Observability

Errors use the existing structured API envelope and distinguish:

- invalid or unsupported OpenAPI;
- missing base URL;
- unsafe URL, redirect failure, download failure, or oversized document;
- unavailable provider;
- provider timeout or upstream failure;
- invalid model output after correction;
- transaction or name-conflict failure.

Ordinary logs include only the document hash, operation counts, batch counts, generated object counts, elapsed time, provider ID, and structured error code. Logs do not contain API keys, full OpenAPI documents, or complete model responses.

Analysis and correction calls have bounded timeouts. URL input retains the existing redirect, network-target, and response-size protections.

## Testing

### Backend

Test:

- URL and file generation paths;
- Swagger 2.0 and OpenAPI 3.x inputs;
- enabled-provider selection and unavailable-provider rejection;
- single-pass analysis for up to 200 operations;
- grouped analysis and final synthesis for more than 200 operations;
- the 20-Skill and 10-Agent hard limits;
- invalid operation and Skill references;
- one correction attempt and failure after the second invalid response;
- enabling only referenced Tools;
- running Skills and enabled Agents bound to the selected provider;
- risk-based Agent mode defaults;
- deterministic name-conflict resolution;
- full rollback from failures at each persistence stage;
- admin authorization, CSRF, SSRF, redirect, timeout, and file-size protections;
- redacted logging.

### Frontend

Test:

- provider selection;
- URL/file mode switching and form validation;
- request payloads and CSRF behavior;
- progress, success summary, and retryable error states;
- generated Skill and Agent value/binding display;
- English and Simplified Chinese locale coverage.

## Acceptance Criteria

An administrator can select an enabled provider and submit a valid Swagger/OpenAPI URL or file. In one operation, Agent4API creates a new Source, enables only the Tools needed by the generated Skills, runs those Skills, and enables provider-bound core Agents that can immediately be used in chat.

The result never exceeds 20 Skills or 10 Agents. Failure leaves no partially generated objects in the database.
