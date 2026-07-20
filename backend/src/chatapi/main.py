from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from chatapi.api.admin_auth import router as admin_auth_router
from chatapi.api.errors import install_error_handlers
from chatapi.api.health import router as health_router
from chatapi.api.setup import router as setup_router


def create_app(frontend_dist: Path | None = None) -> FastAPI:
    app = FastAPI(title="ChatAPI", version="0.1.0")
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(setup_router)
    app.include_router(admin_auth_router)

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
