import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.models import (
    AdminUser,
    AutoAgentifyJob,
    AutoAgentifyJobEvent,
    LlmProvider,
)

ADMIN = {"username": "admin", "password": "StrongPass!123", "locale": "en-US"}


async def _login(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/setup", json=ADMIN)).status_code == 201
    assert (
        await client.post(
            "/api/admin/auth/login",
            json={"username": ADMIN["username"], "password": ADMIN["password"]},
        )
    ).status_code == 200


@pytest.mark.asyncio
async def test_sse_replays_events_after_last_event_id_and_closes_terminal_job(
    client: httpx.AsyncClient,
    app: FastAPI,
    db_session_factory: sessionmaker[Session],
) -> None:
    await _login(client)
    with db_session_factory() as db:
        owner_id = db.scalar(select(AdminUser.id))
        provider = LlmProvider(
            name="Provider",
            provider_type="openai",
            base_url="https://llm.example.test/v1",
            encrypted_api_key=b"secret",
            default_model="gpt-test",
            enabled=True,
        )
        db.add(provider)
        db.flush()
        job = AutoAgentifyJob(
            public_id="job-sse",
            creator_admin_id=owner_id,
            provider_id=provider.id,
            input_mode="url",
            source_name="Pets",
            source_url="https://api.example.test/openapi.json",
            status="completed",
            phase="completed",
            progress=100,
            metrics={},
            result={"imported_tool_count": 1},
        )
        db.add(job)
        db.flush()
        for sequence, kind in ((1, "queued"), (2, "completed")):
            db.add(
                AutoAgentifyJobEvent(
                    job_id=job.id,
                    sequence=sequence,
                    kind=kind,
                    phase=kind,
                    progress=0 if sequence == 1 else 100,
                    message_key=f"autoAgentify.events.{kind}",
                    params={},
                )
            )
        db.commit()

    response = await client.get(
        "/api/admin/auto-agentify/jobs/job-sse/events",
        headers={"Last-Event-ID": "1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 2" in response.text
    assert '"kind":"completed"' in response.text
    assert "id: 1" not in response.text
