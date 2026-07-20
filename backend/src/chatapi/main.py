from fastapi import FastAPI

from chatapi.api.admin_auth import router as admin_auth_router
from chatapi.api.errors import install_error_handlers
from chatapi.api.health import router as health_router
from chatapi.api.setup import router as setup_router


def create_app() -> FastAPI:
    app = FastAPI(title="ChatAPI", version="0.1.0")
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(setup_router)
    app.include_router(admin_auth_router)
    return app


app = create_app()
