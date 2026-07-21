# M7 Brief: OAuth Device Flow and PKCE

## Scope

- Add encrypted, per-API-source OAuth client configuration.
- Add OAuth 2.0 Device Authorization Grant start and explicit status polling for Agent-key owners.
- Add Authorization Code + PKCE (S256) start/callback for authenticated browser administrators.
- Materialize successful OAuth grants as the existing Agent/owner/source-bound Tool Session credential.
- Refresh an OAuth credential without crossing its Tool Session owner or API Source boundary.

## Security invariants

- Authorization, device, and token URLs are read only from the stored source configuration. Request
  bodies cannot override them. Each target is checked by the existing network policy using the
  source's `allow_private_networks` setting.
- Device codes, PKCE verifiers, callback Tool Session tokens, client secrets, access tokens, and
  refresh tokens are encrypted at rest and are never returned or logged. The Device `user_code`
  and verification URL are public protocol instructions and may be returned.
- PKCE uses a high-entropy verifier, S256 challenge, a high-entropy state stored only as a hash,
  and atomic one-time state consumption before token exchange. Expired, replayed, or mismatched
  states fail without revealing whether another owner's flow exists.
- Device polling persists and enforces `interval`; `slow_down` increases it, while pending, denied,
  and expired responses map to stable local states without leaking upstream payloads.
- OAuth is pre-authorization only. AgentRuntime, Chat, and Tool execution never redirect and never
  wait for user authorization. Only the explicit Device status endpoint polls the issuer.
- Agent API keys may start/poll Device Flow only for their bound Agent. PKCE mutations use the
  administrator cookie plus CSRF; callback authentication is the one-time state.

## Persistence

- `api_source_oauth_configs`: one encrypted client configuration per API Source.
- `tool_oauth_authorizations`: one flow record per Tool Session/source with encrypted flow state,
  state hash, polling schedule, expiry, consumed timestamp, and terminal status.
- Successful exchange updates the existing `tool_session_credentials` row with encrypted bearer
  and refresh metadata and changes both the credential and Tool Session to `ready`.

## Test strategy

- Deterministic mock HTTP transport; no real issuer network.
- RED first for model/service/routes, then minimal GREEN implementation.
- Cover Device success, interval, pending, slow_down, denied, expired; PKCE S256, callback,
  mismatch/replay/expiry; owner/source isolation; encrypted secrets and redacted errors; refresh;
  CSRF and network-policy/config URL boundaries.
