# M7 Report: OAuth Device Flow and PKCE

## Outcome

- Added encrypted, per-API-source OAuth configuration with CSRF-protected administrator APIs.
- Added Agent-key-bound OAuth Device Authorization start and explicit status polling. Polling
  persists and enforces the issuer interval, implements `authorization_pending` and `slow_down`,
  and maps denial/expiry to redacted terminal states.
- Added browser administrator Authorization Code + PKCE start and callback. PKCE uses S256, a
  high-entropy verifier, a hashed high-entropy state, atomic one-time state consumption, and an
  HTTP-only Tool Session cookie after successful callback.
- Successful grants populate the existing M6 Agent/owner/source-bound encrypted credential row.
  Device codes, verifiers, client secrets, access tokens, refresh tokens, and callback Tool Session
  tokens remain encrypted and are erased from flow state on completion/failure/expiry.
- Added safe OAuth refresh for explicit clients and Tool execution. Refresh preserves the original
  absolute Tool Session lifetime and reuses only the matching owner/source credential. Runtime
  refresh is a direct token request: it never redirects, polls authorization, or waits for users.
- Added Alembic revision `0010_tool_oauth` and verified `0009 -> 0010 -> 0009 -> 0010`.

## Security boundaries

- OAuth endpoints come only from encrypted source configuration; request schemas reject arbitrary
  endpoint fields. Authorization/device/token targets use the existing API Source private-network
  policy, HTTP credentials/fragments are rejected, and upstream redirects are not followed.
- Device operations require the bound Agent API key. PKCE start requires an administrator browser
  session and CSRF. Callback authorization relies only on the single-use state.
- API/config/status/callback responses contain protocol instructions and metadata only, never
  client secrets, device codes, verifiers, access tokens, refresh tokens, or injected credentials.
- Revoked/expired Agent keys and expired/revoked administrator sessions remain enforced by the M6
  owner binding before polling, refresh, status, or Tool use.

## TDD evidence

- Initial model/service RED: imports for `ApiSourceOAuthConfig` and `ToolOAuthAuthorization` failed.
- Initial route RED: `chat4openapi.api.tool_oauth` did not exist.
- Runtime refresh RED: OAuth had no bound-credential refresher.
- Absolute-lifetime RED: refresh moved the absolute expiry forward by two seconds.
- PKCE network-policy RED: the authorization endpoint was not validated.
- Expiry hygiene RED: an expired PKCE record retained its encrypted verifier and Session token.

All failures were observed before the corresponding production changes.

## Verification

The requested `chat4openapi` Conda environment is not installed locally; verification used the
repository's existing Python 3.12 `chatapi` environment without adding that legacy name to tracked
files.

- Focused OAuth/Tool Session/migration suites: `38 passed`.
- Full backend suite: `260 passed`.
- Ruff: `All checks passed!` for `backend/src` and `backend/tests`.
- Alembic: `0010_tool_oauth (head)`.
- `git diff --check`: clean.
- Tracked legacy-product-name scan: clean.
- Production/migration test-secret scan: clean.

## Independent-review fixes

- Preserved issuer Device Flow polling intervals above 60 seconds and made every `slow_down`
  response add another five seconds without a 60-second ceiling.
- Added SQLite-serialized, generation-bound operation claims before Device token requests. A
  second real database Session cannot cross the issuer network boundary, every actual attempt
  (including network and JSON failures) advances the durable throttle, and a late stale result
  cannot overwrite a newer success. Claims use a 60-second lease so process cancellation or a
  crash cannot leave a flow permanently in flight.
- Made every post-claim PKCE callback failure converge atomically to the same redacted
  `oauth.exchange_failed` result. Disabled/missing sources or configuration, encrypted-data
  failures, network/JSON errors, non-2xx responses, and missing access tokens now erase both the
  encrypted flow payload and the corresponding credential ciphertext.
- Serialized OAuth refresh per Tool Session and API Source with the same durable generation
  claim. Concurrent callers singleflight on the winner, rotating refresh tokens are retained,
  and generation-checked finalization prevents a stale failure from deleting a newer token.
- Refresh now checks Session status, idle expiry, and absolute expiry before any issuer request.
  Expired Sessions are atomically marked expired and all associated credential/flow ciphertext is
  erased.
- Tool execution refreshes and replays exactly once after HTTP 401 only. HTTP 403 is returned
  directly without refresh or replay.
- Added Alembic revision `0011_oauth_operation_claims` for durable generation, in-flight, and
  lease-start state; verified `0010 -> 0011 -> 0010 -> 0011`.

### Review-fix TDD evidence

- Device RED: four failures proved the 60-second interval cap, concurrent double polling, and
  missing throttling after network and invalid-JSON attempts. A separate RED proved an abandoned
  in-flight claim was not recoverable.
- PKCE RED: seven of eight parameterized failure modes retained sensitive flow/credential state
  or returned an unstable error; the pre-existing non-2xx cleanup case was already green.
- Refresh RED: idle and absolute expiry each reached the issuer, while two real database Sessions
  issued competing refreshes and allowed a late failure against a rotating token.
- Retry RED: a 403 Tool response refreshed credentials and executed the Tool a second time.

### Review-fix verification

- Focused OAuth, Tool Session, credential, and migration suites: `57 passed`.
- Full backend suite: `279 passed`.
- Ruff: `All checks passed!` for backend source, migrations, and tests.
- Alembic head: `0011_oauth_operation_claims (head)`; both OAuth migration roundtrips passed.
- `git diff --check`: clean.
- Production/migration secret-literal, logging, legacy product-name, and legacy Tool Session header
  scans: no matches.
