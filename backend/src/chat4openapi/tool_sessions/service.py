from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from chat4openapi.models import ApiSource, GlobalToolAuthConfig, Tool, ToolUserSession
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.security.session_tokens import hash_token, new_token
from chat4openapi.tool_sessions.auth_mapping import build_request_auth, extract_json_path
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


@dataclass(frozen=True, slots=True)
class CreatedToolSession:
    token: str
    token_hash: str
    idle_expires_at: datetime
    absolute_expires_at: datetime


@dataclass(frozen=True, slots=True)
class ResolvedToolSession:
    id: int
    auth: RequestAuth
    idle_expires_at: datetime
    absolute_expires_at: datetime


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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

    def _login_runtime(
        self, config: GlobalToolAuthConfig
    ) -> tuple[Tool, ApiSource]:
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
        if isinstance(raw, (int, float)):
            if raw > 10_000_000_000:
                raw /= 1000
            if raw > 1_000_000_000:
                return datetime.fromtimestamp(raw, UTC).replace(tzinfo=None)
            return self._now() + timedelta(seconds=float(raw))
        if isinstance(raw, str):
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed
            return parsed.astimezone(UTC).replace(tzinfo=None)
        return None

    async def _login(self, config: GlobalToolAuthConfig, login_data: Mapping[str, Any]) -> Any:
        login_tool, source = self._login_runtime(config)
        result = await self._executor.execute(login_tool, source, login_data, RequestAuth())
        build_request_auth(config, result.data)
        return result.data

    async def create(self, username: str, password: str) -> CreatedToolSession:
        config = self._config()
        login_data = {
            config.username_field: username,
            config.password_field: password,
        }
        auth_payload = await self._login(config, login_data)
        now = self._now()
        token = new_token()
        token_hash = hash_token(token)
        row = ToolUserSession(
            token_hash=token_hash,
            encrypted_login_data=self._cipher.encrypt_json(login_data),
            encrypted_auth_data=self._cipher.encrypt_json(auth_payload),
            auth_expires_at=self._auth_expiry(config, auth_payload),
            idle_expires_at=now + timedelta(minutes=config.idle_minutes),
            absolute_expires_at=now + timedelta(hours=config.absolute_hours),
            last_used_at=now,
        )
        self._session.add(row)
        self._session.commit()
        return CreatedToolSession(token, token_hash, row.idle_expires_at, row.absolute_expires_at)

    def _find(self, token: str) -> ToolUserSession:
        row = self._session.scalar(
            select(ToolUserSession).where(ToolUserSession.token_hash == hash_token(token))
        )
        if row is None or row.revoked_at is not None:
            raise ToolSessionNotFound("Tool Session was not found")
        return row

    async def _refresh(
        self, row: ToolUserSession, config: GlobalToolAuthConfig
    ) -> RequestAuth:
        login_data = self._cipher.decrypt_json(row.encrypted_login_data)
        payload = await self._login(config, login_data)
        row.encrypted_auth_data = self._cipher.encrypt_json(payload)
        row.auth_expires_at = self._auth_expiry(config, payload)
        self._session.commit()
        return build_request_auth(config, payload)

    async def resolve(self, token: str, *, force_refresh: bool = False) -> ResolvedToolSession:
        row = self._find(token)
        now = self._now()
        if row.idle_expires_at <= now or row.absolute_expires_at <= now:
            self._session.delete(row)
            self._session.commit()
            raise ToolSessionExpired("Tool Session has expired")
        config = self._config()
        if force_refresh or (row.auth_expires_at is not None and row.auth_expires_at <= now):
            auth = await self._refresh(row, config)
        else:
            payload = self._cipher.decrypt_json(row.encrypted_auth_data)
            auth = build_request_auth(config, payload)
        row.last_used_at = now
        row.idle_expires_at = min(
            now + timedelta(minutes=config.idle_minutes), row.absolute_expires_at
        )
        self._session.commit()
        return ResolvedToolSession(row.id, auth, row.idle_expires_at, row.absolute_expires_at)

    async def revoke(self, token: str) -> None:
        row = self._find(token)
        self._session.delete(row)
        self._session.commit()

    async def execute(
        self,
        tool: Tool,
        arguments: Mapping[str, Any],
        token: str,
    ) -> ToolExecutionResult:
        source = self._session.get(ApiSource, tool.api_source_id)
        if source is None:
            raise ToolExecutionError("source_not_found", "Tool API Source was not found")
        resolved = await self.resolve(token)
        try:
            return await self._executor.execute(tool, source, arguments, resolved.auth)
        except ToolExecutionError as exc:
            if exc.status_code not in {401, 403}:
                raise
        refreshed = await self.resolve(token, force_refresh=True)
        return await self._executor.execute(tool, source, arguments, refreshed.auth)
