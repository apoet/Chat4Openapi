import httpx
from fastapi import APIRouter, Depends, File, Form, UploadFile

from chat4openapi.api.admin_auth import AdminContext, require_csrf
from chat4openapi.api.admin_tools import _fetch_openapi_document
from chat4openapi.api.errors import ApiError
from chat4openapi.api.tool_sessions import get_tool_secret_cipher
from chat4openapi.auto_agentify.planner import AutoAgentifyPlanner
from chat4openapi.auto_agentify.service import AutoAgentifyService
from chat4openapi.schemas.auto_agentify import (
    AutoAgentifyResponse,
    AutoAgentifyUrlRequest,
)
from chat4openapi.security.encryption import SecretCipher

router = APIRouter(
    prefix="/api/admin/auto-agentify",
    tags=["admin-auto-agentify"],
)


def get_auto_agentify_planner() -> AutoAgentifyPlanner:
    return AutoAgentifyPlanner()


@router.post("/file", response_model=AutoAgentifyResponse, status_code=201)
async def auto_agentify_file(
    provider_id: int = Form(gt=0),
    name: str = Form(min_length=1, max_length=160),
    document: UploadFile = File(),
    base_url: str | None = Form(default=None, max_length=2048),
    allow_private_networks: bool = Form(default=False),
    context: AdminContext = Depends(require_csrf),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
    planner: AutoAgentifyPlanner = Depends(get_auto_agentify_planner),
) -> AutoAgentifyResponse:
    raw_document = await document.read(5 * 1024 * 1024 + 1)
    return await AutoAgentifyService(planner=planner, cipher=cipher).generate(
        context=context,
        provider_id=provider_id,
        name=name,
        raw_document=raw_document,
        source_url=None,
        base_url=base_url,
        allow_private_networks=allow_private_networks,
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
        context=context,
        provider_id=payload.provider_id,
        name=payload.name,
        raw_document=raw_document,
        source_url=payload.url,
        base_url=payload.base_url,
        allow_private_networks=payload.allow_private_networks,
    )

