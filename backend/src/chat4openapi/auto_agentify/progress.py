from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chat4openapi.models import AutoAgentifyJob, AutoAgentifyJobEvent

MAX_JOB_EVENTS = 500
ALLOWED_PHASES = {
    "queued",
    "loading_document",
    "parsing_openapi",
    "cataloging_operations",
    "analyzing_capabilities",
    "synthesizing_plan",
    "validating_plan",
    "persisting_configuration",
    "completed",
    "failed",
}


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    kind: str
    phase: str
    progress: int
    message_key: str
    params: dict[str, Any]
    capability: dict[str, Any] | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


def _validate_json(value: Any, *, depth: int = 0) -> None:
    if depth > 6:
        raise ValueError("progress payload is too deeply nested")
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if len(value) > 4_000:
            raise ValueError("progress string is too long")
        return
    if isinstance(value, list):
        if len(value) > 200:
            raise ValueError("progress list is too long")
        for item in value:
            _validate_json(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > 100:
            raise ValueError("progress object has too many keys")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 160:
                raise ValueError("progress key is invalid")
            _validate_json(item, depth=depth + 1)
        return
    raise ValueError("progress payload contains an unsupported value")


class JobProgressReporter:
    def __init__(self, db: Session, job_id: int) -> None:
        self._db = db
        self._job_id = job_id

    async def emit(self, event: ProgressEvent) -> None:
        job = self._db.get(AutoAgentifyJob, self._job_id)
        if job is None:
            raise LookupError("Auto-Agentify job no longer exists")
        if event.phase not in ALLOWED_PHASES:
            raise ValueError("unknown progress phase")
        if not 0 <= event.progress <= 100:
            raise ValueError("progress must be between 0 and 100")
        if event.progress < job.progress:
            raise ValueError("progress cannot decrease")
        if not event.message_key.startswith("autoAgentify.events."):
            raise ValueError("progress message key is invalid")
        _validate_json(event.params)
        _validate_json(event.metrics)
        _validate_json(event.capability)

        now = datetime.now(UTC).replace(tzinfo=None)
        if job.status == "queued":
            job.status = "running"
            job.started_at = now
        job.phase = event.phase
        job.progress = event.progress
        job.metrics = {**(job.metrics or {}), **event.metrics}

        event_count = self._db.scalar(
            select(func.count())
            .select_from(AutoAgentifyJobEvent)
            .where(AutoAgentifyJobEvent.job_id == job.id)
        ) or 0
        if event_count < MAX_JOB_EVENTS:
            last_sequence = self._db.scalar(
                select(func.max(AutoAgentifyJobEvent.sequence)).where(
                    AutoAgentifyJobEvent.job_id == job.id
                )
            ) or 0
            self._db.add(
                AutoAgentifyJobEvent(
                    job_id=job.id,
                    sequence=last_sequence + 1,
                    kind=event.kind,
                    phase=event.phase,
                    progress=event.progress,
                    message_key=event.message_key,
                    params=event.params,
                    capability=event.capability,
                )
            )
        self._db.commit()


def mark_interrupted_jobs(db: Session) -> int:
    jobs = db.scalars(
        select(AutoAgentifyJob).where(
            AutoAgentifyJob.status.in_(("queued", "running"))
        )
    ).all()
    now = datetime.now(UTC).replace(tzinfo=None)
    for job in jobs:
        last_sequence = db.scalar(
            select(func.max(AutoAgentifyJobEvent.sequence)).where(
                AutoAgentifyJobEvent.job_id == job.id
            )
        ) or 0
        job.status = "failed"
        job.phase = "failed"
        job.error_code = "auto_agentify.interrupted"
        job.error_params = {}
        job.completed_at = now
        db.add(
            AutoAgentifyJobEvent(
                job_id=job.id,
                sequence=last_sequence + 1,
                kind="failed",
                phase="failed",
                progress=job.progress,
                message_key="autoAgentify.events.interrupted",
                params={},
            )
        )
    if jobs:
        db.commit()
    return len(jobs)
