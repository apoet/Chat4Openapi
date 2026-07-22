from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.models import (
    Agent,
    AgentEmbed,
    BrowserChatSession,
    Conversation,
    EmbedAuthGrant,
    EmbedSession,
    ToolUserSession,
)


def _agent(db: Session) -> Agent:
    agent = Agent(name="Embedded Agent", system_prompt="Help the visitor.")
    db.add(agent)
    db.flush()
    return agent


def _embed_session(db: Session, agent: Agent) -> EmbedSession:
    embed = AgentEmbed(
        agent_id=agent.id,
        name="Documentation",
        public_id="embed-public-id",
        allowed_origins=["https://docs.example"],
    )
    db.add(embed)
    db.flush()
    now = datetime.now(UTC).replace(tzinfo=None)
    session = EmbedSession(
        embed_id=embed.id,
        agent_id=agent.id,
        public_subject_id="embed-subject-id",
        parent_origin="https://docs.example",
        token_hash="e" * 64,
        idle_expires_at=now + timedelta(hours=2),
        absolute_expires_at=now + timedelta(days=7),
    )
    db.add(session)
    db.flush()
    return session


def test_embed_session_can_own_conversation_and_tool_session(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        agent = _agent(db)
        embed_session = _embed_session(db, agent)
        conversation = Conversation(agent_id=agent.id, embed_session_id=embed_session.id)
        tool_session = ToolUserSession(
            token_hash="t" * 64,
            agent_id=agent.id,
            embed_session_id=embed_session.id,
            idle_expires_at=embed_session.idle_expires_at,
            absolute_expires_at=embed_session.absolute_expires_at,
        )
        db.add_all([conversation, tool_session])
        db.commit()

        assert conversation.embed_session_id == embed_session.id
        assert tool_session.embed_session_id == embed_session.id


def test_conversation_rejects_multiple_active_owners(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as db:
        agent = _agent(db)
        embed_session = _embed_session(db, agent)
        browser_session = BrowserChatSession(
            token_hash="b" * 64,
            public_subject_id="browser-subject-id",
            expires_at=embed_session.absolute_expires_at,
        )
        db.add(browser_session)
        db.flush()
        db.add(
            Conversation(
                agent_id=agent.id,
                embed_session_id=embed_session.id,
                browser_chat_session_id=browser_session.id,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_embed_auth_grant_has_bound_session_tool_and_source_columns() -> None:
    assert {
        "code_hash",
        "embed_session_id",
        "tool_session_id",
        "api_source_id",
        "expires_at",
        "consumed_at",
    } <= set(EmbedAuthGrant.__table__.columns.keys())
