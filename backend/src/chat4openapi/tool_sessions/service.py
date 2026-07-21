from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from chat4openapi.models import (
    AdminSession,
    Agent,
    AgentApiKey,
    ApiSource,
    GlobalToolAuthConfig,
    Tool,
    ToolSessionCredential,
    ToolUserSession,
)
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.security.session_tokens import hash_token, new_token
from chat4openapi.tool_sessions.auth_mapping import build_request_auth, extract_json_path
from chat4openapi.tool_sessions.credentials import (
    auth_from_json,
    auth_to_json,
    credential_expiry,
    validate_and_normalize_credentials,
)
from chat4openapi.tools.errors import ToolExecutionError
from chat4openapi.tools.executor import RequestAuth, ToolExecutionResult


class Executor(Protocol):
    async def execute(
        self,
        tool: Tool,
        source: ApiSource,
        arguments: Mapping[str, Any],
        auth: RequestAuth,
    ) -> ToolExecutionResult: ...


class ToolSessionError(RuntimeError):
    pass


class ToolLoginDisabled(ToolSessionError):
    pass


class ToolSessionNotFound(ToolSessionError):
    pass


class ToolSessionExpired(ToolSessionError):
    pass


class ToolSessionReauthorizationRequired(ToolSessionError):
    pass


@dataclass(frozen=True, slots=True)
class CreatedToolSession:
    token: str
    token_hash: str
    idle_expires_at: datetime
    absolute_expires_at: datetime
    status: str = "ready"
    api_source_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedToolSession:
    id: int
    auth: RequestAuth
    idle_expires_at: datetime
    absolute_expires_at: datetime
    status: str = "ready"
    api_source_id: int | None = None


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


class ToolSessionService:
    def __init__(
        self,
        session: Session,
        cipher: SecretCipher,
        executor: Executor,
        *,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._cipher = cipher
        self._executor = executor
        self._now = now

    def _config(self) -> GlobalToolAuthConfig:
        config = self._session.get(GlobalToolAuthConfig, 1)
        if config is None or not config.enabled or config.login_tool_id is None:
            raise ToolLoginDisabled("Original API login is not enabled")
        return config

    def _login_runtime(self, config: GlobalToolAuthConfig) -> tuple[Tool, ApiSource]:
        login_tool = self._session.get(Tool, config.login_tool_id)
        if login_tool is None or login_tool.deleted_at is not None:
            raise ToolLoginDisabled("Configured login Tool is unavailable")
        source = self._session.get(ApiSource, login_tool.api_source_id)
        if source is None or source.deleted_at is not None:
            raise ToolLoginDisabled("Configured login API Source is unavailable")
        return login_tool, source

    def _auth_expiry(self, config: GlobalToolAuthConfig, payload: Any) -> datetime | None:
        if not config.expires_json_path:
            return None
        raw = extract_json_path(payload, config.expires_json_path)
        if raw is None:
            return None
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            if raw > 10_000_000_000:
                raw /= 1000
            if raw > 1_000_000_000:
                return datetime.fromtimestamp(raw, UTC).replace(tzinfo=None)
            return self._now() + timedelta(seconds=float(raw))
        if isinstance(raw, str):
            return _naive_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
        return None

    async def _login(self, config: GlobalToolAuthConfig, login_data: Mapping[str, Any]) -> Any:
        login_tool, source = self._login_runtime(config)
        result = await self._executor.execute(login_tool, source, login_data, RequestAuth())
        build_request_auth(config, result.data)
        return result.data

    @staticmethod
    def _owner(context: Any, agent_id: int | None = None) -> tuple[int, int | None, int | None]:
        api_key = getattr(context, "api_key", None)
        if api_key is not None:
            context_agent = getattr(context, "agent", None)
            if context_agent is None:
                raise ToolSessionNotFound("Tool Session owner was not found")
            if agent_id is not None and agent_id != context_agent.id:
                raise ToolSessionNotFound("Tool Session owner was not found")
            return context_agent.id, api_key.id, None
        admin_session = getattr(context, "admin_session", None)
        if admin_session is None or agent_id is None:
            raise ToolSessionNotFound("Tool Session owner was not found")
        return agent_id, None, admin_session.id

    def _new_row(
        self,
        *,
        context: Any,
        agent_id: int | None,
        absolute_expires_at: datetime,
        encrypted_login_data: bytes | None = None,
        encrypted_auth_data: bytes | None = None,
        auth_expires_at: datetime | None = None,
    ) -> tuple[str, ToolUserSession]:
        bound_agent_id, key_id, admin_session_id = self._owner(context, agent_id)
        agent = self._session.get(Agent, bound_agent_id)
        if agent is None or agent.deleted_at is not None or not agent.enabled:
            raise ToolSessionNotFound("Tool Session owner was not found")
        now = self._now()
        token = new_token()
        row = ToolUserSession(
            token_hash=hash_token(token),
            agent_id=bound_agent_id,
            agent_key_id=key_id,
            admin_session_id=admin_session_id,
            status="ready",
            encrypted_login_data=encrypted_login_data,
            encrypted_auth_data=encrypted_auth_data,
            auth_expires_at=auth_expires_at,
            idle_expires_at=min(now + timedelta(minutes=30), absolute_expires_at),
            absolute_expires_at=absolute_expires_at,
            last_used_at=now,
        )
        self._session.add(row)
        self._session.flush()
        return token, row

    async def create(
        self,
        username: str,
        password: str,
        *,
        context: Any,
        agent_id: int | None = None,
    ) -> CreatedToolSession:
        config = self._config()
        login_data = {config.username_field: username, config.password_field: password}
        auth_payload = await self._login(config, login_data)
        now = self._now()
        auth = build_request_auth(config, auth_payload)
        expiry_candidates = [
            expiry
            for expiry in (self._auth_expiry(config, auth_payload), credential_expiry(auth))
            if expiry is not None
        ]
        auth_expires_at = min(expiry_candidates) if expiry_candidates else None
        absolute_expires_at = min(
            [now + timedelta(hours=config.absolute_hours), *expiry_candidates]
        )
        token, row = self._new_row(
            context=context,
            agent_id=agent_id,
            absolute_expires_at=absolute_expires_at,
            encrypted_login_data=self._cipher.encrypt_json(login_data),
            encrypted_auth_data=self._cipher.encrypt_json(auth_payload),
            auth_expires_at=auth_expires_at,
        )
        source_ids = [self._login_runtime(config)[1].id]
        for source_id in source_ids:
            self._session.add(
                ToolSessionCredential(
                    tool_session_id=row.id,
                    api_source_id=source_id,
                    encrypted_credentials=self._cipher.encrypt_json(auth_to_json(auth)),
                    status="ready",
                    expires_at=row.auth_expires_at,
                    last_used_at=now,
                )
            )
        row.idle_expires_at = min(
            now + timedelta(minutes=config.idle_minutes), row.absolute_expires_at
        )
        self._session.commit()
        return CreatedToolSession(
            token,
            row.token_hash,
            row.idle_expires_at,
            row.absolute_expires_at,
            api_source_ids=tuple(source_ids),
        )

    async def create_injected(
        self,
        context: Any,
        credentials_by_source: Mapping[int, Mapping[str, Any]],
        expires_at: datetime | None,
        *,
        agent_id: int | None = None,
    ) -> CreatedToolSession:
        if not credentials_by_source:
            raise ToolSessionNotFound("At least one API Source credential is required")
        now = self._now()
        requested_expiry = _naive_utc(expires_at) or now + timedelta(hours=8)
        normalized: list[tuple[ApiSource, RequestAuth, datetime | None]] = []
        legacy_config = self._session.get(GlobalToolAuthConfig, 1)
        legacy_source_id: int | None = None
        if (
            legacy_config is not None
            and legacy_config.enabled
            and legacy_config.login_tool_id is not None
        ):
            login_tool = self._session.get(Tool, legacy_config.login_tool_id)
            if login_tool is not None and login_tool.deleted_at is None:
                legacy_source_id = login_tool.api_source_id
        for source_id, supplied in credentials_by_source.items():
            source = self._session.get(ApiSource, source_id)
            if (
                source is None
                or source.deleted_at is not None
                or not source.enabled
            ):
                raise ToolSessionNotFound("API Source was not found")
            scoped_legacy_config = legacy_config if source.id == legacy_source_id else None
            auth = validate_and_normalize_credentials(source, supplied, scoped_legacy_config)
            normalized.append((source, auth, credential_expiry(auth)))
        caps = [expiry for _, _, expiry in normalized if expiry is not None]
        absolute_expiry = min([requested_expiry, *caps])
        if absolute_expiry <= now:
            raise ToolSessionExpired("Tool Session credentials have expired")
        token, row = self._new_row(
            context=context,
            agent_id=agent_id,
            absolute_expires_at=absolute_expiry,
        )
        for source, auth, expiry in normalized:
            self._session.add(
                ToolSessionCredential(
                    tool_session_id=row.id,
                    api_source_id=source.id,
                    encrypted_credentials=self._cipher.encrypt_json(auth_to_json(auth)),
                    status="ready",
                    expires_at=min(expiry, absolute_expiry) if expiry is not None else absolute_expiry,
                    last_used_at=now,
                )
            )
        self._session.commit()
        return CreatedToolSession(
            token,
            row.token_hash,
            row.idle_expires_at,
            row.absolute_expires_at,
            api_source_ids=tuple(source.id for source, _, _ in normalized),
        )

    def _find(
        self,
        token: str,
        agent_id: int,
        agent_key_id: int | None,
        admin_session_id: int | None,
    ) -> ToolUserSession:
        row = self._session.scalar(
            select(ToolUserSession).where(
                ToolUserSession.token_hash == hash_token(token),
                ToolUserSession.agent_id == agent_id,
                ToolUserSession.agent_key_id == agent_key_id,
                ToolUserSession.admin_session_id == admin_session_id,
            )
        )
        if row is None or row.revoked_at is not None or row.status == "revoked":
            raise ToolSessionNotFound("Tool Session was not found")
        return row

    def _validate_owner(self, row: ToolUserSession, now: datetime) -> None:
        agent = self._session.get(Agent, row.agent_id)
        if agent is None or agent.deleted_at is not None or not agent.enabled:
            raise ToolSessionNotFound("Tool Session was not found")
        if row.agent_key_id is not None:
            key = self._session.get(AgentApiKey, row.agent_key_id)
            if (
                key is None
                or key.agent_id != row.agent_id
                or key.deleted_at is not None
                or key.revoked_at is not None
                or not key.enabled
                or (key.expires_at is not None and key.expires_at <= now)
            ):
                raise ToolSessionNotFound("Tool Session was not found")
        else:
            admin_session = self._session.get(AdminSession, row.admin_session_id)
            if (
                admin_session is None
                or admin_session.revoked_at is not None
                or admin_session.idle_expires_at <= now
                or admin_session.absolute_expires_at <= now
            ):
                raise ToolSessionNotFound("Tool Session was not found")

    def binding_for_context(
        self, token: str, context: Any, *, agent_id: int | None = None
    ) -> tuple[int, int | None, int | None]:
        api_key = getattr(context, "api_key", None)
        if api_key is not None:
            bound_agent = getattr(context, "agent", None)
            if bound_agent is None or (agent_id is not None and agent_id != bound_agent.id):
                raise ToolSessionNotFound("Tool Session was not found")
            binding = (bound_agent.id, api_key.id, None)
        else:
            admin_session = getattr(context, "admin_session", None)
            if admin_session is None:
                raise ToolSessionNotFound("Tool Session was not found")
            query = select(ToolUserSession.agent_id).where(
                ToolUserSession.token_hash == hash_token(token),
                ToolUserSession.agent_key_id.is_(None),
                ToolUserSession.admin_session_id == admin_session.id,
            )
            if agent_id is not None:
                query = query.where(ToolUserSession.agent_id == agent_id)
            bound_agent_id = self._session.scalar(query)
            if bound_agent_id is None:
                raise ToolSessionNotFound("Tool Session was not found")
            binding = (bound_agent_id, None, admin_session.id)
        row = self._find(token, *binding)
        self._validate_owner(row, self._now())
        return binding

    async def _refresh(self, row: ToolUserSession, config: GlobalToolAuthConfig) -> None:
        if row.encrypted_login_data is None:
            raise ToolSessionReauthorizationRequired("Tool Session requires reauthorization")
        login_data = self._cipher.decrypt_json(row.encrypted_login_data)
        payload = await self._login(config, login_data)
        auth = build_request_auth(config, payload)
        row.encrypted_auth_data = self._cipher.encrypt_json(payload)
        expiry_candidates = [
            expiry
            for expiry in (self._auth_expiry(config, payload), credential_expiry(auth))
            if expiry is not None
        ]
        row.auth_expires_at = min(expiry_candidates) if expiry_candidates else None
        login_source_id = self._login_runtime(config)[1].id
        credentials = self._session.scalars(
            select(ToolSessionCredential).where(
                ToolSessionCredential.tool_session_id == row.id,
                ToolSessionCredential.api_source_id == login_source_id,
            )
        ).all()
        for credential in credentials:
            credential.encrypted_credentials = self._cipher.encrypt_json(auth_to_json(auth))
            credential.expires_at = (
                min(row.auth_expires_at, row.absolute_expires_at)
                if row.auth_expires_at is not None
                else row.absolute_expires_at
            )
            credential.status = "ready"
        self._session.commit()

    def _expire(self, row: ToolUserSession) -> None:
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
        self._session.commit()

    async def resolve(
        self,
        token: str,
        agent_id: int,
        agent_key_id: int | None,
        api_source_id: int,
        *,
        admin_session_id: int | None = None,
        force_refresh: bool = False,
    ) -> ResolvedToolSession:
        if (agent_key_id is None) == (admin_session_id is None):
            raise ToolSessionNotFound("Tool Session was not found")
        row = self._find(token, agent_id, agent_key_id, admin_session_id)
        now = self._now()
        self._validate_owner(row, now)
        source = self._session.get(ApiSource, api_source_id)
        if source is None or source.deleted_at is not None or not source.enabled:
            raise ToolSessionNotFound("Tool Session was not found")
        if row.idle_expires_at <= now or row.absolute_expires_at <= now:
            self._expire(row)
            raise ToolSessionExpired("Tool Session has expired")
        if row.status != "ready":
            raise ToolSessionReauthorizationRequired("Tool Session requires reauthorization")
        credential = self._session.scalar(
            select(ToolSessionCredential).where(
                ToolSessionCredential.tool_session_id == row.id,
                ToolSessionCredential.api_source_id == api_source_id,
            )
        )
        if credential is None:
            raise ToolSessionNotFound("Tool Session was not found")
        if (
            (row.auth_expires_at is not None and row.auth_expires_at <= now)
            or (credential.expires_at is not None and credential.expires_at <= now)
        ):
            if row.encrypted_login_data is None:
                self._expire(row)
                raise ToolSessionExpired("Tool Session credentials have expired")
            force_refresh = True
        if force_refresh:
            await self._refresh(row, self._config())
            self._session.refresh(credential)
        if credential.status != "ready":
            raise ToolSessionReauthorizationRequired("Tool Session requires reauthorization")
        auth = auth_from_json(self._cipher.decrypt_json(credential.encrypted_credentials))
        config = self._session.get(GlobalToolAuthConfig, 1)
        idle_minutes = config.idle_minutes if config is not None else 30
        row.last_used_at = now
        row.idle_expires_at = min(
            now + timedelta(minutes=idle_minutes), row.absolute_expires_at
        )
        credential.last_used_at = now
        self._session.commit()
        return ResolvedToolSession(
            row.id,
            auth,
            row.idle_expires_at,
            row.absolute_expires_at,
            api_source_id=api_source_id,
        )

    async def revoke(
        self,
        token: str,
        agent_id: int,
        agent_key_id: int | None,
        *,
        admin_session_id: int | None = None,
    ) -> None:
        row = self._find(token, agent_id, agent_key_id, admin_session_id)
        now = self._now()
        row.status = "revoked"
        row.revoked_at = now
        row.encrypted_login_data = None
        row.encrypted_auth_data = None
        for credential in self._session.scalars(
            select(ToolSessionCredential).where(
                ToolSessionCredential.tool_session_id == row.id
            )
        ):
            credential.status = "revoked"
            credential.encrypted_credentials = self._cipher.encrypt_json({})
        self._session.commit()

    async def execute(
        self,
        tool: Tool,
        arguments: Mapping[str, Any],
        token: str,
        *,
        agent_id: int,
        agent_key_id: int | None,
        admin_session_id: int | None = None,
    ) -> ToolExecutionResult:
        source = self._session.get(ApiSource, tool.api_source_id)
        if source is None or source.deleted_at is not None or not source.enabled:
            raise ToolExecutionError("source_not_found", "Tool API Source was not found")
        resolved = await self.resolve(
            token,
            agent_id,
            agent_key_id,
            source.id,
            admin_session_id=admin_session_id,
        )
        try:
            return await self._executor.execute(tool, source, arguments, resolved.auth)
        except ToolExecutionError as exc:
            if exc.status_code not in {401, 403}:
                raise
        row = self._session.get(ToolUserSession, resolved.id)
        if row is None or row.encrypted_login_data is None:
            if row is not None:
                row.status = "failed"
                self._session.commit()
            raise ToolSessionReauthorizationRequired("Tool Session requires reauthorization")
        refreshed = await self.resolve(
            token,
            agent_id,
            agent_key_id,
            source.id,
            admin_session_id=admin_session_id,
            force_refresh=True,
        )
        return await self._executor.execute(tool, source, arguments, refreshed.auth)
