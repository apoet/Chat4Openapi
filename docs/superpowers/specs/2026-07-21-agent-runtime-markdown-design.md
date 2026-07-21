# Agent Runtime, Human-in-loop, and Markdown Chat Design

Date: 2026-07-21
Status: Approved design

## Purpose

Replace the current Skill-as-model transparent chat path with one built-in Agent that handles every conversation. Skills remain reusable capability packages made from instructions and Tool allow-lists; they are not Agents. The Agent routes requests, dynamically loads one or more Skills, executes Tools, optionally asks the user to clarify missing business inputs, and returns Markdown responses.

This design also adds browser-local conversation history, safe Markdown rendering with tables, and editable Tool parameter descriptions/examples without allowing edits to imported request structure.

## Decisions

- The system has one independently configured built-in Agent.
- All browser, OpenAI-compatible, and Anthropic-compatible conversations pass through that Agent.
- Agent mode is configured independently of Skills. The default is `human_in_loop`.
- Human-in-loop never approves Tool calls. It only pauses for missing, ambiguous, or choice-dependent user input.
- Browser Chat honors the configured mode. Compatibility APIs always run non-interactively with ReAct behavior.
- Chat Skill selection is optional and supports multiple selections.
- No selected Skills means the Agent may route across every running Skill.
- Selected Skills restrict the candidate catalog; the Agent may load one or more of those candidates.
- Markdown is the Agent response format. Chat safely renders GFM tables and common Markdown constructs.
- Tool parameter descriptions and examples are editable overrides. Structural parameter fields remain owned by Swagger/OpenAPI.

## Architecture

### Global Agent configuration

Add a singleton Agent configuration record and an `Agent` administration menu. The record contains:

- display name;
- enabled state;
- general system prompt;
- mode: `human_in_loop` or `react`;
- maximum Agent iterations;
- timestamps.

The application creates the singleton with built-in defaults when no record exists. Default rules require the Agent to:

- choose Skills from their declared names and descriptions;
- load a Skill before using its Tools;
- never invent required Tool arguments;
- ask for clarification when a material ambiguity prevents a reliable call in human-in-loop mode;
- make and disclose a reasonable assumption in ReAct mode;
- use the user's language;
- prefer structured Markdown, including tables for structured results;
- explain exhausted retries, unavailable Skills, and Tool failures.

Restoring defaults replaces only the configurable Agent prompt and runtime settings. It does not modify Skills or Tools.

### Agent runtime

The runtime is an application-owned state machine rather than a third-party Agent framework:

1. `route`: expose metadata for eligible running Skills.
2. `load`: process the internal `load_skills` action and attach selected Skill instructions and Tool schemas.
3. `reason`: ask the configured LLM for the next action.
4. `clarify`: process `ask_user`, persist pending state, and return control to browser Chat.
5. `act`: execute a business Tool automatically.
6. `observe`: append the Tool result and continue reasoning.
7. `respond`: persist and return the final Markdown answer.

`load_skills` and `ask_user` are Agent control actions, not imported business Tools and not MCP tools. The runtime validates every requested Skill against the conversation's candidate set. Loaded Tool schemas are the union of Tools belonging to loaded Skills, with name collisions rejected or namespaced deterministically before execution.

The configured maximum iteration count bounds routing, control actions, Tool actions, and observations. Reaching the bound returns a structured Agent failure rather than an unhandled server error.

### Skill candidate selection

Browser Chat sends `candidate_skill_ids` with each new conversation:

- an empty array means all running Skills are candidates;
- one or more IDs restrict routing to those Skills;
- the candidate set is fixed for the conversation unless the user starts a new conversation.

The Agent receives only Skill catalog metadata during routing. It receives full Skill prompts and Tool schemas after `load_skills`. Compound requests may load multiple Skills. A browser-selected candidate is a scope restriction, not a forced eager load.

The compatibility APIs accept optional `chatapi_skill_ids` as an extension. Existing `skill-<id>` model identifiers remain compatible and are treated as a one-Skill candidate set. A generic built-in Agent model identifier exposes automatic routing across all running Skills.

## Human-in-loop behavior

Human-in-loop is a clarification mechanism, not an approval mechanism. Tool execution never displays an allow/deny prompt.

In browser Chat, the runtime exposes `ask_user` only when the global Agent mode is `human_in_loop`. The action contains:

- a Markdown question;
- a concise reason for clarification;
- optional choices;
- the missing or ambiguous field names.

The Agent persists the pending state and returns:

```json
{
  "status": "needs_input",
  "conversation_id": "...",
  "message": "请确认参考基因组：GRCh37 还是 GRCh38？",
  "loaded_skill_ids": [1],
  "pending": {
    "fields": ["reference"],
    "choices": ["GRCh37", "GRCh38"]
  }
}
```

The next user message resumes the same Agent run using the persisted conversation, loaded Skills, prior observations, and pending clarification. The runtime records the answer and clears the pending state before continuing.

For OpenAI- and Anthropic-compatible requests, the Agent always uses ReAct behavior and does not expose `ask_user`. If critical information is missing, it chooses a reasonable default based on Skill/Tool metadata and states that assumption in the final response.

## Conversation state and APIs

Add server-side Agent state associated with each conversation:

- candidate Skill IDs;
- loaded Skill IDs;
- runtime mode used for the channel;
- status: `running`, `needs_input`, `completed`, or `failed`;
- pending clarification payload;
- latest failure summary;
- timestamps.

Messages remain the canonical server-side execution history. A new browser endpoint, `POST /api/chat/turns`, accepts one user turn plus an optional conversation ID and candidate Skill IDs. It returns either `completed` or `needs_input`, the Markdown message, loaded Skill IDs, and the conversation ID.

The browser endpoint avoids encoding interactive state into OpenAI response objects. Compatibility endpoints retain their existing response formats and streaming envelopes while delegating execution to the Agent runtime in non-interactive mode.

Server history prevents a page refresh from losing Agent context. Browser storage remains responsible for the local history list and immediate transcript restoration.

## Browser Chat

The Chat workspace contains:

- local conversation history and New Chat;
- a multi-select candidate Skill control below the input;
- an empty selection label of “Agent auto-select”;
- loaded Skill indicators on Agent responses;
- a distinct clarification presentation for `needs_input`;
- one input box for both ordinary turns and clarification answers.

Each browser-local session stores a versioned record containing:

- local ID and server conversation ID;
- title;
- candidate Skill IDs;
- loaded Skill IDs;
- messages;
- pending clarification state;
- update time.

The loader migrates the previous `skillId` field to `skillIds: [skillId]`. Malformed local records are ignored. Starting a new conversation preserves prior sessions and creates a new local identity.

### Markdown rendering

Agent messages are rendered as sanitized GFM Markdown. Rendering supports:

- headings, paragraphs, lists, and blockquotes;
- fenced and inline code;
- links;
- GFM tables;
- line breaks.

Raw HTML is disabled. Generated HTML is sanitized before insertion into the DOM. Links use safe protocols and external links receive safe target/rel attributes. User messages remain plain text.

Table styles include horizontal overflow on narrow screens, visible headers, cell borders, and readable alternating rows. Markdown source remains stored unchanged in browser history.

## Varcards2-Gene output contract

The `Varcards2-Gene` Skill instructions require gene locus responses to include a Markdown table. At minimum the table has `Field` and `Result` columns and rows for gene symbol, chromosome, and cytogenetic location when returned by the Tool. Optional rows include full name, gene type, identifiers, and reference build.

Missing fields remain explicit instead of being invented. If the upstream result does not state GRCh37/GRCh38, the answer says the reference build is not provided. The response includes a concise source note after the table.

## Tool parameter description overrides

Add a parameter override record keyed by Tool ID and stable argument name. Each override may contain:

- custom description;
- custom example value.

The Tools page exposes editing beside each parameter. Parameter name, type, required status, request location, and execution mapping are read-only.

The effective Tool schema merges imported structure with overrides at read/runtime time:

- custom description replaces the imported description when present;
- custom example replaces or adds the imported example when present;
- all structural fields come from the latest imported schema.

API Source refresh reconciles overrides after updating Tools:

- preserve overrides for stable argument names that still exist;
- delete overrides for removed arguments;
- use imported descriptions/examples for new arguments;
- preserve overrides when operation parameters change in other structural ways.

Agent routing, Tool calls, and clarification generation always use the effective merged schema.

## Error handling

- No eligible Skill: return a localized, structured error.
- Explicit candidate Skill stopped or deleted: reject a new conversation; for an existing conversation, reroute among remaining candidates or explain that none remain.
- Invalid `load_skills` request: add an Agent observation and allow one correction within the iteration bound.
- Tool unavailable or failed: allow Agent recovery, alternative Tool selection, or a final explanation.
- Invalid Tool arguments: do not execute; in human-in-loop mode ask for the required user input, otherwise make and disclose a supported assumption or fail clearly.
- Provider/network failure: normalize to a structured Agent error without leaking credentials or upstream bodies containing secrets.
- Pending clarification resumed with an unrelated answer: the Agent may rephrase once, then explain what is still required.
- Unsafe Markdown: remove unsafe HTML, scripts, event handlers, and unsafe URL schemes.

## Administration and localization

The Agent menu and all new Chat, Tool parameter, status, and error strings are available in English and Simplified Chinese. English remains the default locale.

Agent configuration changes apply to new turns. Updating the mode does not rewrite stored conversations; the channel policy is evaluated when each turn starts. Editing an Agent configuration does not stop running Skills.

## Testing and acceptance

Backend tests cover:

- singleton Agent configuration defaults and administration;
- Agent routing across all Skills and a restricted multi-Skill candidate set;
- `load_skills` validation and Tool allow-list isolation;
- loading more than one Skill for a compound request;
- human-in-loop clarification, persistence, and resume;
- automatic Tool execution without approval;
- compatibility API ReAct behavior without interactive pauses;
- iteration limits and normalized failures;
- parameter override merge and refresh reconciliation;
- Varcards2-Gene table-oriented instructions.

Frontend tests cover:

- multi-select Skill behavior and auto-select empty state;
- browser history persistence and legacy migration;
- clarification display and resume requests;
- loaded Skill indicators;
- sanitized Markdown and GFM table rendering;
- parameter description/example editing while structural fields remain read-only.

End-to-end acceptance uses the running `Varcards2-Gene` Skill and the question `查询ABCA4位点`. The visible response must contain a rendered table with ABCA4, chromosome 1, and `1p22.1`; a page reload must restore the rendered answer and selected candidate Skills from browser storage.

## Out of scope

- Multiple independent Agents or Agent-to-Agent delegation.
- Tool-call approval prompts.
- A visual graph editor for Agent logic.
- Persisting browser history to a user account or synchronizing it across devices.
- Arbitrary edits to Swagger-owned parameter structure.
- Interactive clarification in OpenAI- or Anthropic-compatible clients.
