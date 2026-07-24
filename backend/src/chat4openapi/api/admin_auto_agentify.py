import asyncio
import json

import httpx
from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from chat4openapi.api.admin_auth import AdminContext, require_admin, require_csrf
from chat4openapi.api.admin_tools import _fetch_openapi_document
from chat4openapi.api.errors import ApiError
from chat4openapi.api.tool_sessions import get_tool_secret_cipher
from chat4openapi.auto_agentify.planner import AutoAgentifyPlanner
from chat4openapi.auto_agentify.jobs import (
    create_job,
    event_response,
    job_response,
    latest_job,
    owned_job,
    schedule_auto_agentify_job,
    session_factory_for,
)
from chat4openapi.auto_agentify.service import AutoAgentifyService
from chat4openapi.models import (
    ApiSource,
    AutoAgentifyJob,
    AutoAgentifyJobEvent,
)
from chat4openapi.schemas.auto_agentify import (
    AutoAgentifyJobResponse,
    AutoAgentifyResponse,
    AutoAgentifySourceJobRequest,
    AutoAgentifyUrlRequest,
    CapabilityPreferences,
)
from chat4openapi.security.encryption import SecretCipher

router = APIRouter(
    prefix="/api/admin/auto-agentify",
    tags=["admin-auto-agentify"],
)


def get_auto_agentify_planner() -> AutoAgentifyPlanner:
    return AutoAgentifyPlanner()


def _form_capability_preferences(
    allowed_system_capabilities: str,
    custom_capability_labels: str,
) -> CapabilityPreferences:
    try:
        return CapabilityPreferences(
            allowed_system_capabilities=json.loads(
                allowed_system_capabilities
            ),
            custom_capability_labels=json.loads(custom_capability_labels),
        )
    except (TypeError, ValueError) as exc:
        raise ApiError(
            422, "auto_agentify.capability_preferences_invalid"
        ) from exc


@router.post("/jobs/url", response_model=AutoAgentifyJobResponse, status_code=202)
async def create_url_job(
    payload: AutoAgentifyUrlRequest,
    context: AdminContext = Depends(require_csrf),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
    planner: AutoAgentifyPlanner = Depends(get_auto_agentify_planner),
) -> AutoAgentifyJobResponse:
    factory = session_factory_for(context.db)
    job, created = create_job(
        context.db,
        creator_id=context.admin.id,
        provider_id=payload.provider_id,
        input_mode="url",
        source_name=payload.name,
        source_url=payload.url,
        base_url=payload.base_url,
        allow_private_networks=payload.allow_private_networks,
        allowed_system_capabilities=payload.allowed_system_capabilities,
        custom_capability_labels=payload.custom_capability_labels,
        result_language=payload.result_language,
    )
    if created:
        schedule_auto_agentify_job(
            factory=factory,
            job_id=job.id,
            raw_document=None,
            planner=planner,
            cipher=cipher,
            allowed_system_capabilities=payload.allowed_system_capabilities,
            custom_capability_labels=payload.custom_capability_labels,
            result_language=payload.result_language,
        )
    return job_response(job)


@router.post("/jobs/file", response_model=AutoAgentifyJobResponse, status_code=202)
async def create_file_job(
    provider_id: int = Form(gt=0),
    name: str = Form(min_length=1, max_length=160),
    document: UploadFile = File(),
    base_url: str | None = Form(default=None, max_length=2048),
    allow_private_networks: bool = Form(default=False),
    allowed_system_capabilities: str = Form(default="[]"),
    custom_capability_labels: str = Form(default="[]"),
    result_language: str = Form(default="en-US", pattern="^(zh-CN|en-US)$"),
    context: AdminContext = Depends(require_csrf),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
    planner: AutoAgentifyPlanner = Depends(get_auto_agentify_planner),
) -> AutoAgentifyJobResponse:
    preferences = _form_capability_preferences(
        allowed_system_capabilities, custom_capability_labels
    )
    raw_document = await document.read(5 * 1024 * 1024 + 1)
    if len(raw_document) > 5 * 1024 * 1024:
        raise ApiError(413, "tools.document_too_large")
    factory = session_factory_for(context.db)
    job, created = create_job(
        context.db,
        creator_id=context.admin.id,
        provider_id=provider_id,
        input_mode="file",
        source_name=name,
        file_name=document.filename,
        base_url=base_url,
        allow_private_networks=allow_private_networks,
        allowed_system_capabilities=(
            preferences.allowed_system_capabilities
        ),
        custom_capability_labels=preferences.custom_capability_labels,
        result_language=result_language,
    )
    if created:
        schedule_auto_agentify_job(
            factory=factory,
            job_id=job.id,
            raw_document=raw_document,
            planner=planner,
            cipher=cipher,
            allowed_system_capabilities=(
                preferences.allowed_system_capabilities
            ),
            custom_capability_labels=preferences.custom_capability_labels,
            result_language=result_language,
        )
    return job_response(job)


@router.get("/jobs/latest", response_model=AutoAgentifyJobResponse | None)
def get_latest_job(
    context: AdminContext = Depends(require_admin),
) -> AutoAgentifyJobResponse | None:
    job = latest_job(context.db, context.admin.id)
    return job_response(job) if job is not None else None


@router.post(
    "/sources/{source_id}/jobs",
    response_model=AutoAgentifyJobResponse,
    status_code=202,
)
def create_source_job(
    source_id: int,
    payload: AutoAgentifySourceJobRequest,
    context: AdminContext = Depends(require_csrf),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
    planner: AutoAgentifyPlanner = Depends(get_auto_agentify_planner),
) -> AutoAgentifyJobResponse:
    source = context.db.get(ApiSource, source_id)
    if source is None or source.deleted_at is not None:
        raise ApiError(404, "tools.source_not_found")
    if not source.spec_snapshot:
        raise ApiError(409, "auto_agentify.source_document_missing")
    factory = session_factory_for(context.db)
    job, created = create_job(
        context.db,
        creator_id=context.admin.id,
        provider_id=payload.provider_id,
        source_id=source.id,
        input_mode="url" if source.document_url else "file",
        source_name=source.name,
        source_url=source.document_url,
        base_url=source.base_url,
        allow_private_networks=source.allow_private_networks,
        allowed_system_capabilities=payload.allowed_system_capabilities,
        custom_capability_labels=payload.custom_capability_labels,
        result_language=payload.result_language,
    )
    if created:
        schedule_auto_agentify_job(
            factory=factory,
            job_id=job.id,
            raw_document=source.spec_snapshot.encode("utf-8"),
            planner=planner,
            cipher=cipher,
            allowed_system_capabilities=payload.allowed_system_capabilities,
            custom_capability_labels=payload.custom_capability_labels,
            result_language=payload.result_language,
        )
    return job_response(job)


@router.get("/jobs/{public_id}", response_model=AutoAgentifyJobResponse)
def get_job(
    public_id: str,
    context: AdminContext = Depends(require_admin),
) -> AutoAgentifyJobResponse:
    return job_response(owned_job(context.db, context.admin.id, public_id))


@router.get("/jobs/{public_id}/events")
def stream_job_events(
    public_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    after: int = 0,
    context: AdminContext = Depends(require_admin),
) -> StreamingResponse:
    job = owned_job(context.db, context.admin.id, public_id)
    factory = session_factory_for(context.db)
    try:
        cursor = max(after, int(last_event_id or 0))
    except ValueError as exc:
        raise ApiError(422, "auto_agentify.invalid_event_cursor") from exc

    async def events():
        nonlocal cursor
        while True:
            with factory() as db:
                current = db.get(AutoAgentifyJob, job.id)
                rows = db.scalars(
                    select(AutoAgentifyJobEvent)
                    .where(
                        AutoAgentifyJobEvent.job_id == job.id,
                        AutoAgentifyJobEvent.sequence > cursor,
                    )
                    .order_by(AutoAgentifyJobEvent.sequence)
                ).all()
                for row in rows:
                    cursor = row.sequence
                    payload = event_response(row).model_dump(mode="json")
                    yield f"id: {row.sequence}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
                terminal = current is None or current.status in ("completed", "failed")
            if terminal:
                break
            if await request.is_disconnected():
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/file", response_model=AutoAgentifyResponse, status_code=201)
async def auto_agentify_file(
    provider_id: int = Form(gt=0),
    name: str = Form(min_length=1, max_length=160),
    document: UploadFile = File(),
    base_url: str | None = Form(default=None, max_length=2048),
    allow_private_networks: bool = Form(default=False),
    allowed_system_capabilities: str = Form(default="[]"),
    custom_capability_labels: str = Form(default="[]"),
    result_language: str = Form(default="en-US", pattern="^(zh-CN|en-US)$"),
    context: AdminContext = Depends(require_csrf),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
    planner: AutoAgentifyPlanner = Depends(get_auto_agentify_planner),
) -> AutoAgentifyResponse:
    preferences = _form_capability_preferences(
        allowed_system_capabilities, custom_capability_labels
    )
    raw_document = await document.read(5 * 1024 * 1024 + 1)
    return await AutoAgentifyService(planner=planner, cipher=cipher).generate(
        db=context.db,
        provider_id=provider_id,
        name=name,
        raw_document=raw_document,
        source_url=None,
        base_url=base_url,
        allow_private_networks=allow_private_networks,
        allowed_system_capabilities=preferences.allowed_system_capabilities,
        custom_capability_labels=preferences.custom_capability_labels,
        result_language=result_language,
    )


@router.post("/url", response_model=AutoAgentifyResponse, status_code=201)
async def auto_agentify_url(
    payload: AutoAgentifyUrlRequest,
    context: AdminContext = Depends(require_csrf),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
    planner: AutoAgentifyPlanner = Depends(get_auto_agentify_planner),
) -> AutoAgentifyResponse:
    try:
        raw_document = await _fetch_openapi_document(
            payload.url, payload.allow_private_networks
        )
    except httpx.RequestError as exc:
        raise ApiError(422, "tools.source_url_failed") from exc
    return await AutoAgentifyService(planner=planner, cipher=cipher).generate(
        db=context.db,
        provider_id=payload.provider_id,
        name=payload.name,
        raw_document=raw_document,
        source_url=payload.url,
        base_url=payload.base_url,
        allow_private_networks=payload.allow_private_networks,
        allowed_system_capabilities=payload.allowed_system_capabilities,
        custom_capability_labels=payload.custom_capability_labels,
        result_language=payload.result_language,
    )
