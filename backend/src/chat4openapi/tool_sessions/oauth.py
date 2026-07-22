import asyncio
import base64
import hashlib
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from chat4openapi.db.serialized_write import serialized_write
from chat4openapi.models import (
    ApiSource,
    ApiSourceOAuthConfig,
    EmbedSession,
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
    tool_session_db_id: int | None = None
    embed_session_id: int | None = None
    parent_origin: str | None = None
    target_origin: str | None = None


@dataclass(frozen=True, slots=True)
class PKCEStart:
    authorization_url: str
    state: str
    expires_at: datetime


class _UnusedExecutor:
    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("OAuth does not execute Tools")


def _positive_seconds(value: Any, *, default: int, maximum: int | None) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return default
    seconds = max(1, int(value))
    return min(maximum, seconds) if maximum is not None else seconds


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
        interval = _positive_seconds(payload.get("interval"), default=5, maximum=None)
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
        claimed = self._claim_device_poll(row.id, flow.id, now)
        if isinstance(claimed, OAuthStatus):
            return OAuthStatus(
                token,
                claimed.status,
                claimed.api_source_id,
                claimed.expires_at,
                claimed.interval,
            )
        generation, interval = claimed
        try:
            response = await self._post(source, config["token_url"], fields)
            payload = self._response_json(response)
        except OAuthFlowError:
            self._release_operation(flow.id, generation)
            raise
        return self._finish_device_poll(
            token,
            row.id,
            flow.id,
            generation,
            interval,
            response.status_code,
            payload,
        )

    def _claim_device_poll(
        self, row_id: int, flow_id: int, now: datetime
    ) -> tuple[int, int] | OAuthStatus:
        with serialized_write(self._session):
            row = self._session.get(ToolUserSession, row_id)
            flow = self._session.get(ToolOAuthAuthorization, flow_id)
            if row is None or flow is None:
                raise OAuthFlowError("oauth.session_not_found")
            interval = flow.interval_seconds or 5
            if flow.status != "pending":
                return OAuthStatus("", flow.status, flow.api_source_id, flow.expires_at, interval)
            if flow.expires_at <= now:
                self._terminal(row, flow, "expired", commit=False)
                return OAuthStatus("", "expired", flow.api_source_id, flow.expires_at, interval)
            lease_expires_at = (
                flow.operation_started_at + timedelta(seconds=60)
                if flow.operation_started_at is not None
                else None
            )
            retry_at = max(
                candidate
                for candidate in (flow.next_poll_at, lease_expires_at, now)
                if candidate is not None
            )
            must_wait = (
                flow.operation_in_progress and retry_at > now
            ) or (
                not flow.operation_in_progress
                and flow.next_poll_at is not None
                and flow.next_poll_at > now
            )
            if must_wait:
                retry_after = max(
                    1,
                    int((retry_at - now).total_seconds()),
                )
                raise OAuthPollingTooSoon(retry_after)
            flow.operation_generation += 1
            flow.operation_in_progress = True
            flow.operation_started_at = now
            flow.next_poll_at = now + timedelta(seconds=interval)
            return flow.operation_generation, interval

    def _release_operation(self, flow_id: int, generation: int) -> None:
        with serialized_write(self._session):
            flow = self._session.get(ToolOAuthAuthorization, flow_id)
            if (
                flow is not None
                and flow.operation_generation == generation
                and flow.operation_in_progress
                and flow.status == "pending"
            ):
                flow.operation_in_progress = False
                flow.operation_started_at = None

    def _finish_device_poll(
        self,
        token: str,
        row_id: int,
        flow_id: int,
        generation: int,
        interval: int,
        status_code: int,
        payload: Mapping[str, Any],
    ) -> OAuthStatus:
        with serialized_write(self._session):
            row = self._session.get(ToolUserSession, row_id)
            flow = self._session.get(ToolOAuthAuthorization, flow_id)
            if row is None or flow is None:
                raise OAuthFlowError("oauth.session_not_found")
            if (
                flow.status != "pending"
                or not flow.operation_in_progress
                or flow.operation_generation != generation
            ):
                return OAuthStatus(
                    token,
                    flow.status,
                    flow.api_source_id,
                    flow.expires_at,
                    flow.interval_seconds,
                )
            flow.operation_in_progress = False
            flow.operation_started_at = None
            if status_code < 400:
                try:
                    self._store_token(row, flow, payload, commit=False)
                except OAuthFlowError:
                    self._terminal(row, flow, "failed", commit=False)
                    return OAuthStatus(
                        token,
                        "failed",
                        flow.api_source_id,
                        flow.expires_at,
                        interval,
                    )
                return OAuthStatus(token, "ready", flow.api_source_id, row.absolute_expires_at)
            error = payload.get("error")
            if error == "authorization_pending":
                return OAuthStatus(token, "pending", flow.api_source_id, flow.expires_at, interval)
            if error == "slow_down":
                interval += 5
                flow.interval_seconds = interval
                flow.next_poll_at = self._now() + timedelta(seconds=interval)
                return OAuthStatus(token, "pending", flow.api_source_id, flow.expires_at, interval)
            terminal = "expired" if error == "expired_token" else "failed"
            self._terminal(row, flow, terminal, commit=False)
            return OAuthStatus(token, terminal, flow.api_source_id, flow.expires_at, interval)

    async def start_pkce(
        self,
        context: Any,
        source_id: int,
        *,
        agent_id: int,
    ) -> PKCEStart:
        if getattr(context, "admin_session", None) is None:
            raise OAuthFlowError("oauth.pkce_browser_required")
        return await self._start_pkce(context, source_id, agent_id=agent_id)

    async def start_embed_pkce(
        self,
        owner: EmbedSession,
        source_id: int,
        *,
        redirect_uri: str,
    ) -> PKCEStart:
        return await self._start_pkce(
            owner,
            source_id,
            agent_id=owner.agent_id,
            redirect_uri_override=redirect_uri,
        )

    async def _start_pkce(
        self,
        context: Any,
        source_id: int,
        *,
        agent_id: int,
        redirect_uri_override: str | None = None,
    ) -> PKCEStart:
        source = self._source(source_id)
        _, config = self._config(source.id)
        authorization_url = config.get("authorization_url")
        redirect_uri = config.get("redirect_uri") or redirect_uri_override
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
        if isinstance(context, EmbedSession):
            if (
                context.revoked_at is not None
                or context.absolute_expires_at <= now
                or context.agent_id != agent_id
            ):
                raise OAuthFlowError("oauth.session_not_found")
            expires_at = min(expires_at, context.absolute_expires_at)
            token = new_token()
            row = ToolUserSession(
                token_hash=hash_token(token),
                agent_id=context.agent_id,
                embed_session_id=context.id,
                status="pending",
                idle_expires_at=min(now + timedelta(minutes=30), expires_at),
                absolute_expires_at=expires_at,
                last_used_at=now,
            )
            self._session.add(row)
            self._session.flush()
            self._session.add(
                ToolSessionCredential(
                    tool_session_id=row.id,
                    api_source_id=source.id,
                    encrypted_credentials=self._cipher.encrypt_json({}),
                    status="pending",
                    expires_at=expires_at,
                    last_used_at=now,
                )
            )
            binding_data = {
                "embed_session_id": context.id,
                "parent_origin": context.parent_origin,
                "target_origin": (
                    f"{urlsplit(str(redirect_uri)).scheme}://"
                    f"{urlsplit(str(redirect_uri)).netloc}"
                ),
                "redirect_uri": redirect_uri,
            }
        else:
            token, row, _credential = self._pending_session(
                context, source.id, expires_at, agent_id=agent_id
            )
            binding_data = {"redirect_uri": redirect_uri}
        flow = ToolOAuthAuthorization(
            tool_session_id=row.id,
            api_source_id=source.id,
            flow_type="pkce",
            state_hash=hash_token(state),
            encrypted_flow_data=self._cipher.encrypt_json(
                {
                    "kind": "oauth",
                    "code_verifier": verifier,
                    "tool_session_token": token,
                    **binding_data,
                }
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
        try:
            unclaimed_flow_data = self._cipher.decrypt_json(flow.encrypted_flow_data)
        except Exception:
            unclaimed_flow_data = None
        if (
            isinstance(unclaimed_flow_data, dict)
            and unclaimed_flow_data.get("kind") == "swagger"
        ):
            raise OAuthFlowError("oauth.state_invalid")
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
        flow_id = flow.id
        row_id = flow.tool_session_id
        try:
            self._session.refresh(flow)
            source = self._source(flow.api_source_id)
            _, config = self._config(source.id)
            flow_data = self._cipher.decrypt_json(flow.encrypted_flow_data)
            fields = self._client_fields(config)
            fields.update(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": flow_data.get("redirect_uri")
                    or config.get("redirect_uri"),
                    "code_verifier": flow_data["code_verifier"],
                }
            )
            response = await self._post(source, config["token_url"], fields)
            payload = self._response_json(response)
            row = self._session.get(ToolUserSession, row_id)
            if row is None or response.status_code >= 400:
                raise OAuthFlowError("oauth.exchange_failed")
            embed_session_id = flow_data.get("embed_session_id")
            self._store_token(
                row,
                flow,
                payload,
                commit=not isinstance(embed_session_id, int),
            )
            if isinstance(embed_session_id, int):
                owner = self._session.get(EmbedSession, embed_session_id)
                if owner is None or owner.id != row.embed_session_id:
                    raise OAuthFlowError("oauth.session_not_found")
                row.absolute_expires_at = min(
                    row.absolute_expires_at, owner.absolute_expires_at
                )
                row.idle_expires_at = min(row.idle_expires_at, row.absolute_expires_at)
                credential = self._session.scalar(
                    select(ToolSessionCredential).where(
                        ToolSessionCredential.tool_session_id == row.id,
                        ToolSessionCredential.api_source_id == source.id,
                    )
                )
                if credential is not None and credential.expires_at is not None:
                    credential.expires_at = min(
                        credential.expires_at, row.absolute_expires_at
                    )
                self._session.commit()
            return OAuthStatus(
                flow_data["tool_session_token"],
                "ready",
                source.id,
                row.absolute_expires_at,
                tool_session_db_id=row.id,
                embed_session_id=flow_data.get("embed_session_id"),
                parent_origin=flow_data.get("parent_origin"),
                target_origin=flow_data.get("target_origin"),
            )
        except BaseException as exc:
            self._fail_claimed_pkce(flow_id, row_id)
            if not isinstance(exc, Exception):
                raise
            raise OAuthFlowError("oauth.exchange_failed") from None

    def _fail_claimed_pkce(self, flow_id: int, row_id: int) -> None:
        with serialized_write(self._session):
            flow = self._session.get(ToolOAuthAuthorization, flow_id)
            if (
                flow is None
                or flow.flow_type != "pkce"
                or flow.status != "pending"
                or flow.consumed_at is None
            ):
                return
            row = self._session.get(ToolUserSession, row_id)
            if row is not None:
                self._terminal(row, flow, "failed", commit=False)
                return
            flow.status = "failed"
            flow.operation_in_progress = False
            flow.operation_started_at = None
            flow.encrypted_flow_data = self._cipher.encrypt_json({})

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
        commit: bool = True,
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
        flow.operation_in_progress = False
        flow.operation_started_at = None
        flow.encrypted_flow_data = self._cipher.encrypt_json({})
        if commit:
            self._session.commit()

    def _terminal(
        self,
        row: ToolUserSession,
        flow: ToolOAuthAuthorization,
        status: str,
        *,
        commit: bool = True,
    ) -> None:
        row.status = status
        flow.status = status
        flow.operation_in_progress = False
        flow.operation_started_at = None
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
        if commit:
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
        claim_kind, generation, refresh_token = self._claim_refresh(
            row.id, credential.id
        )
        if claim_kind == "expired":
            raise OAuthFlowError("oauth.session_expired")
        if claim_kind == "wait":
            await self._wait_for_refresh(
                row.id, credential.id, generation
            )
            return
        assert refresh_token is not None
        flow = self._session.scalar(
            select(ToolOAuthAuthorization).where(
                ToolOAuthAuthorization.tool_session_id == row.id,
                ToolOAuthAuthorization.api_source_id == credential.api_source_id,
            )
        )
        if flow is None:
            raise OAuthFlowError("oauth.refresh_unavailable")
        try:
            source = self._source(credential.api_source_id)
            _, config = self._config(source.id)
            fields = self._client_fields(config)
            fields.update(
                {"grant_type": "refresh_token", "refresh_token": refresh_token}
            )
            response = await self._post(source, config["token_url"], fields)
            if response.status_code >= 400:
                raise OAuthFlowError("oauth.refresh_failed")
            payload = self._response_json(response)
        except Exception:
            self._finish_refresh_failure(flow.id, generation)
            raise OAuthFlowError("oauth.refresh_failed") from None
        if not self._finish_refresh_success(
            row.id,
            credential.id,
            flow.id,
            generation,
            refresh_token,
            payload,
        ):
            raise OAuthFlowError("oauth.refresh_failed")

    def _claim_refresh(
        self, row_id: int, credential_id: int
    ) -> tuple[str, int, str | None]:
        result: tuple[str, int, str | None]
        with serialized_write(self._session):
            now = self._now()
            row = self._session.get(ToolUserSession, row_id)
            credential = self._session.get(ToolSessionCredential, credential_id)
            flow = self._session.scalar(
                select(ToolOAuthAuthorization).where(
                    ToolOAuthAuthorization.tool_session_id == row_id,
                    ToolOAuthAuthorization.api_source_id
                    == (credential.api_source_id if credential is not None else -1),
                )
            )
            if row is None or credential is None or flow is None:
                raise OAuthFlowError("oauth.refresh_unavailable")
            if row.idle_expires_at <= now or row.absolute_expires_at <= now:
                self._expire_oauth_session(row)
                result = ("expired", flow.operation_generation, None)
            elif (
                row.status != "ready"
                or credential.status != "ready"
                or flow.status != "ready"
            ):
                raise OAuthFlowError("oauth.refresh_unavailable")
            else:
                lease_expires_at = (
                    flow.operation_started_at + timedelta(seconds=60)
                    if flow.operation_started_at is not None
                    else None
                )
                if (
                    flow.operation_in_progress
                    and lease_expires_at is not None
                    and lease_expires_at > now
                ):
                    result = ("wait", flow.operation_generation, None)
                else:
                    stored = self._cipher.decrypt_json(
                        credential.encrypted_credentials
                    )
                    oauth = stored.get("oauth", {}) if isinstance(stored, dict) else {}
                    refresh_token = (
                        oauth.get("refresh_token") if isinstance(oauth, dict) else None
                    )
                    if not isinstance(refresh_token, str) or not refresh_token:
                        raise OAuthFlowError("oauth.refresh_unavailable")
                    flow.operation_generation += 1
                    flow.operation_in_progress = True
                    flow.operation_started_at = now
                    result = ("claimed", flow.operation_generation, refresh_token)
        return result

    def _expire_oauth_session(self, row: ToolUserSession) -> None:
        row.status = "expired"
        row.encrypted_login_data = None
        row.encrypted_auth_data = None
        for credential in self._session.scalars(
            select(ToolSessionCredential).where(
                ToolSessionCredential.tool_session_id == row.id
            )
        ):
            credential.status = "expired"
            credential.encrypted_credentials = self._cipher.encrypt_json({})
        for flow in self._session.scalars(
            select(ToolOAuthAuthorization).where(
                ToolOAuthAuthorization.tool_session_id == row.id
            )
        ):
            flow.status = "expired"
            flow.operation_in_progress = False
            flow.operation_started_at = None
            flow.encrypted_flow_data = self._cipher.encrypt_json({})

    async def _wait_for_refresh(
        self, row_id: int, credential_id: int, generation: int
    ) -> None:
        deadline = asyncio.get_running_loop().time() + 25
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
            self._session.rollback()
            self._session.expire_all()
            credential = self._session.get(ToolSessionCredential, credential_id)
            flow = self._session.scalar(
                select(ToolOAuthAuthorization).where(
                    ToolOAuthAuthorization.tool_session_id == row_id,
                    ToolOAuthAuthorization.api_source_id
                    == (credential.api_source_id if credential is not None else -1),
                )
            )
            if credential is None or flow is None:
                raise OAuthFlowError("oauth.refresh_failed")
            if flow.operation_in_progress and flow.operation_generation == generation:
                continue
            if (
                flow.status == "ready"
                and credential.status == "ready"
                and flow.operation_generation >= generation
                and not flow.operation_in_progress
            ):
                return
            raise OAuthFlowError("oauth.refresh_failed")
        raise OAuthFlowError("oauth.refresh_failed")

    def _finish_refresh_failure(self, flow_id: int, generation: int) -> None:
        with serialized_write(self._session):
            flow = self._session.get(ToolOAuthAuthorization, flow_id)
            if (
                flow is None
                or not flow.operation_in_progress
                or flow.operation_generation != generation
                or flow.status != "ready"
            ):
                return
            row = self._session.get(ToolUserSession, flow.tool_session_id)
            if row is not None:
                self._terminal(row, flow, "failed", commit=False)

    def _finish_refresh_success(
        self,
        row_id: int,
        credential_id: int,
        flow_id: int,
        generation: int,
        prior_refresh_token: str,
        payload: Mapping[str, Any],
    ) -> bool:
        succeeded = False
        with serialized_write(self._session):
            row = self._session.get(ToolUserSession, row_id)
            credential = self._session.get(ToolSessionCredential, credential_id)
            flow = self._session.get(ToolOAuthAuthorization, flow_id)
            if row is None or credential is None or flow is None:
                return False
            if (
                not flow.operation_in_progress
                or flow.operation_generation != generation
                or flow.status != "ready"
            ):
                return False
            try:
                self._store_token(
                    row,
                    flow,
                    payload,
                    prior_refresh_token=prior_refresh_token,
                    commit=False,
                )
            except OAuthFlowError:
                self._terminal(row, flow, "failed", commit=False)
            else:
                succeeded = True
        return succeeded
