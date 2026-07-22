from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from chat4openapi.api.admin_agents import router as admin_agents_router
from chat4openapi.api.admin_embeds import router as admin_embeds_router
from chat4openapi.api.agent_keys import router as agent_keys_router
from chat4openapi.api.admin_auth import router as admin_auth_router
from chat4openapi.api.admin_tools import router as admin_tools_router
from chat4openapi.api.admin_providers import router as admin_providers_router
from chat4openapi.api.admin_skills import router as admin_skills_router
from chat4openapi.api.admin_settings import router as admin_settings_router
from chat4openapi.api.errors import install_error_handlers
from chat4openapi.api.embed_public import router as embed_public_router
from chat4openapi.api.embed_agent import router as embed_agent_router
from chat4openapi.api.health import router as health_router
from chat4openapi.api.setup import router as setup_router
from chat4openapi.api.tool_sessions import router as tool_sessions_router
from chat4openapi.api.tool_oauth import router as tool_oauth_router
from chat4openapi.config import get_settings
from chat4openapi.chat.api import router as chat_router
from chat4openapi.db.session import SessionLocal
from chat4openapi.mcp.runtime import create_mcp_server
from chat4openapi.security.encryption import load_secret_cipher
from chat4openapi.tools.executor import ToolExecutor


def create_app(frontend_dist: Path | None = None) -> FastAPI:
    def cipher_factory():
        settings = get_settings()
        return load_secret_cipher(settings.encryption_key, settings.encryption_key_file)

    mcp_server = create_mcp_server(SessionLocal, cipher_factory, ToolExecutor())
    mcp_http_app = mcp_server.http_app(path="/", stateless_http=True)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with mcp_http_app.lifespan(mcp_http_app):
            yield

    app = FastAPI(title="Chat4Openapi", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(setup_router)
    app.include_router(admin_auth_router)
    app.include_router(admin_agents_router)
    app.include_router(admin_embeds_router)
    app.include_router(agent_keys_router)
    app.include_router(admin_tools_router)
    app.include_router(admin_providers_router)
    app.include_router(admin_skills_router)
    app.include_router(admin_settings_router)
    app.include_router(tool_sessions_router)
    app.include_router(tool_oauth_router)
    app.include_router(chat_router)
    app.include_router(embed_agent_router)
    app.include_router(embed_public_router)
    app.mount("/mcp", mcp_http_app, name="mcp")

    dist = frontend_dist or Path(__file__).resolve().parents[3] / "frontend" / "dist"
    index_file = dist / "index.html"
    assets = dist / "assets"
    if index_file.is_file() and assets.is_dir():
        app.state.frontend_index = index_file
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa_fallback(path: str) -> FileResponse:
            reserved = ("api/", "v1/", "anthropic/")
            if path == "health" or path.startswith(reserved):
                raise HTTPException(status_code=404)
            return FileResponse(index_file)

    return app


app = create_app()
