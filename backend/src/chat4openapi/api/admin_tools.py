import hashlib
import json
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chat4openapi.api.admin_auth import AdminContext, require_admin, require_csrf
from chat4openapi.api.errors import ApiError
from chat4openapi.db.serialized_write import serialized_write
from chat4openapi.models import (
    ApiSource,
    GlobalToolAuthConfig,
    Skill,
    SkillTool,
    Tool,
    ToolParameterOverride,
)
from chat4openapi.schemas.tools import (
    ApiSourceEnabledRequest,
    ApiSourceSummary,
    ApiSourceUpdateRequest,
    SourceImportRequest,
    SourceImportResponse,
    SourceRefreshResponse,
    SourceUrlImportRequest,
    ToolAuthConfigRequest,
    ToolAuthConfigResponse,
    ToolBatchFailed,
    ToolBatchRequest,
    ToolBatchResponse,
    ToolBatchSucceeded,
    ToolEnabledRequest,
    ToolParameterOverrideRequest,
    ToolSummary,
    ToolUpdateRequest,
)
from chat4openapi.tools.candidates import build_candidates
from chat4openapi.tools.effective_schema import (
    effective_input_schema,
    reconcile_parameter_overrides,
)
from chat4openapi.tools.openapi_loader import OpenAPIImportError, load_openapi, normalize_openapi
from chat4openapi.tools.network_policy import UnsafeNetworkTarget, validate_network_target
from chat4openapi.tools.bulk import apply_tool_action

router = APIRouter(prefix="/api/admin", tags=["admin-tools"])


def _tool_summary(
    db: Session,
    tool: Tool,
    spec: dict | None = None,
) -> ToolSummary:
    summary = ToolSummary.model_validate(tool)
    summary = summary.model_copy(update={"input_schema": effective_input_schema(db, tool)})
    if spec is None:
        return summary
    method, path = tool.operation_key.split(" ", 1)
    operation = spec.get("paths", {}).get(path, {}).get(method.lower(), {})
    tags = operation.get("tags", []) if isinstance(operation, dict) else []
    return summary.model_copy(
        update={"tags": [str(tag) for tag in tags if isinstance(tag, str)]}
    )


async def _persist_import(
    payload: SourceImportRequest,
    context: AdminContext,
    *,
    source_url: str | None = None,
) -> SourceImportResponse:
    raw = (
        json.dumps(payload.document, ensure_ascii=False).encode()
        if isinstance(payload.document, dict)
        else payload.document.encode()
    )
    try:
        spec = load_openapi(raw)
        normalized = normalize_openapi(spec, source_url=source_url)
    except OpenAPIImportError as exc:
        raise ApiError(422, "tools.openapi_invalid", reason=str(exc)) from exc
    base_url = payload.base_url
    if base_url is None:
        servers = normalized.get("servers", [])
        base_url = servers[0].get("url") if servers else None
    if not base_url:
        raise ApiError(422, "tools.base_url_required")
    try:
        candidates = await build_candidates(normalized, base_url)
    except (KeyError, ValueError) as exc:
        raise ApiError(422, "tools.openapi_unsupported", reason=str(exc)) from exc

    source = ApiSource(
        name=payload.name,
        source_type="openapi",
        base_url=base_url,
        document_url=source_url,
        spec_snapshot=json.dumps(spec, ensure_ascii=False, separators=(",", ":")),
        spec_hash=hashlib.sha256(raw).hexdigest(),
        allow_private_networks=payload.allow_private_networks,
    )
    context.db.add(source)
    context.db.flush()
    tools = [
        Tool(
            api_source_id=source.id,
            operation_key=candidate.operation_key,
            name=candidate.name,
            description=candidate.description,
            input_schema=candidate.input_schema,
            execution_schema=candidate.execution_schema,
            enabled=False,
        )
        for candidate in candidates
    ]
    context.db.add_all(tools)
    try:
        context.db.commit()
    except IntegrityError as exc:
        context.db.rollback()
        raise ApiError(409, "tools.name_conflict") from exc
    return SourceImportResponse(
        source=ApiSourceSummary.model_validate(source),
        tools=[_tool_summary(context.db, tool, spec) for tool in tools],
    )


@router.post("/sources/import", response_model=SourceImportResponse, status_code=201)
async def import_source(
    payload: SourceImportRequest,
    context: AdminContext = Depends(require_csrf),
) -> SourceImportResponse:
    return await _persist_import(payload, context)


@router.post("/sources/import-file", response_model=SourceImportResponse, status_code=201)
async def import_source_file(
    name: str = Form(min_length=1, max_length=160),
    document: UploadFile = File(),
    base_url: str | None = Form(default=None, max_length=2048),
    allow_private_networks: bool = Form(default=False),
    context: AdminContext = Depends(require_csrf),
) -> SourceImportResponse:
    raw = await document.read(5 * 1024 * 1024 + 1)
    return await _persist_import(
        SourceImportRequest(
            name=name,
            document=raw.decode("utf-8", errors="strict"),
            base_url=base_url,
            allow_private_networks=allow_private_networks,
        ),
        context,
    )


async def _fetch_openapi_document(url: str, allow_private_networks: bool) -> bytes:
    target = httpx.URL(url)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30, connect=10), verify=False
    ) as client:
        for redirect_count in range(4):
            try:
                await validate_network_target(target, allow_private_networks)
            except UnsafeNetworkTarget as exc:
                raise ApiError(422, "tools.source_url_unsafe", reason=str(exc)) from exc
            async with client.stream("GET", target, follow_redirects=False) as response:
                if response.is_redirect:
                    if redirect_count == 3 or not response.headers.get("location"):
                        raise ApiError(422, "tools.source_url_redirect")
                    target = target.join(response.headers["location"])
                    continue
                if not 200 <= response.status_code < 300:
                    raise ApiError(422, "tools.source_url_failed", status=response.status_code)
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 5 * 1024 * 1024:
                        raise ApiError(413, "tools.openapi_too_large")
                    chunks.append(chunk)
                return b"".join(chunks)
    raise ApiError(422, "tools.source_url_redirect")


@router.post("/sources/import-url", response_model=SourceImportResponse, status_code=201)
async def import_source_url(
    payload: SourceUrlImportRequest,
    context: AdminContext = Depends(require_csrf),
) -> SourceImportResponse:
    try:
        raw = await _fetch_openapi_document(payload.url, payload.allow_private_networks)
    except httpx.RequestError as exc:
        raise ApiError(422, "tools.source_url_failed") from exc
    return await _persist_import(
        SourceImportRequest(
            name=payload.name,
            document=raw.decode("utf-8", errors="strict"),
            base_url=payload.base_url,
            allow_private_networks=payload.allow_private_networks,
        ),
        context,
        source_url=payload.url,
    )


@router.get("/sources", response_model=list[ApiSourceSummary])
def list_sources(context: AdminContext = Depends(require_admin)) -> list[ApiSourceSummary]:
    sources = context.db.scalars(
        select(ApiSource).where(ApiSource.deleted_at.is_(None)).order_by(ApiSource.id)
    ).all()
    return [ApiSourceSummary.model_validate(source) for source in sources]


def _managed_source(context: AdminContext, source_id: int) -> ApiSource:
    source = context.db.get(ApiSource, source_id)
    if source is None or source.deleted_at is not None:
        raise ApiError(404, "tools.source_not_found")
    return source


def _source_tool_ids(context: AdminContext, source_id: int) -> list[int]:
    return list(
        context.db.scalars(
            select(Tool.id).where(
                Tool.api_source_id == source_id,
                Tool.deleted_at.is_(None),
            )
        )
    )


def _ensure_source_not_login_source(context: AdminContext, tool_ids: list[int]) -> None:
    config = context.db.get(GlobalToolAuthConfig, 1)
    if (
        config is not None
        and config.enabled
        and config.login_tool_id is not None
        and config.login_tool_id in tool_ids
    ):
        raise ApiError(409, "tools.login_tool_conflict")


def _stop_skills_using_tools(context: AdminContext, tool_ids: list[int]) -> None:
    if not tool_ids:
        return
    skills = context.db.scalars(
        select(Skill)
        .join(SkillTool, SkillTool.skill_id == Skill.id)
        .where(SkillTool.tool_id.in_(tool_ids), Skill.running.is_(True))
        .distinct()
    ).all()
    for skill in skills:
        skill.running = False


@router.put("/sources/{source_id}", response_model=ApiSourceSummary)
def update_source(
    source_id: int,
    payload: ApiSourceUpdateRequest,
    context: AdminContext = Depends(require_csrf),
) -> ApiSourceSummary:
    source = _managed_source(context, source_id)
    source.name = payload.name
    source.base_url = payload.base_url
    source.document_url = payload.document_url
    source.allow_private_networks = payload.allow_private_networks
    context.db.commit()
    return ApiSourceSummary.model_validate(source)


async def _refresh_source_document(
    source: ApiSource,
    raw: bytes,
    context: AdminContext,
) -> SourceRefreshResponse:
    try:
        spec = load_openapi(raw)
        normalized = normalize_openapi(spec, source_url=source.document_url)
        candidates = await build_candidates(normalized, source.base_url)
    except OpenAPIImportError as exc:
        raise ApiError(422, "tools.openapi_invalid", reason=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise ApiError(422, "tools.openapi_unsupported", reason=str(exc)) from exc

    existing = {
        tool.name: tool
        for tool in context.db.scalars(
            select(Tool).where(
                Tool.api_source_id == source.id,
                Tool.deleted_at.is_(None),
            )
        )
    }
    created = updated = unchanged = 0
    for candidate in candidates:
        tool = existing.get(candidate.name)
        if tool is None:
            context.db.add(
                Tool(
                    api_source_id=source.id,
                    operation_key=candidate.operation_key,
                    name=candidate.name,
                    description=candidate.description,
                    input_schema=candidate.input_schema,
                    execution_schema=candidate.execution_schema,
                    enabled=False,
                )
            )
            created += 1
            continue
        parameters_changed = (
            tool.input_schema != candidate.input_schema
            or tool.execution_schema != candidate.execution_schema
        )
        if not parameters_changed:
            unchanged += 1
            continue
        tool.operation_key = candidate.operation_key
        tool.description = candidate.description
        tool.input_schema = candidate.input_schema
        reconcile_parameter_overrides(context.db, tool)
        tool.execution_schema = candidate.execution_schema
        updated += 1

    source.spec_snapshot = json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
    source.spec_hash = hashlib.sha256(raw).hexdigest()
    try:
        context.db.commit()
    except IntegrityError as exc:
        context.db.rollback()
        raise ApiError(409, "tools.name_conflict") from exc
    return SourceRefreshResponse(created=created, updated=updated, unchanged=unchanged)


@router.post("/sources/{source_id}/refresh", response_model=SourceRefreshResponse)
async def refresh_source(
    source_id: int,
    context: AdminContext = Depends(require_csrf),
) -> SourceRefreshResponse:
    source = _managed_source(context, source_id)
    if not source.document_url:
        raise ApiError(409, "tools.source_url_required")
    try:
        raw = await _fetch_openapi_document(
            source.document_url, source.allow_private_networks
        )
    except httpx.RequestError as exc:
        raise ApiError(422, "tools.source_url_failed") from exc
    return await _refresh_source_document(source, raw, context)


@router.post("/sources/{source_id}/refresh-file", response_model=SourceRefreshResponse)
async def refresh_source_file(
    source_id: int,
    document: UploadFile = File(),
    context: AdminContext = Depends(require_csrf),
) -> SourceRefreshResponse:
    source = _managed_source(context, source_id)
    raw = await document.read(5 * 1024 * 1024 + 1)
    return await _refresh_source_document(source, raw, context)


@router.patch("/sources/{source_id}/enabled", response_model=ApiSourceSummary)
def set_source_enabled(
    source_id: int,
    payload: ApiSourceEnabledRequest,
    context: AdminContext = Depends(require_csrf),
) -> ApiSourceSummary:
    with serialized_write(context.db):
        source = _managed_source(context, source_id)
        tool_ids = _source_tool_ids(context, source_id)
        if not payload.enabled:
            _ensure_source_not_login_source(context, tool_ids)
            _stop_skills_using_tools(context, tool_ids)
        source.enabled = payload.enabled
    return ApiSourceSummary.model_validate(source)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(
    source_id: int,
    context: AdminContext = Depends(require_csrf),
) -> None:
    with serialized_write(context.db):
        source = _managed_source(context, source_id)
        tools = context.db.scalars(
            select(Tool).where(
                Tool.api_source_id == source_id,
                Tool.deleted_at.is_(None),
            )
        ).all()
        tool_ids = [tool.id for tool in tools]
        _ensure_source_not_login_source(context, tool_ids)
        _stop_skills_using_tools(context, tool_ids)
        deleted_at = datetime.now(UTC).replace(tzinfo=None)
        for tool in tools:
            tool.enabled = False
            tool.deleted_at = deleted_at
        source.enabled = False
        source.deleted_at = deleted_at


@router.get("/tools", response_model=list[ToolSummary])
def list_tools(
    enabled: bool | None = Query(default=None),
    context: AdminContext = Depends(require_admin),
) -> list[ToolSummary]:
    statement = select(Tool).where(Tool.deleted_at.is_(None))
    if enabled is not None:
        statement = statement.where(Tool.enabled.is_(enabled))
    tools = context.db.scalars(statement.order_by(Tool.id)).all()
    source_ids = {tool.api_source_id for tool in tools}
    source_specs = {
        source.id: json.loads(source.spec_snapshot)
        for source in context.db.scalars(
            select(ApiSource).where(ApiSource.id.in_(source_ids))
        )
    }
    return [
        _tool_summary(context.db, tool, source_specs.get(tool.api_source_id))
        for tool in tools
    ]


@router.post("/tools/batch", response_model=ToolBatchResponse)
def batch_tools(
    payload: ToolBatchRequest,
    context: AdminContext = Depends(require_csrf),
) -> ToolBatchResponse:
    if len(payload.tool_ids) > 200:
        raise ApiError(422, "tools.batch_limit_exceeded", limit=200)
    succeeded: list[ToolBatchSucceeded] = []
    failed: list[ToolBatchFailed] = []
    with serialized_write(context.db):
        for tool_id in payload.tool_ids:
            try:
                with context.db.begin_nested():
                    status = apply_tool_action(context.db, tool_id, payload.action)
                    context.db.flush()
                succeeded.append(
                    ToolBatchSucceeded(
                        tool_id=tool_id,
                        action=payload.action,
                        status=status,
                    )
                )
            except ApiError as exc:
                failed.append(
                    ToolBatchFailed(
                        tool_id=tool_id,
                        action=payload.action,
                        code=exc.code,
                        params=exc.params,
                    )
                )
            except Exception:
                failed.append(
                    ToolBatchFailed(
                        tool_id=tool_id,
                        action=payload.action,
                        code="tools.batch_item_failed",
                    )
                )
    return ToolBatchResponse(
        request_count=len(payload.tool_ids),
        succeeded=succeeded,
        failed=failed,
    )


def _managed_tool(context: AdminContext, tool_id: int) -> Tool:
    tool = context.db.get(Tool, tool_id)
    if tool is None or tool.deleted_at is not None:
        raise ApiError(404, "tools.not_found")
    return tool


@router.patch("/tools/{tool_id}", response_model=ToolSummary)
def update_tool(
    tool_id: int,
    payload: ToolUpdateRequest,
    context: AdminContext = Depends(require_csrf),
) -> ToolSummary:
    tool = _managed_tool(context, tool_id)
    description = payload.description.strip() if payload.description else ""
    tool.description = description or None
    context.db.commit()
    source = context.db.get(ApiSource, tool.api_source_id)
    spec = json.loads(source.spec_snapshot) if source is not None else None
    return _tool_summary(context.db, tool, spec)


@router.put(
    "/tools/{tool_id}/parameters/{argument_name}",
    response_model=ToolSummary,
)
def update_tool_parameter(
    tool_id: int,
    argument_name: str,
    payload: ToolParameterOverrideRequest,
    context: AdminContext = Depends(require_csrf),
) -> ToolSummary:
    tool = _managed_tool(context, tool_id)
    properties = tool.input_schema.get("properties", {})
    if not isinstance(properties, dict) or argument_name not in properties:
        raise ApiError(404, "tools.parameter_not_found")
    override = context.db.scalar(
        select(ToolParameterOverride).where(
            ToolParameterOverride.tool_id == tool.id,
            ToolParameterOverride.argument_name == argument_name,
        )
    )
    if payload.description is None and payload.example is None:
        if override is not None:
            context.db.delete(override)
    else:
        if override is None:
            override = ToolParameterOverride(
                tool_id=tool.id,
                argument_name=argument_name,
            )
            context.db.add(override)
        override.description = payload.description
        override.example = payload.example
    context.db.commit()
    source = context.db.get(ApiSource, tool.api_source_id)
    spec = json.loads(source.spec_snapshot) if source is not None else None
    return _tool_summary(context.db, tool, spec)


@router.patch("/tools/{tool_id}/enabled", response_model=ToolSummary)
def set_tool_enabled(
    tool_id: int,
    payload: ToolEnabledRequest,
    context: AdminContext = Depends(require_csrf),
) -> ToolSummary:
    with serialized_write(context.db):
        apply_tool_action(
            context.db,
            tool_id,
            "enable" if payload.enabled else "disable",
        )
        tool = _managed_tool(context, tool_id)
    source = context.db.get(ApiSource, tool.api_source_id)
    spec = json.loads(source.spec_snapshot) if source is not None else None
    return _tool_summary(context.db, tool, spec)


@router.delete("/tools/{tool_id}", status_code=204)
def delete_tool(tool_id: int, context: AdminContext = Depends(require_csrf)) -> None:
    with serialized_write(context.db):
        apply_tool_action(context.db, tool_id, "delete")


@router.get("/tool-auth", response_model=ToolAuthConfigResponse)
def get_tool_auth(context: AdminContext = Depends(require_admin)) -> ToolAuthConfigResponse:
    config = context.db.get(GlobalToolAuthConfig, 1)
    if config is None:
        return ToolAuthConfigResponse(enabled=False)
    return ToolAuthConfigResponse.model_validate(config, from_attributes=True)


@router.put("/tool-auth", response_model=ToolAuthConfigResponse)
def set_tool_auth(
    payload: ToolAuthConfigRequest,
    context: AdminContext = Depends(require_csrf),
) -> ToolAuthConfigResponse:
    if payload.enabled:
        if payload.login_tool_id is None or not payload.token_json_path:
            raise ApiError(422, "tools.login_config_incomplete")
        tool = _managed_tool(context, payload.login_tool_id)
        if not tool.enabled:
            raise ApiError(409, "tools.login_tool_disabled")
    config = context.db.get(GlobalToolAuthConfig, 1)
    values = payload.model_dump()
    if config is None:
        config = GlobalToolAuthConfig(id=1, **values)
        context.db.add(config)
    else:
        for key, value in values.items():
            setattr(config, key, value)
    context.db.commit()
    return ToolAuthConfigResponse.model_validate(config, from_attributes=True)
