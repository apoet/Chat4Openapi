import hashlib
import json
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from chatapi.api.admin_auth import AdminContext, require_admin, require_csrf
from chatapi.api.errors import ApiError
from chatapi.models import ApiSource, GlobalToolAuthConfig, Tool
from chatapi.schemas.tools import (
    ApiSourceSummary,
    SourceImportRequest,
    SourceImportResponse,
    SourceUrlImportRequest,
    ToolAuthConfigRequest,
    ToolAuthConfigResponse,
    ToolEnabledRequest,
    ToolSummary,
)
from chatapi.tools.candidates import build_candidates
from chatapi.tools.openapi_loader import OpenAPIImportError, load_openapi, normalize_openapi
from chatapi.tools.network_policy import UnsafeNetworkTarget, validate_network_target

router = APIRouter(prefix="/api/admin", tags=["admin-tools"])


def _tool_summary(tool: Tool) -> ToolSummary:
    return ToolSummary.model_validate(tool)


async def _persist_import(
    payload: SourceImportRequest,
    context: AdminContext,
) -> SourceImportResponse:
    raw = (
        json.dumps(payload.document, ensure_ascii=False).encode()
        if isinstance(payload.document, dict)
        else payload.document.encode()
    )
    try:
        spec = load_openapi(raw)
        normalized = normalize_openapi(spec)
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
        tools=[_tool_summary(tool) for tool in tools],
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
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10)) as client:
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
    )


@router.get("/sources", response_model=list[ApiSourceSummary])
def list_sources(context: AdminContext = Depends(require_admin)) -> list[ApiSourceSummary]:
    sources = context.db.scalars(
        select(ApiSource).where(ApiSource.deleted_at.is_(None)).order_by(ApiSource.id)
    ).all()
    return [ApiSourceSummary.model_validate(source) for source in sources]


@router.get("/tools", response_model=list[ToolSummary])
def list_tools(
    enabled: bool | None = Query(default=None),
    context: AdminContext = Depends(require_admin),
) -> list[ToolSummary]:
    statement = select(Tool).where(Tool.deleted_at.is_(None))
    if enabled is not None:
        statement = statement.where(Tool.enabled.is_(enabled))
    tools = context.db.scalars(statement.order_by(Tool.id)).all()
    return [_tool_summary(tool) for tool in tools]


def _managed_tool(context: AdminContext, tool_id: int) -> Tool:
    tool = context.db.get(Tool, tool_id)
    if tool is None or tool.deleted_at is not None:
        raise ApiError(404, "tools.not_found")
    return tool


def _ensure_not_login_tool(context: AdminContext, tool_id: int) -> None:
    config = context.db.get(GlobalToolAuthConfig, 1)
    if config is not None and config.enabled and config.login_tool_id == tool_id:
        raise ApiError(409, "tools.login_tool_conflict")


@router.patch("/tools/{tool_id}/enabled", response_model=ToolSummary)
def set_tool_enabled(
    tool_id: int,
    payload: ToolEnabledRequest,
    context: AdminContext = Depends(require_csrf),
) -> ToolSummary:
    tool = _managed_tool(context, tool_id)
    if not payload.enabled:
        _ensure_not_login_tool(context, tool_id)
    tool.enabled = payload.enabled
    context.db.commit()
    return _tool_summary(tool)


@router.delete("/tools/{tool_id}", status_code=204)
def delete_tool(tool_id: int, context: AdminContext = Depends(require_csrf)) -> None:
    tool = _managed_tool(context, tool_id)
    _ensure_not_login_tool(context, tool_id)
    tool.enabled = False
    tool.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    context.db.commit()


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
