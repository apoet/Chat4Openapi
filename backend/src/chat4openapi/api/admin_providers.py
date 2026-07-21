from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from chat4openapi.api.admin_auth import AdminContext, require_admin, require_csrf
from chat4openapi.api.errors import ApiError
from chat4openapi.api.tool_sessions import get_tool_secret_cipher
from chat4openapi.llm.client import CanonicalMessage, LlmClient, LlmProviderError
from chat4openapi.models import Agent, LlmProvider
from chat4openapi.schemas.providers import (
    ProviderCreateRequest,
    ProviderResponse,
    ProviderUpdateRequest,
)
from chat4openapi.security.encryption import SecretCipher

router = APIRouter(prefix="/api/admin/providers", tags=["admin-providers"])


def _response(provider: LlmProvider) -> ProviderResponse:
    return ProviderResponse.model_validate(provider)


def _provider(context: AdminContext, provider_id: int) -> LlmProvider:
    provider = context.db.get(LlmProvider, provider_id)
    if provider is None or provider.deleted_at is not None:
        raise ApiError(404, "providers.not_found")
    return provider


def _ensure_not_agent_provider(context: AdminContext, provider_id: int) -> None:
    agent_ids = list(
        context.db.scalars(
            select(Agent.id)
            .where(Agent.provider_id == provider_id, Agent.deleted_at.is_(None))
            .order_by(Agent.id)
        )
    )
    if agent_ids:
        raise ApiError(409, "providers.agent_in_use", agent_ids=agent_ids)


@router.get("", response_model=list[ProviderResponse])
def list_providers(context: AdminContext = Depends(require_admin)) -> list[ProviderResponse]:
    providers = context.db.scalars(
        select(LlmProvider)
        .where(LlmProvider.deleted_at.is_(None))
        .order_by(LlmProvider.id)
    ).all()
    return [_response(provider) for provider in providers]


@router.post("", response_model=ProviderResponse, status_code=201)
def create_provider(
    payload: ProviderCreateRequest,
    context: AdminContext = Depends(require_csrf),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
) -> ProviderResponse:
    provider = LlmProvider(
        name=payload.name,
        provider_type=payload.provider_type,
        base_url=payload.base_url,
        encrypted_api_key=cipher.encrypt_json({"api_key": payload.api_key}),
        default_model=payload.default_model,
        enabled=payload.enabled,
    )
    context.db.add(provider)
    try:
        context.db.commit()
    except IntegrityError as exc:
        context.db.rollback()
        raise ApiError(409, "providers.name_conflict") from exc
    return _response(provider)


@router.post("/{provider_id}/test")
async def test_provider(
    provider_id: int,
    context: AdminContext = Depends(require_csrf),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
) -> dict[str, str | bool]:
    provider = _provider(context, provider_id)
    secret = cipher.decrypt_json(provider.encrypted_api_key)
    try:
        result = await LlmClient().complete(
            provider_type=provider.provider_type,
            base_url=provider.base_url,
            api_key=str(secret["api_key"]),
            model=provider.default_model,
            messages=[CanonicalMessage(role="user", content="Reply with OK.")],
            max_tokens=8,
        )
    except LlmProviderError as exc:
        raise ApiError(409, "providers.test_failed", status=exc.status_code) from exc
    return {
        "ok": True,
        "model": provider.default_model,
        "response": result.content,
    }


@router.patch("/{provider_id}", response_model=ProviderResponse)
def update_provider(
    provider_id: int,
    payload: ProviderUpdateRequest,
    context: AdminContext = Depends(require_csrf),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
) -> ProviderResponse:
    provider = _provider(context, provider_id)
    values = payload.model_dump(exclude_unset=True)
    api_key = values.pop("api_key", None)
    if values.get("enabled") is False:
        _ensure_not_agent_provider(context, provider.id)
    for key, value in values.items():
        setattr(provider, key, value)
    if api_key:
        provider.encrypted_api_key = cipher.encrypt_json({"api_key": api_key})
    try:
        context.db.commit()
    except IntegrityError as exc:
        context.db.rollback()
        raise ApiError(409, "providers.name_conflict") from exc
    return _response(provider)


@router.delete("/{provider_id}", status_code=204)
def delete_provider(
    provider_id: int, context: AdminContext = Depends(require_csrf)
) -> None:
    provider = _provider(context, provider_id)
    _ensure_not_agent_provider(context, provider.id)
    provider.enabled = False
    provider.deleted_at = datetime.now(UTC).replace(tzinfo=None)
    context.db.commit()
