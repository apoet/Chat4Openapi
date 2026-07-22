from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from chat4openapi.agui.contracts import AguiRunInput
from chat4openapi.agui.events import encode_sse
from chat4openapi.agui.runtime import AguiRuntime
from chat4openapi.api.embed_public import _bearer, _unavailable
from chat4openapi.api.tool_sessions import get_tool_executor, get_tool_secret_cipher
from chat4openapi.chat.agent import AgentRuntime
from chat4openapi.chat.api import get_llm_client
from chat4openapi.db.session import get_db_session
from chat4openapi.embed.sessions import EmbedUnavailableError, authenticate_embed_session
from chat4openapi.llm.client import LlmClient
from chat4openapi.models import EmbedSession
from chat4openapi.security.encryption import SecretCipher
from chat4openapi.tools.executor import ToolExecutor

router = APIRouter(tags=["embed-agent"])


def require_embed_session(
    public_id: str,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db_session),
) -> EmbedSession:
    try:
        return authenticate_embed_session(
            db,
            _bearer(authorization),
            public_id=public_id,
        )
    except EmbedUnavailableError as exc:
        raise _unavailable() from exc


def get_agui_runtime(
    db: Session = Depends(get_db_session),
    cipher: SecretCipher = Depends(get_tool_secret_cipher),
    llm: LlmClient = Depends(get_llm_client),
    executor: ToolExecutor = Depends(get_tool_executor),
) -> AguiRuntime:
    return AguiRuntime(AgentRuntime(db, cipher, llm, executor))


@router.post("/api/embed/{public_id}/agent")
async def run_embed_agent(
    payload: AguiRunInput,
    owner: EmbedSession = Depends(require_embed_session),
    runtime: AguiRuntime = Depends(get_agui_runtime),
) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        async for event in runtime.run(payload, owner):
            yield encode_sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
