import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from chat4openapi.api.errors import ApiError
from chat4openapi.api.tool_sessions import (
    TOOL_SESSION_COOKIE,
    get_tool_executor,
    get_tool_secret_cipher,
)
from chat4openapi.chat.agent import AgentError, AgentRuntime, AgentTurnRequest, AgentTurnResult
from chat4openapi.db.session import get_db_session
from chat4openapi.llm.client import CanonicalMessage, LlmClient, LlmProviderError
from chat4openapi.models import AgentSkill, Conversation, Skill
from chat4openapi.schemas.chat import ChatTurnRequest, ChatTurnResponse
from chat4openapi.security.agent_keys import AgentKeyContext, require_agent_api_key
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.tools.executor import ToolExecutor

router = APIRouter(tags=["compatible-chat"])


def get_llm_client() -> LlmClient:
    return LlmClient()


def _skill_id(model: str) -> int:
    if not model.startswith("skill-"):
        raise ApiError(404, "chat.skill_not_found")
    try:
        skill_id = int(model.removeprefix("skill-"))
    except ValueError as exc:
        raise ApiError(404, "chat.skill_not_found") from exc
    if skill_id < 1:
        raise ApiError(404, "chat.skill_not_found")
    return skill_id


def _bound_skill_ids(db: Session, agent_id: int) -> list[int]:
    return list(
        db.scalars(
            select(AgentSkill.skill_id)
            .where(AgentSkill.agent_id == agent_id)
            .order_by(AgentSkill.position, AgentSkill.skill_id)
        )
    )


def _eligible_bound_skill_ids(db: Session, agent_id: int) -> list[int]:
    return list(
        db.scalars(
            select(AgentSkill.skill_id)
            .join(Skill, Skill.id == AgentSkill.skill_id)
            .where(
                AgentSkill.agent_id == agent_id,
                Skill.running.is_(True),
                Skill.deleted_at.is_(None),
            )
            .order_by(AgentSkill.position, AgentSkill.skill_id)
        )
    )


def _candidate_skill_ids(
    body: dict[str, Any],
    context: AgentKeyContext,
    conversation: Conversation | None,
) -> list[int]:
    db = context.db
    model = body.get("model", "")
    extension_present = "chat4openapi_skill_ids" in body
    agent_aliases = {"agent-default", f"agent-{context.agent.id}"}
    if isinstance(model, str) and model.startswith("agent-") and model not in agent_aliases:
        raise ApiError(403, "auth.agent_key_forbidden")
    bound_ids = _bound_skill_ids(db, context.agent.id)
    bound_set = set(bound_ids)
    if model in agent_aliases:
        candidate_ids = body.get("chat4openapi_skill_ids", [])
        if (
            not isinstance(candidate_ids, list)
            or len(candidate_ids) > 32
            or any(
                isinstance(skill_id, bool) or not isinstance(skill_id, int) or skill_id < 1
                for skill_id in candidate_ids
            )
        ):
            raise ApiError(422, "validation.invalid", fields=["body.chat4openapi_skill_ids"])
        candidate_ids = list(dict.fromkeys(candidate_ids))
        forbidden = [skill_id for skill_id in candidate_ids if skill_id not in bound_set]
        if forbidden and conversation is None:
            raise ApiError(404, "chat.skill_not_found")
        if extension_present and candidate_ids:
            return candidate_ids
        eligible_ids = _eligible_bound_skill_ids(db, context.agent.id)
        if not eligible_ids and conversation is None:
            raise ApiError(409, "agent.no_eligible_skills")
        return eligible_ids
    if extension_present:
        raise ApiError(409, "chat.candidate_scope_conflict")
    skill_id = _skill_id(model)
    if conversation is not None:
        return [skill_id]
    skill = db.get(Skill, skill_id)
    if skill is None or skill_id not in bound_set:
        raise ApiError(404, "chat.skill_not_found")
    if body.get("conversation_id") is None and (skill.deleted_at is not None or not skill.running):
        raise ApiError(409, "agent.skill_unavailable", skill_ids=[skill_id])
    return [skill_id]


def _session_id(
    body: dict[str, Any],
    request: Request,
    chat4openapi_header: str | None,
    legacy_header: str | None,
) -> str | None:
    return (
        body.get("tool_session_id")
        or chat4openapi_header
        or legacy_header
        or request.cookies.get(TOOL_SESSION_COOKIE)
    )


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content)


def _latest_user_content(body: dict[str, Any]) -> str:
    messages = body.get("messages")
    if not isinstance(messages, list):
        raise ApiError(422, "validation.invalid", fields=["body.messages"])
    user_message = next(
        (
            message
            for message in reversed(messages)
            if isinstance(message, dict) and message.get("role") == "user"
        ),
        None,
    )
    if user_message is None:
        raise ApiError(422, "validation.invalid", fields=["body.messages"])
    return _content_text(user_message.get("content", ""))


def _incoming_messages(body: dict[str, Any], *, anthropic: bool) -> list[CanonicalMessage]:
    raw_messages = body.get("messages")
    if not isinstance(raw_messages, list):
        raise ApiError(422, "validation.invalid", fields=["body.messages"])
    messages: list[CanonicalMessage] = []
    if anthropic and "system" in body:
        system = _content_text(body["system"])
        if system:
            messages.append(CanonicalMessage(role="system", content=system))
    for index, item in enumerate(raw_messages):
        if not isinstance(item, dict) or item.get("role") not in {
            "system",
            "user",
            "assistant",
        }:
            raise ApiError(422, "validation.invalid", fields=[f"body.messages.{index}"])
        messages.append(
            CanonicalMessage(
                role=str(item["role"]),
                content=_content_text(item.get("content", "")),
            )
        )
    if not any(message.role == "user" for message in messages):
        raise ApiError(422, "validation.invalid", fields=["body.messages"])
    return messages


def _agent_error(exc: AgentError) -> ApiError:
    status_code = 404 if exc.code == "agent.conversation_not_found" else 409
    return ApiError(status_code, exc.code, **exc.params)


def _validate_conversation_scope(
    db: Session,
    conversation_id: str | None,
    candidate_skill_ids: list[int],
    *,
    scope_supplied: bool,
) -> None:
    if conversation_id is None or not scope_supplied:
        return
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.deleted_at is not None:
        return
    requested_source = "explicit" if candidate_skill_ids else "automatic"
    requested = list(dict.fromkeys(candidate_skill_ids))
    if conversation.candidate_scope_source != requested_source:
        raise ApiError(409, "chat.candidate_scope_locked")
    if requested_source == "explicit" and set(requested) != set(conversation.candidate_skill_ids):
        raise ApiError(409, "chat.candidate_scope_locked")


def _validate_compatibility_scope(
    db: Session,
    conversation_id: str | None,
    candidate_skill_ids: list[int],
    model: str,
    *,
    scope_supplied: bool,
) -> None:
    if conversation_id is None:
        return
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.deleted_at is not None:
        return
    selected_skill_id = candidate_skill_ids[0] if model.startswith("skill-") else None
    if conversation.skill_id != selected_skill_id:
        raise ApiError(409, "chat.candidate_scope_locked")
    _validate_conversation_scope(
        db,
        conversation_id,
        candidate_skill_ids,
        scope_supplied=scope_supplied,
    )


def _browser_agent_id(db: Session, payload: ChatTurnRequest) -> int:
    if payload.conversation_id is None:
        if payload.agent_id is None:
            raise ApiError(422, "validation.invalid", fields=["body.agent_id"])
        return payload.agent_id
    conversation = db.get(Conversation, payload.conversation_id)
    if conversation is None or conversation.deleted_at is not None:
        raise ApiError(404, "agent.conversation_not_found")
    if payload.agent_id is not None and payload.agent_id != conversation.agent_id:
        raise ApiError(409, "chat.agent_locked")
    return conversation.agent_id


async def _run_agent(
    turn: AgentTurnRequest,
    db: Session,
    cipher: SecretCipher,
    llm: LlmClient,
    executor: ToolExecutor,
) -> AgentTurnResult:
    try:
        return await AgentRuntime(db, cipher, llm, executor).run(turn)
    except AgentError as exc:
        raise _agent_error(exc) from exc
    except LlmProviderError as exc:
        raise ApiError(409, "chat.failed", reason=str(exc)) from exc


async def _run(
    body: dict[str, Any],
    request: Request,
    db: Session,
    cipher: SecretCipher,
    llm: LlmClient,
    executor: ToolExecutor,
    chat4openapi_tool_session_header: str | None,
    legacy_tool_session_header: str | None,
    key_context: AgentKeyContext,
    *,
    anthropic: bool,
):
    model = body.get("model", "")
    conversation_id = body.get("conversation_id")
    conversation = None
    if conversation_id is not None:
        conversation = db.get(Conversation, conversation_id)
        if (
            conversation is None
            or conversation.deleted_at is not None
            or conversation.agent_id != key_context.agent.id
        ):
            raise ApiError(404, "agent.conversation_not_found")
    candidate_skill_ids = _candidate_skill_ids(body, key_context, conversation)
    _validate_compatibility_scope(
        db,
        conversation_id,
        candidate_skill_ids,
        model,
        scope_supplied=(model.startswith("skill-") or bool(body.get("chat4openapi_skill_ids"))),
    )
    result = await _run_agent(
        AgentTurnRequest(
            user_content=_latest_user_content(body),
            candidate_skill_ids=candidate_skill_ids,
            interactive=False,
            conversation_id=conversation_id,
            tool_session_id=_session_id(
                body,
                request,
                chat4openapi_tool_session_header,
                legacy_tool_session_header,
            ),
            incoming_messages=_incoming_messages(body, anthropic=anthropic),
            candidate_scope_source=(
                "explicit"
                if model.startswith("skill-") or bool(body.get("chat4openapi_skill_ids"))
                else "automatic"
            ),
            agent_id=key_context.agent.id,
        ),
        db,
        cipher,
        llm,
        executor,
    )
    if conversation_id is None:
        conversation = db.get(Conversation, result.conversation_id)
        if conversation is not None:
            conversation.skill_id = candidate_skill_ids[0] if model.startswith("skill-") else None
            db.commit()
    return result


@router.post("/api/chat/turns", response_model=ChatTurnResponse)
async def browser_turn(
    payload: ChatTurnRequest,
    request: Request,
    chat4openapi_tool_session_header: str | None = Header(
        default=None, alias="X-Chat4Openapi-Tool-Session"
    ),
    legacy_tool_session_header: str | None = Header(default=None, alias="X-Tool-Session-ID"),
    db: Session = Depends(get_db_session),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
    llm: LlmClient = Depends(get_llm_client),
    executor: ToolExecutor = Depends(get_tool_executor),
) -> ChatTurnResponse:
    agent_id = _browser_agent_id(db, payload)
    result = await _run_agent(
        AgentTurnRequest(
            agent_id=agent_id,
            user_content=payload.message,
            candidate_skill_ids=[],
            interactive=True,
            conversation_id=payload.conversation_id,
            tool_session_id=(
                chat4openapi_tool_session_header
                or legacy_tool_session_header
                or request.cookies.get(TOOL_SESSION_COOKIE)
            ),
            candidate_scope_source="automatic",
        ),
        db,
        cipher,
        llm,
        executor,
    )
    return ChatTurnResponse(
        status=result.status,
        conversation_id=result.conversation_id,
        message=result.content,
        loaded_skill_ids=result.loaded_skill_ids,
        pending=result.pending,
    )


@router.get("/v1/models")
def models(
    context: AgentKeyContext = Depends(require_agent_api_key),
) -> dict[str, Any]:
    skills = context.db.scalars(
        select(Skill)
        .join(AgentSkill, AgentSkill.skill_id == Skill.id)
        .where(Skill.running.is_(True), Skill.deleted_at.is_(None))
        .where(AgentSkill.agent_id == context.agent.id)
        .order_by(AgentSkill.position, Skill.id)
    ).all()
    generic = {
        "id": "agent-default",
        "object": "model",
        "created": 0,
        "owned_by": "chat4openapi",
        "name": context.agent.name,
        "description": "Built-in Agent with automatic Skill routing.",
    }
    return {
        "object": "list",
        "data": [
            generic,
            {
                **generic,
                "id": f"agent-{context.agent.id}",
                "description": "Built-in Agent selected by this API key.",
            },
        ]
        + [
            {
                "id": f"skill-{skill.id}",
                "object": "model",
                "created": int(skill.created_at.timestamp()) if skill.created_at else 0,
                "owned_by": "chat4openapi",
                "name": skill.name,
                "description": (f"Built-in Agent restricted to candidate Skill {skill.name}."),
            }
            for skill in skills
        ],
    }


@router.post("/v1/chat/completions")
async def openai_chat(
    body: dict[str, Any],
    request: Request,
    key_context: AgentKeyContext = Depends(require_agent_api_key),
    chat4openapi_tool_session_header: str | None = Header(
        default=None, alias="X-Chat4Openapi-Tool-Session"
    ),
    legacy_tool_session_header: str | None = Header(default=None, alias="X-Tool-Session-ID"),
    db: Session = Depends(get_db_session),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
    llm: LlmClient = Depends(get_llm_client),
    executor: ToolExecutor = Depends(get_tool_executor),
):
    result = await _run(
        body,
        request,
        db,
        cipher,
        llm,
        executor,
        chat4openapi_tool_session_header,
        legacy_tool_session_header,
        key_context,
        anthropic=False,
    )
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model = body["model"]
    if body.get("stream"):
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {"index": 0, "delta": {"content": result.content}, "finish_reason": "stop"}
            ],
        }

        async def events():
            yield f"data: {json.dumps(chunk, ensure_ascii=False, separators=(',', ':'))}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": result.input_tokens,
            "completion_tokens": result.output_tokens,
            "total_tokens": result.input_tokens + result.output_tokens,
        },
        "chat4openapi_conversation_id": result.conversation_id,
    }


@router.post("/v1/messages")
async def anthropic_messages(
    body: dict[str, Any],
    request: Request,
    key_context: AgentKeyContext = Depends(require_agent_api_key),
    chat4openapi_tool_session_header: str | None = Header(
        default=None, alias="X-Chat4Openapi-Tool-Session"
    ),
    legacy_tool_session_header: str | None = Header(default=None, alias="X-Tool-Session-ID"),
    db: Session = Depends(get_db_session),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
    llm: LlmClient = Depends(get_llm_client),
    executor: ToolExecutor = Depends(get_tool_executor),
):
    result = await _run(
        body,
        request,
        db,
        cipher,
        llm,
        executor,
        chat4openapi_tool_session_header,
        legacy_tool_session_header,
        key_context,
        anthropic=True,
    )
    message_id = f"msg_{uuid.uuid4().hex}"
    if body.get("stream"):
        start = {
            "type": "message_start",
            "message": {"id": message_id, "type": "message", "role": "assistant"},
        }
        delta = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": result.content},
        }

        async def events():
            yield f"event: message_start\ndata: {json.dumps(start, separators=(',', ':'))}\n\n"
            yield f"event: content_block_delta\ndata: {json.dumps(delta, ensure_ascii=False, separators=(',', ':'))}\n\n"
            yield 'event: message_stop\ndata: {"type":"message_stop"}\n\n'

        return StreamingResponse(events(), media_type="text/event-stream")
    return {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "model": body["model"],
        "content": [{"type": "text", "text": result.content}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        },
        "chat4openapi_conversation_id": result.conversation_id,
    }
