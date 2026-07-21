import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from chatapi.api.errors import ApiError
from chatapi.api.tool_sessions import (
    TOOL_SESSION_COOKIE,
    get_tool_executor,
    get_tool_secret_cipher,
)
from chatapi.chat.orchestrator import ChatError, ChatOrchestrator
from chatapi.db.session import get_db_session
from chatapi.llm.client import LlmClient, LlmProviderError
from chatapi.models import Skill
from chatapi.security.encryption import SecretCipher
from chatapi.tools.executor import ToolExecutor

router = APIRouter(tags=["compatible-chat"])


def get_llm_client() -> LlmClient:
    return LlmClient()


def _skill_id(model: str) -> int:
    if not model.startswith("skill-"):
        raise ApiError(404, "chat.skill_not_found")
    try:
        return int(model.removeprefix("skill-"))
    except ValueError as exc:
        raise ApiError(404, "chat.skill_not_found") from exc


def _session_id(body: dict[str, Any], request: Request, header: str | None) -> str | None:
    return body.get("tool_session_id") or header or request.cookies.get(TOOL_SESSION_COOKIE)


async def _run(
    body: dict[str, Any],
    request: Request,
    db: Session,
    cipher: SecretCipher,
    llm: LlmClient,
    executor: ToolExecutor,
    tool_session_header: str | None,
):
    messages = list(body.get("messages", []))
    system = body.get("system")
    if system:
        if isinstance(system, list):
            system = "\n".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in system
            )
        messages.insert(0, {"role": "system", "content": system})
    try:
        return await ChatOrchestrator(db, cipher, llm, executor).run(
            skill_id=_skill_id(body.get("model", "")),
            messages=messages,
            tool_session_id=_session_id(body, request, tool_session_header),
            conversation_id=body.get("conversation_id"),
        )
    except (ChatError, LlmProviderError) as exc:
        raise ApiError(409, "chat.failed", reason=str(exc)) from exc


@router.get("/v1/models")
def models(db: Session = Depends(get_db_session)) -> dict[str, Any]:
    skills = db.scalars(
        select(Skill)
        .where(Skill.running.is_(True), Skill.deleted_at.is_(None))
        .order_by(Skill.id)
    ).all()
    return {
        "object": "list",
        "data": [
            {
                "id": f"skill-{skill.id}",
                "object": "model",
                "created": int(skill.created_at.timestamp()) if skill.created_at else 0,
                "owned_by": "chatapi",
                "name": skill.name,
            }
            for skill in skills
        ],
    }


@router.post("/v1/chat/completions")
async def openai_chat(
    body: dict[str, Any],
    request: Request,
    tool_session_header: str | None = Header(default=None, alias="X-Tool-Session-ID"),
    db: Session = Depends(get_db_session),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
    llm: LlmClient = Depends(get_llm_client),
    executor: ToolExecutor = Depends(get_tool_executor),
):
    result = await _run(body, request, db, cipher, llm, executor, tool_session_header)
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
        "chatapi_conversation_id": result.conversation_id,
    }


@router.post("/v1/messages")
async def anthropic_messages(
    body: dict[str, Any],
    request: Request,
    tool_session_header: str | None = Header(default=None, alias="X-Tool-Session-ID"),
    db: Session = Depends(get_db_session),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
    llm: LlmClient = Depends(get_llm_client),
    executor: ToolExecutor = Depends(get_tool_executor),
):
    result = await _run(body, request, db, cipher, llm, executor, tool_session_header)
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
        "chatapi_conversation_id": result.conversation_id,
    }
