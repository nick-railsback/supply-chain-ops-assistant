"""FastAPI service factory with shared middleware."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from services.middleware import TraceMiddleware


def create_app(service_name: str) -> FastAPI:
    app = FastAPI(title=f"{service_name.upper()} API", version="1.0.0")

    app.add_middleware(TraceMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": service_name}

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
        detail = getattr(exc, "detail", str(exc))
        return JSONResponse(status_code=404, content={"detail": str(detail)})

    return app
