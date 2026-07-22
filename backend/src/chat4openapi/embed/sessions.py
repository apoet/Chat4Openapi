import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from chat4openapi.models import (
    Agent,
    AgentEmbed,
    AgentSkill,
    EmbedSession,
    LlmProvider,
    Skill,
)
from chat4openapi.security.session_tokens import hash_token, new_token

IDLE_HOURS = 2
ABSOLUTE_DAYS = 7


class EmbedUnavailableError(Exception):
    pass


def available_embed(db: Session, public_id: str) -> tuple[AgentEmbed, Agent]:
    embed = db.scalar(
        select(AgentEmbed).where(
            AgentEmbed.public_id == public_id,
            AgentEmbed.enabled.is_(True),
            AgentEmbed.deleted_at.is_(None),
        )
    )
    if embed is None:
        raise EmbedUnavailableError
    agent = db.get(Agent, embed.agent_id)
    if agent is None or not agent.enabled or agent.deleted_at is not None:
        raise EmbedUnavailableError
    provider = db.get(LlmProvider, agent.provider_id) if agent.provider_id is not None else None
    if provider is None or not provider.enabled or provider.deleted_at is not None:
        raise EmbedUnavailableError
    running_skill = db.scalar(
        select(AgentSkill.skill_id)
        .join(Skill, Skill.id == AgentSkill.skill_id)
        .where(
            AgentSkill.agent_id == agent.id,
            Skill.running.is_(True),
            Skill.deleted_at.is_(None),
        )
        .limit(1)
    )
    if running_skill is None:
        raise EmbedUnavailableError
    return embed, agent


def issue_embed_session(
    db: Session,
    embed: AgentEmbed,
    parent_origin: str,
) -> tuple[EmbedSession, str]:
    token = new_token()
    now = datetime.now(UTC).replace(tzinfo=None)
    session = EmbedSession(
        public_subject_id=str(uuid.uuid4()),
        embed_id=embed.id,
        agent_id=embed.agent_id,
        parent_origin=parent_origin,
        token_hash=hash_token(token),
        idle_expires_at=now + timedelta(hours=IDLE_HOURS),
        absolute_expires_at=now + timedelta(days=ABSOLUTE_DAYS),
        last_seen_at=now,
    )
    db.add(session)
    db.flush()
    return session, token


def authenticate_embed_session(
    db: Session,
    token: str,
    *,
    session_id: str | None = None,
    public_id: str | None = None,
) -> EmbedSession:
    session = db.scalar(
        select(EmbedSession).where(EmbedSession.token_hash == hash_token(token))
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    if (
        session is None
        or session.revoked_at is not None
        or (session_id is not None and session.public_subject_id != session_id)
    ):
        raise EmbedUnavailableError
    embed, agent = available_embed(db, public_id or _embed_public_id(db, session.embed_id))
    if embed.id != session.embed_id or agent.id != session.agent_id:
        raise EmbedUnavailableError
    if session.idle_expires_at <= now or session.absolute_expires_at <= now:
        session.revoked_at = now
        db.commit()
        raise EmbedUnavailableError
    session.last_seen_at = now
    session.idle_expires_at = min(
        now + timedelta(hours=IDLE_HOURS), session.absolute_expires_at
    )
    db.commit()
    return session


def _embed_public_id(db: Session, embed_id: int) -> str:
    public_id = db.scalar(select(AgentEmbed.public_id).where(AgentEmbed.id == embed_id))
    if public_id is None:
        raise EmbedUnavailableError
    return public_id
