from datetime import UTC, datetime

import pytest
import httpx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.models import AdminUser, LlmProvider
from chat4openapi.models.auto_agentify_job import (
    AutoAgentifyJob,
    AutoAgentifyJobEvent,
)
from chat4openapi.auto_agentify.progress import (
    JobProgressReporter,
    ProgressEvent,
    mark_interrupted_jobs,
)
from chat4openapi.api.admin_auto_agentify import get_auto_agentify_planner
from chat4openapi.api.tool_sessions import get_tool_secret_cipher
from chat4openapi.security.encryption import SecretCipher
from cryptography.fernet import Fernet

ADMIN = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}


async def _login(client: httpx.AsyncClient) -> str:
    assert (await client.post("/api/setup", json=ADMIN)).status_code == 201
    response = await client.post(
        "/api/admin/auth/login",
        json={"username": ADMIN["username"], "password": ADMIN["password"]},
    )
    return response.json()["csrf_token"]


def _seed_owner_and_provider(
    factory: sessionmaker[Session],
) -> tuple[int, int]:
    with factory() as session:
        owner = AdminUser(
            username="job-owner",
            password_hash="hash",
            role="user",
            locale="en-US",
            enabled=True,
        )
        provider = LlmProvider(
            name="Job Provider",
            provider_type="openai",
            base_url="https://llm.example.test/v1",
            encrypted_api_key=b"secret",
            default_model="gpt-test",
            enabled=True,
        )
        session.add_all([owner, provider])
        session.commit()
        return owner.id, provider.id


def _job(owner_id: int, provider_id: int, *, status: str = "queued") -> AutoAgentifyJob:
    return AutoAgentifyJob(
        public_id=f"job-{status}-{datetime.now(UTC).timestamp()}",
        creator_admin_id=owner_id,
        provider_id=provider_id,
        input_mode="url",
        source_name="Projects",
        source_url="https://api.example.test/openapi.json",
        status=status,
        phase="queued",
        progress=0,
        metrics={},
    )


def test_job_enforces_one_active_job_per_creator(
    db_session_factory: sessionmaker[Session],
) -> None:
    owner_id, provider_id = _seed_owner_and_provider(db_session_factory)
    with db_session_factory() as session:
        session.add_all(
            [
                _job(owner_id, provider_id, status="queued"),
                _job(owner_id, provider_id, status="running"),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_job_allows_multiple_terminal_jobs_and_orders_event_sequences_per_job(
    db_session_factory: sessionmaker[Session],
) -> None:
    owner_id, provider_id = _seed_owner_and_provider(db_session_factory)
    with db_session_factory() as session:
        first = _job(owner_id, provider_id, status="completed")
        second = _job(owner_id, provider_id, status="failed")
        session.add_all([first, second])
        session.flush()
        session.add_all(
            [
                AutoAgentifyJobEvent(
                    job_id=first.id,
                    sequence=1,
                    kind="queued",
                    phase="queued",
                    progress=0,
                    message_key="autoAgentify.events.queued",
                    params={},
                ),
                AutoAgentifyJobEvent(
                    job_id=second.id,
                    sequence=1,
                    kind="failed",
                    phase="failed",
                    progress=40,
                    message_key="autoAgentify.events.failed",
                    params={},
                ),
            ]
        )
        session.commit()

        assert session.scalars(
            select(AutoAgentifyJobEvent).order_by(AutoAgentifyJobEvent.job_id)
        ).all()[0].sequence == 1


def test_job_rejects_duplicate_event_sequence(
    db_session_factory: sessionmaker[Session],
) -> None:
    owner_id, provider_id = _seed_owner_and_provider(db_session_factory)
    with db_session_factory() as session:
        job = _job(owner_id, provider_id, status="completed")
        session.add(job)
        session.flush()
        session.add_all(
            [
                AutoAgentifyJobEvent(
                    job_id=job.id,
                    sequence=1,
                    kind="one",
                    phase="queued",
                    progress=0,
                    message_key="autoAgentify.events.one",
                    params={},
                ),
                AutoAgentifyJobEvent(
                    job_id=job.id,
                    sequence=1,
                    kind="two",
                    phase="queued",
                    progress=0,
                    message_key="autoAgentify.events.two",
                    params={},
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.asyncio
async def test_reporter_persists_monotonic_progress_and_metrics(
    db_session_factory: sessionmaker[Session],
) -> None:
    owner_id, provider_id = _seed_owner_and_provider(db_session_factory)
    with db_session_factory() as session:
        job = _job(owner_id, provider_id)
        session.add(job)
        session.commit()
        reporter = JobProgressReporter(session, job.id)

        await reporter.emit(
            ProgressEvent(
                kind="operations_discovered",
                phase="cataloging_operations",
                progress=20,
                message_key="autoAgentify.events.operationsDiscovered",
                params={"count": 8},
                metrics={"operation_count": 8},
            )
        )

        saved_job = session.get(AutoAgentifyJob, job.id)
        event = session.scalar(select(AutoAgentifyJobEvent))
        assert saved_job is not None
        assert saved_job.progress == 20
        assert saved_job.metrics == {"operation_count": 8}
        assert event is not None and event.sequence == 1

        with pytest.raises(ValueError, match="progress cannot decrease"):
            await reporter.emit(
                ProgressEvent(
                    kind="invalid",
                    phase="parsing_openapi",
                    progress=10,
                    message_key="autoAgentify.events.invalid",
                    params={},
                )
            )


def test_interruption_recovery_marks_active_jobs_failed(
    db_session_factory: sessionmaker[Session],
) -> None:
    owner_id, provider_id = _seed_owner_and_provider(db_session_factory)
    with db_session_factory() as session:
        job = _job(owner_id, provider_id, status="running")
        job.phase = "analyzing_capabilities"
        job.progress = 42
        session.add(job)
        session.commit()

        assert mark_interrupted_jobs(session) == 1

        session.refresh(job)
        assert job.status == "failed"
        assert job.phase == "failed"
        assert job.error_code == "auto_agentify.interrupted"
        assert job.completed_at is not None
        event = session.scalar(select(AutoAgentifyJobEvent))
        assert event is not None
        assert event.kind == "failed"
        assert event.progress == 42


@pytest.mark.asyncio
async def test_job_api_creates_and_recovers_latest_job(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = await _login(client)
    cipher = SecretCipher(Fernet.generate_key())
    provider_id = _seed_owner_and_provider(db_session_factory)[1]
    app.dependency_overrides[get_tool_secret_cipher] = lambda: cipher
    app.dependency_overrides[get_auto_agentify_planner] = lambda: object()
    scheduled: list[dict] = []
    monkeypatch.setattr(
        "chat4openapi.api.admin_auto_agentify.schedule_auto_agentify_job",
        lambda **kwargs: scheduled.append(kwargs),
    )

    first = await client.post(
        "/api/admin/auto-agentify/jobs/url",
        json={
            "provider_id": provider_id,
            "name": "Projects",
            "url": "https://api.example.test/openapi.json",
            "allowed_system_capabilities": ["file_management"],
            "custom_capability_labels": ["clinical trial data capture"],
        },
        headers={"X-CSRF-Token": token},
    )
    second = await client.post(
        "/api/admin/auto-agentify/jobs/url",
        json={
            "provider_id": provider_id,
            "name": "Ignored duplicate",
            "url": "https://api.example.test/other.json",
        },
        headers={"X-CSRF-Token": token},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["public_id"] == first.json()["public_id"]
    assert scheduled[0]["allowed_system_capabilities"] == ["file_management"]
    assert scheduled[0]["custom_capability_labels"] == [
        "clinical trial data capture"
    ]
    latest = await client.get("/api/admin/auto-agentify/jobs/latest")
    assert latest.status_code == 200
    assert latest.json()["public_id"] == first.json()["public_id"]
    assert latest.json()["metrics"]["allowed_system_capabilities"] == [
        "file_management"
    ]
    assert latest.json()["metrics"]["custom_capability_labels"] == [
        "clinical trial data capture"
    ]
