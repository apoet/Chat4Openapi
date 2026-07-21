from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from chatapi.api.admin_auth import router as admin_auth_router
from chatapi.api.admin_tools import router as admin_tools_router
from chatapi.api.admin_providers import router as admin_providers_router
from chatapi.api.admin_skills import router as admin_skills_router
from chatapi.api.errors import install_error_handlers
from chatapi.api.health import router as health_router
from chatapi.api.setup import router as setup_router
from chatapi.api.tool_sessions import router as tool_sessions_router
from chatapi.config import get_settings
from chatapi.chat.api import router as chat_router
from chatapi.db.session import SessionLocal
from chatapi.mcp.runtime import create_mcp_server
from chatapi.security.encryption import load_secret_cipher
from chatapi.tools.executor import ToolExecutor


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

    app = FastAPI(title="ChatAPI", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(setup_router)
    app.include_router(admin_auth_router)
    app.include_router(admin_tools_router)
    app.include_router(admin_providers_router)
    app.include_router(admin_skills_router)
    app.include_router(tool_sessions_router)
    app.include_router(chat_router)
    app.mount("/mcp", mcp_http_app, name="mcp")

    dist = frontend_dist or Path(__file__).resolve().parents[3] / "frontend" / "dist"
    index_file = dist / "index.html"
    assets = dist / "assets"
    if index_file.is_file() and assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa_fallback(path: str) -> FileResponse:
            reserved = ("api/", "v1/", "anthropic/")
            if path == "health" or path.startswith(reserved):
                raise HTTPException(status_code=404)
            return FileResponse(index_file)

    return app


app = create_app()
