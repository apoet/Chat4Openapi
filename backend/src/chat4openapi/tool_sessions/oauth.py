import base64
import hashlib
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from chat4openapi.models import (
    ApiSource,
    ApiSourceOAuthConfig,
    ToolOAuthAuthorization,
    ToolSessionCredential,
    ToolUserSession,
)
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.security.session_tokens import hash_token, new_token
from chat4openapi.tool_sessions.credentials import auth_to_json
from chat4openapi.tool_sessions.service import ToolSessionService, utc_now
from chat4openapi.tools.network_policy import validate_network_target
from chat4openapi.tools.executor import RequestAuth

NetworkValidator = Callable[[httpx.URL, bool], Awaitable[None]]


class OAuthFlowError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class OAuthPollingTooSoon(OAuthFlowError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("oauth.poll_too_soon")
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class OAuthStatus:
    tool_session_id: str
    status: str
    api_source_id: int
    expires_at: datetime
    interval: int | None = None
    user_code: str | None = None
    verification_uri: str | None = None
    verification_uri_complete: str | None = None


@dataclass(frozen=True, slots=True)
class PKCEStart:
    authorization_url: str
    state: str
    expires_at: datetime


class _UnusedExecutor:
    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("OAuth does not execute Tools")


def _positive_seconds(value: Any, *, default: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return default
    return min(maximum, max(1, int(value)))


def _safe_url(value: Any, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise OAuthFlowError("oauth.config_invalid")
    try:
        parsed = httpx.URL(value.strip())
    except (TypeError, ValueError) as exc:
        raise OAuthFlowError("oauth.config_invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.host or parsed.userinfo or parsed.fragment:
        raise OAuthFlowError("oauth.config_invalid")
    return str(parsed)


class ToolOAuthService:
    def __init__(
        self,
        session: Session,
        cipher: SecretCipher,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        network_validator: NetworkValidator = validate_network_target,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._cipher = cipher
        self._transport = transport
        self._network_validator = network_validator
        self._now = now

    def configure_source(self, source_id: int, supplied: Mapping[str, Any]) -> None:
        source = self._source(source_id)
        client_id = supplied.get("client_id")
        if not isinstance(client_id, str) or not client_id.strip():
            raise OAuthFlowError("oauth.config_invalid")
        scopes = supplied.get("scopes", [])
        if not isinstance(scopes, list) or any(
            not isinstance(scope, str) or not scope.strip() for scope in scopes
        ):
            raise OAuthFlowError("oauth.config_invalid")
        config = {
            "client_id": client_id.strip(),
            "client_secret": supplied.get("client_secret") or None,
            "authorization_url": _safe_url(supplied.get("authorization_url"), required=False),
            "token_url": _safe_url(supplied.get("token_url")),
            "device_authorization_url": _safe_url(
                supplied.get("device_authorization_url"), required=False
            ),
            "redirect_uri": _safe_url(supplied.get("redirect_uri"), required=False),
            "scopes": [scope.strip() for scope in scopes],
        }
        if config["client_secret"] is not None and not isinstance(config["client_secret"], str):
            raise OAuthFlowError("oauth.config_invalid")
        row = self._session.get(ApiSourceOAuthConfig, source.id)
        if row is None:
            row = ApiSourceOAuthConfig(api_source_id=source.id, encrypted_config=b"")
            self._session.add(row)
        row.encrypted_config = self._cipher.encrypt_json(config)
        row.enabled = bool(supplied.get("enabled", True))
        self._session.commit()

    def config_summary(self, source_id: int) -> dict[str, Any]:
        self._source(source_id)
        row, config = self._config(source_id)
        return {
            "api_source_id": source_id,
            "enabled": row.enabled,
            "client_id": config["client_id"],
            "has_client_secret": bool(config.get("client_secret")),
            "authorization_url": config.get("authorization_url"),
            "token_url": config["token_url"],
            "device_authorization_url": config.get("device_authorization_url"),
            "redirect_uri": config.get("redirect_uri"),
            "scopes": list(config.get("scopes", [])),
        }

    def _source(self, source_id: int) -> ApiSource:
        source = self._session.get(ApiSource, source_id)
        if source is None or source.deleted_at is not None or not source.enabled:
            raise OAuthFlowError("oauth.source_not_found")
        return source

    def _config(self, source_id: int) -> tuple[ApiSourceOAuthConfig, dict[str, Any]]:
        row = self._session.get(ApiSourceOAuthConfig, source_id)
        if row is None or not row.enabled:
            raise OAuthFlowError("oauth.not_configured")
        config = self._cipher.decrypt_json(row.encrypted_config)
        if not isinstance(config, dict):
            raise OAuthFlowError("oauth.not_configured")
        return row, config

    async def _post(self, source: ApiSource, url: str, data: Mapping[str, str]) -> httpx.Response:
        target = httpx.URL(url)
        try:
            await self._network_validator(target, source.allow_private_networks)
            async with httpx.AsyncClient(
                transport=self._transport,
                follow_redirects=False,
                timeout=httpx.Timeout(20, connect=10),
            ) as client:
                response = await client.post(target, data=data)
        except (httpx.RequestError, ValueError) as exc:
            raise OAuthFlowError("oauth.upstream_failed") from exc
        if response.is_redirect:
            raise OAuthFlowError("oauth.upstream_failed")
        return response

    @staticmethod
    def _client_fields(config: Mapping[str, Any]) -> dict[str, str]:
        fields = {"client_id": str(config["client_id"])}
        secret = config.get("client_secret")
        if isinstance(secret, str) and secret:
            fields["client_secret"] = secret
        return fields

    def _pending_session(
        self,
        context: Any,
        source_id: int,
        expires_at: datetime,
        *,
        agent_id: int | None,
    ) -> tuple[str, ToolUserSession, ToolSessionCredential]:
        session_service = ToolSessionService(self._session, self._cipher, _UnusedExecutor(), now=self._now)
        token, row = session_service._new_row(
            context=context,
            agent_id=agent_id,
            absolute_expires_at=expires_at,
        )
        row.status = "pending"
        credential = ToolSessionCredential(
            tool_session_id=row.id,
            api_source_id=source_id,
            encrypted_credentials=self._cipher.encrypt_json({}),
            status="pending",
            expires_at=expires_at,
            last_used_at=self._now(),
        )
        self._session.add(credential)
        self._session.flush()
        return token, row, credential

    async def start_device(
        self, context: Any, source_id: int, *, agent_id: int | None = None
    ) -> OAuthStatus:
        source = self._source(source_id)
        _, config = self._config(source_id)
        device_url = config.get("device_authorization_url")
        if not device_url:
            raise OAuthFlowError("oauth.device_not_configured")
        fields = self._client_fields(config)
        if config.get("scopes"):
            fields["scope"] = " ".join(config["scopes"])
        response = await self._post(source, str(device_url), fields)
        try:
            payload = response.json()
        except ValueError as exc:
            raise OAuthFlowError("oauth.upstream_failed") from exc
        if response.status_code >= 400 or not isinstance(payload, dict):
            raise OAuthFlowError("oauth.upstream_failed")
        device_code = payload.get("device_code")
        user_code = payload.get("user_code")
        verification_uri = payload.get("verification_uri") or payload.get("verification_url")
        if not all(isinstance(value, str) and value for value in (device_code, user_code, verification_uri)):
            raise OAuthFlowError("oauth.upstream_failed")
        expires_in = _positive_seconds(payload.get("expires_in"), default=600, maximum=3600)
        interval = _positive_seconds(payload.get("interval"), default=5, maximum=60)
        now = self._now()
        expires_at = now + timedelta(seconds=expires_in)
        token, row, _credential = self._pending_session(
            context, source_id, expires_at, agent_id=agent_id
        )
        complete = payload.get("verification_uri_complete")
        flow = ToolOAuthAuthorization(
            tool_session_id=row.id,
            api_source_id=source_id,
            flow_type="device",
            encrypted_flow_data=self._cipher.encrypt_json(
                {"device_code": device_code, "tool_session_token": token}
            ),
            status="pending",
            interval_seconds=interval,
            next_poll_at=now + timedelta(seconds=interval),
            expires_at=expires_at,
        )
        self._session.add(flow)
        self._session.commit()
        return OAuthStatus(
            token,
            "pending",
            source_id,
            expires_at,
            interval=interval,
            user_code=user_code,
            verification_uri=verification_uri,
            verification_uri_complete=complete if isinstance(complete, str) else None,
        )

    def _bound_flow(self, token: str, context: Any, flow_type: str) -> tuple[ToolUserSession, ToolOAuthAuthorization]:
        service = ToolSessionService(self._session, self._cipher, _UnusedExecutor(), now=self._now)
        binding = service.binding_for_context(token, context)
        row = service._find(token, *binding)
        flow = self._session.scalar(
            select(ToolOAuthAuthorization).where(
                ToolOAuthAuthorization.tool_session_id == row.id,
                ToolOAuthAuthorization.flow_type == flow_type,
            )
        )
        if flow is None:
            raise OAuthFlowError("oauth.session_not_found")
        return row, flow

    async def poll_device(self, token: str, context: Any) -> OAuthStatus:
        row, flow = self._bound_flow(token, context, "device")
        now = self._now()
        if flow.status != "pending":
            return OAuthStatus(token, flow.status, flow.api_source_id, flow.expires_at, flow.interval_seconds)
        if flow.expires_at <= now:
            self._terminal(row, flow, "expired")
            return OAuthStatus(token, "expired", flow.api_source_id, flow.expires_at, flow.interval_seconds)
        if flow.next_poll_at is not None and flow.next_poll_at > now:
            retry_after = max(1, int((flow.next_poll_at - now).total_seconds()))
            raise OAuthPollingTooSoon(retry_after)
        source = self._source(flow.api_source_id)
        _, config = self._config(source.id)
        flow_data = self._cipher.decrypt_json(flow.encrypted_flow_data)
        fields = self._client_fields(config)
        fields.update(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": flow_data["device_code"],
            }
        )
        response = await self._post(source, config["token_url"], fields)
        payload = self._response_json(response)
        if response.status_code < 400:
            self._store_token(row, flow, payload)
            return OAuthStatus(token, "ready", source.id, row.absolute_expires_at)
        error = payload.get("error")
        interval = flow.interval_seconds or 5
        if error == "authorization_pending":
            flow.next_poll_at = now + timedelta(seconds=interval)
            self._session.commit()
            return OAuthStatus(token, "pending", source.id, flow.expires_at, interval)
        if error == "slow_down":
            interval = min(60, interval + 5)
            flow.interval_seconds = interval
            flow.next_poll_at = now + timedelta(seconds=interval)
            self._session.commit()
            return OAuthStatus(token, "pending", source.id, flow.expires_at, interval)
        terminal = "expired" if error == "expired_token" else "failed"
        self._terminal(row, flow, terminal)
        return OAuthStatus(token, terminal, source.id, flow.expires_at, interval)

    async def start_pkce(
        self,
        context: Any,
        source_id: int,
        *,
        agent_id: int,
    ) -> PKCEStart:
        if getattr(context, "admin_session", None) is None:
            raise OAuthFlowError("oauth.pkce_browser_required")
        source = self._source(source_id)
        _, config = self._config(source.id)
        authorization_url = config.get("authorization_url")
        redirect_uri = config.get("redirect_uri")
        if not authorization_url or not redirect_uri:
            raise OAuthFlowError("oauth.pkce_not_configured")
        await self._network_validator(
            httpx.URL(str(authorization_url)), source.allow_private_networks
        )
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        state = new_token()
        now = self._now()
        expires_at = now + timedelta(minutes=10)
        token, row, _credential = self._pending_session(
            context, source.id, expires_at, agent_id=agent_id
        )
        flow = ToolOAuthAuthorization(
            tool_session_id=row.id,
            api_source_id=source.id,
            flow_type="pkce",
            state_hash=hash_token(state),
            encrypted_flow_data=self._cipher.encrypt_json(
                {"code_verifier": verifier, "tool_session_token": token}
            ),
            status="pending",
            expires_at=expires_at,
        )
        self._session.add(flow)
        self._session.commit()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": config["client_id"],
                "redirect_uri": redirect_uri,
                "scope": " ".join(config.get("scopes", [])),
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return PKCEStart(f"{authorization_url}{'&' if '?' in authorization_url else '?'}{query}", state, expires_at)

    async def complete_pkce(self, state: str, code: str) -> OAuthStatus:
        if not state or not code:
            raise OAuthFlowError("oauth.state_invalid")
        now = self._now()
        state_hash = hash_token(state)
        flow = self._session.scalar(
            select(ToolOAuthAuthorization).where(
                ToolOAuthAuthorization.state_hash == state_hash,
                ToolOAuthAuthorization.flow_type == "pkce",
            )
        )
        if flow is None or flow.status != "pending" or flow.consumed_at is not None:
            raise OAuthFlowError("oauth.state_invalid")
        if flow.expires_at <= now:
            row = self._session.get(ToolUserSession, flow.tool_session_id)
            if row is not None:
                self._terminal(row, flow, "expired")
            else:
                flow.status = "expired"
                flow.encrypted_flow_data = self._cipher.encrypt_json({})
                self._session.commit()
            raise OAuthFlowError("oauth.state_expired")
        claimed = self._session.execute(
            update(ToolOAuthAuthorization)
            .where(
                ToolOAuthAuthorization.id == flow.id,
                ToolOAuthAuthorization.consumed_at.is_(None),
                ToolOAuthAuthorization.status == "pending",
            )
            .values(consumed_at=now)
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            self._session.rollback()
            raise OAuthFlowError("oauth.state_invalid")
        self._session.commit()
        self._session.refresh(flow)
        source = self._source(flow.api_source_id)
        _, config = self._config(source.id)
        flow_data = self._cipher.decrypt_json(flow.encrypted_flow_data)
        fields = self._client_fields(config)
        fields.update(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config["redirect_uri"],
                "code_verifier": flow_data["code_verifier"],
            }
        )
        response = await self._post(source, config["token_url"], fields)
        payload = self._response_json(response)
        row = self._session.get(ToolUserSession, flow.tool_session_id)
        if row is None or response.status_code >= 400:
            if row is not None:
                self._terminal(row, flow, "failed")
            raise OAuthFlowError("oauth.exchange_failed")
        self._store_token(row, flow, payload)
        return OAuthStatus(
            flow_data["tool_session_token"], "ready", source.id, row.absolute_expires_at
        )

    @staticmethod
    def _response_json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise OAuthFlowError("oauth.upstream_failed") from exc
        if not isinstance(payload, dict):
            raise OAuthFlowError("oauth.upstream_failed")
        return payload

    def _store_token(
        self,
        row: ToolUserSession,
        flow: ToolOAuthAuthorization,
        payload: Mapping[str, Any],
        *,
        prior_refresh_token: str | None = None,
    ) -> None:
        access_token = payload.get("access_token")
        token_type = payload.get("token_type", "Bearer")
        if (
            not isinstance(access_token, str)
            or not access_token
            or not isinstance(token_type, str)
            or token_type.lower() != "bearer"
            or any(ord(character) < 33 or ord(character) == 127 for character in access_token)
        ):
            raise OAuthFlowError("oauth.exchange_failed")
        refresh_token = payload.get("refresh_token", prior_refresh_token)
        if refresh_token is not None and (
            not isinstance(refresh_token, str)
            or not refresh_token
            or any(ord(character) < 33 or ord(character) == 127 for character in refresh_token)
        ):
            raise OAuthFlowError("oauth.exchange_failed")
        now = self._now()
        expires_in = _positive_seconds(payload.get("expires_in"), default=3600, maximum=86400)
        access_expires_at = now + timedelta(seconds=expires_in)
        credential = self._session.scalar(
            select(ToolSessionCredential).where(
                ToolSessionCredential.tool_session_id == row.id,
                ToolSessionCredential.api_source_id == flow.api_source_id,
            )
        )
        if credential is None:
            raise OAuthFlowError("oauth.session_not_found")
        encrypted = auth_to_json(
            RequestAuth(headers={"Authorization": f"Bearer {access_token}"})
        )
        encrypted["oauth"] = {
            "refresh_token": refresh_token,
            "token_type": "Bearer",
        }
        absolute_expires_at = (
            row.absolute_expires_at
            if prior_refresh_token is not None
            else (now + timedelta(hours=8) if refresh_token else access_expires_at)
        )
        credential.encrypted_credentials = self._cipher.encrypt_json(encrypted)
        credential.status = "ready"
        credential.expires_at = min(access_expires_at, absolute_expires_at)
        credential.last_used_at = now
        row.status = "ready"
        row.auth_expires_at = credential.expires_at
        row.absolute_expires_at = absolute_expires_at
        row.idle_expires_at = min(now + timedelta(minutes=30), row.absolute_expires_at)
        flow.status = "ready"
        flow.encrypted_flow_data = self._cipher.encrypt_json({})
        self._session.commit()

    def _terminal(self, row: ToolUserSession, flow: ToolOAuthAuthorization, status: str) -> None:
        row.status = status
        flow.status = status
        flow.encrypted_flow_data = self._cipher.encrypt_json({})
        credential = self._session.scalar(
            select(ToolSessionCredential).where(
                ToolSessionCredential.tool_session_id == row.id,
                ToolSessionCredential.api_source_id == flow.api_source_id,
            )
        )
        if credential is not None:
            credential.status = status
            credential.encrypted_credentials = self._cipher.encrypt_json({})
        self._session.commit()

    async def refresh(self, token: str, context: Any, source_id: int) -> OAuthStatus:
        service = ToolSessionService(self._session, self._cipher, _UnusedExecutor(), now=self._now)
        binding = service.binding_for_context(token, context)
        row = service._find(token, *binding)
        flow = self._session.scalar(
            select(ToolOAuthAuthorization).where(
                ToolOAuthAuthorization.tool_session_id == row.id,
                ToolOAuthAuthorization.api_source_id == source_id,
                ToolOAuthAuthorization.status == "ready",
            )
        )
        credential = self._session.scalar(
            select(ToolSessionCredential).where(
                ToolSessionCredential.tool_session_id == row.id,
                ToolSessionCredential.api_source_id == source_id,
            )
        )
        if flow is None or credential is None:
            raise OAuthFlowError("oauth.session_not_found")
        await self.refresh_bound(row, credential)
        return OAuthStatus(token, "ready", source_id, row.absolute_expires_at)

    async def refresh_bound(
        self, row: ToolUserSession, credential: ToolSessionCredential
    ) -> None:
        flow = self._session.scalar(
            select(ToolOAuthAuthorization).where(
                ToolOAuthAuthorization.tool_session_id == row.id,
                ToolOAuthAuthorization.api_source_id == credential.api_source_id,
                ToolOAuthAuthorization.status == "ready",
            )
        )
        if flow is None:
            raise OAuthFlowError("oauth.refresh_unavailable")
        stored = self._cipher.decrypt_json(credential.encrypted_credentials)
        oauth = stored.get("oauth", {}) if isinstance(stored, dict) else {}
        refresh_token = oauth.get("refresh_token") if isinstance(oauth, dict) else None
        if not isinstance(refresh_token, str) or not refresh_token:
            raise OAuthFlowError("oauth.refresh_unavailable")
        source = self._source(credential.api_source_id)
        _, config = self._config(source.id)
        fields = self._client_fields(config)
        fields.update({"grant_type": "refresh_token", "refresh_token": refresh_token})
        response = await self._post(source, config["token_url"], fields)
        if response.status_code >= 400:
            self._terminal(row, flow, "failed")
            raise OAuthFlowError("oauth.refresh_failed")
        self._store_token(
            row,
            flow,
            self._response_json(response),
            prior_refresh_token=refresh_token,
        )
