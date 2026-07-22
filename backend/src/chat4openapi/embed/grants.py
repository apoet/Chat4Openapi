from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from chat4openapi.models import EmbedAuthGrant, EmbedSession, ToolUserSession
from chat4openapi.security.session_tokens import hash_token, new_token

GRANT_LIFETIME = timedelta(minutes=5)


class AuthGrantError(ValueError):
    pass


def create_auth_grant(
    db: Session,
    embed_session_id: int,
    tool_session_id: int,
    api_source_id: int,
) -> str:
    owner = db.get(EmbedSession, embed_session_id)
    tool_session = db.get(ToolUserSession, tool_session_id)
    if (
        owner is None
        or tool_session is None
        or tool_session.embed_session_id != owner.id
        or tool_session.agent_id != owner.agent_id
    ):
        raise AuthGrantError("invalid_owner")
    now = datetime.now(UTC).replace(tzinfo=None)
    if owner.revoked_at is not None or owner.absolute_expires_at <= now:
        raise AuthGrantError("invalid_owner")
    code = new_token()
    db.add(
        EmbedAuthGrant(
            code_hash=hash_token(code),
            embed_session_id=owner.id,
            tool_session_id=tool_session.id,
            api_source_id=api_source_id,
            expires_at=min(now + GRANT_LIFETIME, owner.absolute_expires_at),
        )
    )
    db.flush()
    return code


def consume_auth_grant(
    db: Session,
    code: str,
    embed_session_id: int,
) -> EmbedAuthGrant:
    now = datetime.now(UTC).replace(tzinfo=None)
    grant_id = db.execute(
        update(EmbedAuthGrant)
        .where(
            EmbedAuthGrant.code_hash == hash_token(code),
            EmbedAuthGrant.embed_session_id == embed_session_id,
            EmbedAuthGrant.consumed_at.is_(None),
            EmbedAuthGrant.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(EmbedAuthGrant.id)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    if grant_id is None:
        raise AuthGrantError("invalid_or_expired")
    return db.get_one(EmbedAuthGrant, grant_id)
