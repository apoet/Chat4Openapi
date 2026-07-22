from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import select

from chat4openapi.embed.grants import (
    AuthGrantError,
    consume_auth_grant,
    create_auth_grant,
)
from chat4openapi.models import (
    Agent,
    AgentEmbed,
    ApiSource,
    EmbedAuthGrant,
    EmbedSession,
    LlmProvider,
    ToolUserSession,
)
from chat4openapi.security.session_tokens import hash_token


def _seed(session) -> tuple[EmbedSession, EmbedSession, ToolUserSession, ApiSource]:
    provider = LlmProvider(
        name="Provider",
        provider_type="openai",
        base_url="https://llm.example/v1",
        encrypted_api_key=b"secret",
        default_model="test-model",
        enabled=True,
    )
    source = ApiSource(
        name="Protected API",
        source_type="openapi",
        base_url="https://api.example",
        enabled=True,
    )
    session.add_all([provider, source])
    session.flush()
    agent = Agent(
        name="Agent",
        system_prompt="Help.",
        provider_id=provider.id,
        enabled=True,
    )
    session.add(agent)
    session.flush()
    embed = AgentEmbed(agent_id=agent.id, name="Embed", public_id="grant-embed")
    session.add(embed)
    session.flush()
    now = datetime.now()
    owners = [
        EmbedSession(
            public_subject_id=f"owner-{index}",
            embed_id=embed.id,
            agent_id=agent.id,
            parent_origin="https://host.example",
            token_hash=hash_token(f"embed-token-{index}"),
            idle_expires_at=now + timedelta(hours=2),
            absolute_expires_at=now + timedelta(days=1),
        )
        for index in range(2)
    ]
    session.add_all(owners)
    session.flush()
    tool_session = ToolUserSession(
        token_hash=hash_token("tool-token"),
        agent_id=agent.id,
        embed_session_id=owners[0].id,
        status="ready",
        idle_expires_at=now + timedelta(hours=2),
        absolute_expires_at=now + timedelta(days=1),
    )
    session.add(tool_session)
    session.commit()
    return owners[0], owners[1], tool_session, source


def test_grant_is_hashed_single_use_and_owner_bound(db_session_factory) -> None:
    with db_session_factory() as session:
        owner, other, tool_session, source = _seed(session)
        code = create_auth_grant(session, owner.id, tool_session.id, source.id)
        session.commit()
        stored = session.scalar(select(EmbedAuthGrant))
        assert stored is not None
        assert stored.code_hash == hash_token(code)
        assert code not in stored.code_hash

        with pytest.raises(AuthGrantError, match="invalid_or_expired"):
            consume_auth_grant(session, code, other.id)
        grant = consume_auth_grant(session, code, owner.id)
        session.commit()

        assert grant.tool_session_id == tool_session.id
        assert grant.api_source_id == source.id
        with pytest.raises(AuthGrantError, match="invalid_or_expired"):
            consume_auth_grant(session, code, owner.id)


def test_grant_expiry_is_capped_by_embed_session(db_session_factory) -> None:
    with db_session_factory() as session:
        owner, _other, tool_session, source = _seed(session)
        owner.absolute_expires_at = datetime.now() + timedelta(seconds=30)
        code = create_auth_grant(session, owner.id, tool_session.id, source.id)
        session.commit()
        stored = session.scalar(select(EmbedAuthGrant))
        assert stored is not None
        assert stored.expires_at <= owner.absolute_expires_at
        stored.expires_at = datetime.now() - timedelta(days=1)
        session.commit()
        session.expire_all()
        expired = session.scalar(select(EmbedAuthGrant))
        assert expired is not None
        assert expired.expires_at < datetime.now()

        with pytest.raises(AuthGrantError, match="invalid_or_expired"):
            consume_auth_grant(session, code, owner.id)


def test_only_one_concurrent_grant_consumer_succeeds(db_session_factory) -> None:
    with db_session_factory() as session:
        owner, _other, tool_session, source = _seed(session)
        code = create_auth_grant(session, owner.id, tool_session.id, source.id)
        owner_id = owner.id
        session.commit()

    barrier = Barrier(2)

    def consume() -> str:
        with db_session_factory() as session:
            barrier.wait()
            try:
                consume_auth_grant(session, code, owner_id)
                session.commit()
                return "consumed"
            except AuthGrantError:
                session.rollback()
                return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: consume(), range(2)))

    assert sorted(outcomes) == ["consumed", "rejected"]
