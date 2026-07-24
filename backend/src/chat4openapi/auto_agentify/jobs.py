import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from chat4openapi.api.admin_tools import _fetch_openapi_document
from chat4openapi.api.errors import ApiError
from chat4openapi.auto_agentify.planner import AutoAgentifyPlanner
from chat4openapi.auto_agentify.progress import JobProgressReporter, ProgressEvent
from chat4openapi.auto_agentify.service import AutoAgentifyService
from chat4openapi.models import AutoAgentifyJob, AutoAgentifyJobEvent, LlmProvider
from chat4openapi.schemas.auto_agentify import (
    AutoAgentifyJobEventResponse,
    AutoAgentifyJobResponse,
)
from chat4openapi.security.encryption import SecretCipher

_tasks: set[asyncio.Task[None]] = set()


def session_factory_for(db: Session) -> sessionmaker[Session]:
    return sessionmaker(bind=db.get_bind(), expire_on_commit=False)


def job_response(job: AutoAgentifyJob) -> AutoAgentifyJobResponse:
    return AutoAgentifyJobResponse(
        public_id=job.public_id,
        provider_id=job.provider_id,
        input_mode=job.input_mode,
        source_name=job.source_name,
        status=job.status,
        phase=job.phase,
        progress=job.progress,
        metrics=job.metrics or {},
        result=job.result,
        error_code=job.error_code,
        error_params=job.error_params,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


def event_response(event: AutoAgentifyJobEvent) -> AutoAgentifyJobEventResponse:
    return AutoAgentifyJobEventResponse(
        sequence=event.sequence,
        kind=event.kind,
        phase=event.phase,
        progress=event.progress,
        message_key=event.message_key,
        params=event.params or {},
        capability=event.capability,
        created_at=event.created_at,
    )


def owned_job(db: Session, creator_id: int, public_id: str) -> AutoAgentifyJob:
    job = db.scalar(
        select(AutoAgentifyJob).where(
            AutoAgentifyJob.public_id == public_id,
            AutoAgentifyJob.creator_admin_id == creator_id,
        )
    )
    if job is None:
        raise ApiError(404, "auto_agentify.job_not_found")
    return job


def latest_job(db: Session, creator_id: int) -> AutoAgentifyJob | None:
    return db.scalar(
        select(AutoAgentifyJob)
        .where(AutoAgentifyJob.creator_admin_id == creator_id)
        .order_by(AutoAgentifyJob.created_at.desc(), AutoAgentifyJob.id.desc())
        .limit(1)
    )


def create_job(
    db: Session,
    *,
    creator_id: int,
    provider_id: int,
    input_mode: str,
    source_name: str,
    source_url: str | None = None,
    file_name: str | None = None,
    base_url: str | None = None,
    allow_private_networks: bool = False,
) -> tuple[AutoAgentifyJob, bool]:
    active = db.scalar(
        select(AutoAgentifyJob).where(
            AutoAgentifyJob.creator_admin_id == creator_id,
            AutoAgentifyJob.status.in_(("queued", "running")),
        )
    )
    if active is not None:
        return active, False
    provider = db.get(LlmProvider, provider_id)
    if provider is None or not provider.enabled:
        raise ApiError(404, "providers.not_found")
    job = AutoAgentifyJob(
        public_id=uuid4().hex,
        creator_admin_id=creator_id,
        provider_id=provider_id,
        input_mode=input_mode,
        source_name=source_name,
        source_url=source_url,
        file_name=file_name,
        base_url=base_url,
        allow_private_networks=allow_private_networks,
        status="queued",
        phase="queued",
        progress=0,
        metrics={},
    )
    db.add(job)
    try:
        db.flush()
        db.add(
            AutoAgentifyJobEvent(
                job_id=job.id,
                sequence=1,
                kind="queued",
                phase="queued",
                progress=0,
                message_key="autoAgentify.events.queued",
                params={},
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        active = db.scalar(
            select(AutoAgentifyJob).where(
                AutoAgentifyJob.creator_admin_id == creator_id,
                AutoAgentifyJob.status.in_(("queued", "running")),
            )
        )
        if active is None:
            raise
        return active, False
    return job, True


def schedule_auto_agentify_job(
    *,
    factory: sessionmaker[Session],
    job_id: int,
    raw_document: bytes | None,
    planner: AutoAgentifyPlanner,
    cipher: SecretCipher,
) -> None:
    task = asyncio.create_task(
        _run_job(
            factory=factory,
            job_id=job_id,
            raw_document=raw_document,
            planner=planner,
            cipher=cipher,
        )
    )
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run_job(
    *,
    factory: sessionmaker[Session],
    job_id: int,
    raw_document: bytes | None,
    planner: AutoAgentifyPlanner,
    cipher: SecretCipher,
) -> None:
    with factory() as db:
        job = db.get(AutoAgentifyJob, job_id)
        if job is None:
            return
        reporter = JobProgressReporter(db, job.id)
        try:
            document = raw_document
            if document is None:
                try:
                    document = await _fetch_openapi_document(
                        job.source_url or "", job.allow_private_networks
                    )
                except httpx.RequestError as exc:
                    raise ApiError(422, "tools.source_url_failed") from exc
            result = await AutoAgentifyService(planner=planner, cipher=cipher).generate(
                db=db,
                provider_id=job.provider_id,
                name=job.source_name,
                raw_document=document,
                source_url=job.source_url,
                base_url=job.base_url,
                allow_private_networks=job.allow_private_networks,
                reporter=reporter,
            )
            job = db.get(AutoAgentifyJob, job_id)
            if job is None:
                return
            job.status = "completed"
            job.phase = "completed"
            job.progress = 100
            job.result = result.model_dump(mode="json")
            job.completed_at = datetime.now(UTC).replace(tzinfo=None)
            db.commit()
        except Exception as exc:
            await _fail_job(db, job_id, exc)


async def _fail_job(db: Session, job_id: int, exc: Exception) -> None:
    db.rollback()
    job = db.get(AutoAgentifyJob, job_id)
    if job is None:
        return
    code = exc.code if isinstance(exc, ApiError) else "auto_agentify.failed"
    params: dict[str, Any] = exc.params if isinstance(exc, ApiError) else {}
    reporter = JobProgressReporter(db, job_id)
    await reporter.emit(
        ProgressEvent(
            kind="failed",
            phase="failed",
            progress=job.progress,
            message_key="autoAgentify.events.failed",
            params={"code": code, **params},
        )
    )
    job = db.get(AutoAgentifyJob, job_id)
    if job is None:
        return
    job.status = "failed"
    job.phase = "failed"
    job.error_code = code
    job.error_params = params
    job.completed_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
