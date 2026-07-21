import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Header
from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from chat4openapi.api.errors import ApiError
from chat4openapi.db.session import get_db_session
from chat4openapi.models import Agent, AgentApiKey


@dataclass(frozen=True, slots=True)
class AgentKeyContext:
    agent: Agent
    api_key: AgentApiKey
    db: Session


def generate_agent_key() -> tuple[str, str, str]:
    secret = "c4o_" + secrets.token_urlsafe(32)
    prefix = secret[:12]
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    return secret, prefix, digest


def create_agent_key(
    *,
    agent_id: int,
    label: str,
    expires_at: datetime | None = None,
) -> tuple[AgentApiKey, str]:
    secret, prefix, digest = generate_agent_key()
    return (
        AgentApiKey(
            agent_id=agent_id,
            label=label,
            key_prefix=prefix,
            key_hash=digest,
            expires_at=expires_at,
        ),
        secret,
    )


def require_agent_api_key(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db_session),
) -> AgentKeyContext:
    if authorization is None or not authorization.strip():
        raise ApiError(401, "auth.api_key_required")
    scheme, separator, secret = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not secret.strip():
        raise ApiError(401, "auth.api_key_invalid")
    secret = secret.strip()
    prefix = secret[:12]
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    candidates = db.scalars(
        select(AgentApiKey).where(AgentApiKey.key_prefix == prefix)
    ).all()
    matches = [
        candidate
        for candidate in candidates
        if secrets.compare_digest(candidate.key_hash, digest)
    ]
    api_key = matches[0] if matches else None
    if api_key is None or api_key.deleted_at is not None:
        raise ApiError(401, "auth.api_key_invalid")
    if api_key.revoked_at is not None or not api_key.enabled:
        raise ApiError(401, "auth.api_key_revoked")
    now = datetime.now(UTC).replace(tzinfo=None)
    if api_key.expires_at is not None and api_key.expires_at <= now:
        raise ApiError(401, "auth.api_key_expired")
    agent = db.get(Agent, api_key.agent_id)
    if agent is None or agent.deleted_at is not None or not agent.enabled:
        raise ApiError(403, "auth.agent_unavailable")
    db.execute(
        update(AgentApiKey)
        .where(AgentApiKey.id == api_key.id)
        .values(
            last_used_at=case(
                (AgentApiKey.last_used_at.is_(None), now),
                (AgentApiKey.last_used_at < now, now),
                else_=AgentApiKey.last_used_at,
            )
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.refresh(api_key)
    return AgentKeyContext(agent=agent, api_key=api_key, db=db)
