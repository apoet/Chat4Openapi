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
