from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.api import admin_agents, admin_providers
from chat4openapi.api.admin_auth import AdminContext
from chat4openapi.api.errors import ApiError
from chat4openapi.models import Agent, AgentSkill, LlmProvider, Skill
from chat4openapi.schemas.agents import AgentWrite
from chat4openapi.schemas.providers import ProviderUpdateRequest
from chat4openapi.security.encryption import SecretCipher


def context(session: Session) -> AdminContext:
    return AdminContext(admin=None, admin_session=None, db=session)  # type: ignore[arg-type]


def seed_default_race(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        provider = LlmProvider(
            name="Race provider",
            provider_type="openai",
            base_url="https://race.test/v1",
            encrypted_api_key=b"secret",
            default_model="race-model",
            enabled=True,
        )
        skill = Skill(name="Race skill", system_prompt="Race", running=True)
        session.add_all([provider, skill])
        session.flush()
        session.add_all(
            [
                Agent(
                    id=1,
                    name="Old default",
                    enabled=True,
                    is_default=True,
                    system_prompt="Old",
                    provider_id=provider.id,
                ),
                Agent(
                    id=2,
                    name="New default",
                    enabled=True,
                    is_default=False,
                    system_prompt="New",
                    provider_id=provider.id,
                ),
                AgentSkill(agent_id=2, skill_id=skill.id, position=0),
            ]
        )
        session.commit()


def seed_provider_race(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        default_provider = LlmProvider(
            name="Default provider",
            provider_type="openai",
            base_url="https://default.test/v1",
            encrypted_api_key=b"secret",
            default_model="default-model",
            enabled=True,
        )
        target_provider = LlmProvider(
            name="Target provider",
            provider_type="openai",
            base_url="https://target.test/v1",
            encrypted_api_key=b"secret",
            default_model="target-model",
            enabled=True,
        )
        session.add_all([default_provider, target_provider])
        session.flush()
        session.add_all(
            [
                Agent(
                    id=1,
                    name="Default",
                    enabled=True,
                    is_default=True,
                    system_prompt="Default",
                    provider_id=default_provider.id,
                ),
                Agent(
                    id=2,
                    name="Rebind",
                    enabled=False,
                    is_default=False,
                    system_prompt="Rebind",
                    provider_id=None,
                ),
            ]
        )
        session.commit()
        return target_provider.id


@pytest.mark.parametrize(
    ("operation", "expected_code"),
    [
        ("disable", "agents.default_cannot_disable"),
        ("delete", "agents.default_cannot_delete"),
        ("update", "agents.default_cannot_disable"),
    ],
)
def test_default_switch_serializes_competing_agent_mutations(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    expected_code: str,
) -> None:
    seed_default_race(db_session_factory)
    default_locked = Event()
    release_default = Event()
    mutation_started = Event()
    original_validate = admin_agents._validate_enable

    def pause_after_default_validation(context: AdminContext, agent: Agent) -> None:
        original_validate(context, agent)
        default_locked.set()
        assert release_default.wait(5)

    monkeypatch.setattr(admin_agents, "_validate_enable", pause_after_default_validation)

    def switch_default() -> None:
        with db_session_factory() as session:
            admin_agents.set_default_agent(2, context(session))

    def mutate_target() -> str | None:
        with db_session_factory() as session:
            stale_agent = session.get(Agent, 2)
            session.commit()
            assert default_locked.wait(5)
            mutation_started.set()
            try:
                if operation == "disable":
                    admin_agents.disable_agent(2, context(session))
                elif operation == "delete":
                    admin_agents.delete_agent(2, context(session))
                else:
                    admin_agents.update_agent(
                        2,
                        AgentWrite(
                            name=stale_agent.name,
                            enabled=False,
                            system_prompt=stale_agent.system_prompt,
                            provider_id=stale_agent.provider_id,
                        ),
                        context(session),
                    )
            except ApiError as exc:
                return exc.code
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        switched = executor.submit(switch_default)
        assert default_locked.wait(5)
        mutated = executor.submit(mutate_target)
        assert mutation_started.wait(5)
        release_default.set()
        switched.result(timeout=5)
        mutation_error = mutated.result(timeout=5)

    assert mutation_error == expected_code
    with db_session_factory() as session:
        defaults = session.scalars(
            select(Agent).where(Agent.deleted_at.is_(None), Agent.is_default.is_(True))
        ).all()
        assert [(agent.id, agent.enabled) for agent in defaults] == [(2, True)]


@pytest.mark.parametrize("provider_operation", ["disable", "delete"])
@pytest.mark.parametrize("agent_operation", ["create", "rebind"])
def test_provider_removal_serializes_with_agent_provider_binding(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    provider_operation: str,
    agent_operation: str,
) -> None:
    provider_id = seed_provider_race(db_session_factory)
    provider_checked = Event()
    release_provider = Event()
    agent_started = Event()
    original_check = admin_providers._ensure_not_agent_provider

    def pause_after_reference_check(context: AdminContext, checked_id: int) -> None:
        original_check(context, checked_id)
        provider_checked.set()
        assert release_provider.wait(5)

    monkeypatch.setattr(
        admin_providers, "_ensure_not_agent_provider", pause_after_reference_check
    )

    def remove_provider() -> None:
        with db_session_factory() as session:
            if provider_operation == "disable":
                admin_providers.update_provider(
                    provider_id,
                    ProviderUpdateRequest(enabled=False),
                    context(session),
                    SecretCipher(Fernet.generate_key()),
                )
            else:
                admin_providers.delete_provider(provider_id, context(session))

    def bind_provider() -> str | None:
        with db_session_factory() as session:
            assert provider_checked.wait(5)
            agent_started.set()
            payload = AgentWrite(
                name="Concurrent binding",
                enabled=False,
                system_prompt="Concurrent",
                provider_id=provider_id,
            )
            try:
                if agent_operation == "create":
                    admin_agents.create_agent(payload, context(session))
                else:
                    admin_agents.update_agent(2, payload, context(session))
            except ApiError as exc:
                return exc.code
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        removed = executor.submit(remove_provider)
        assert provider_checked.wait(5)
        bound = executor.submit(bind_provider)
        assert agent_started.wait(5)
        release_provider.set()
        removed.result(timeout=5)
        binding_error = bound.result(timeout=5)

    assert binding_error == "agents.provider_unavailable"
    with db_session_factory() as session:
        provider = session.get(LlmProvider, provider_id)
        assert provider is not None
        assert provider.enabled is False
        if provider_operation == "delete":
            assert provider.deleted_at is not None
        references = session.scalars(
            select(Agent.id).where(
                Agent.provider_id == provider_id,
                Agent.deleted_at.is_(None),
            )
        ).all()
        assert references == []


@pytest.mark.parametrize("failure_stage", ["body", "commit"])
def test_default_switch_failure_rolls_back_the_previous_default(
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    seed_default_race(db_session_factory)
    with db_session_factory() as session:
        if failure_stage == "body":
            original_execute = session.execute

            def fail_after_default_clear(*args: object, **kwargs: object):
                original_execute(*args, **kwargs)
                raise RuntimeError("default update failed")

            monkeypatch.setattr(session, "execute", fail_after_default_clear)
        else:

            def fail_commit() -> None:
                session.flush()
                raise RuntimeError("commit failed")

            monkeypatch.setattr(session, "commit", fail_commit)

        with pytest.raises(RuntimeError):
            admin_agents.set_default_agent(2, context(session))

    with db_session_factory() as session:
        agents = session.scalars(select(Agent).order_by(Agent.id)).all()
        assert [
            (agent.id, agent.enabled, agent.is_default, agent.deleted_at)
            for agent in agents
        ] == [
            (1, True, True, None),
            (2, True, False, None),
        ]
