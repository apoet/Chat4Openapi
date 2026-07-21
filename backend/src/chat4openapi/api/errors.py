from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, **params: Any) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.params = params


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "params": exc.params}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = [".".join(str(part) for part in error["loc"]) for error in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation.invalid", "params": {"fields": fields}}},
        )
