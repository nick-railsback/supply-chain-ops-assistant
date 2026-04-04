"""FastAPI service factory with shared middleware and utilities."""

from __future__ import annotations

from typing import Any, TypeVar

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config.settings import get_settings
from models.shared import PaginatedResponse
from services.middleware import TraceMiddleware

T = TypeVar("T", bound=BaseModel)

_WRITE_METHODS = {"PATCH", "POST", "PUT", "DELETE"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Validates X-API-Key header on state-changing requests."""

    def __init__(self, app: FastAPI, api_secret_key: str) -> None:
        super().__init__(app)
        self._api_secret_key = api_secret_key

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        if request.method in _WRITE_METHODS:
            api_key = request.headers.get("x-api-key")
            if api_key != self._api_secret_key:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "unauthorized",
                        "message": "Invalid or missing API key",
                    },
                )
        return await call_next(request)


def create_app(service_name: str) -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=f"{service_name.upper()} API", version="1.0.0")

    app.add_middleware(TraceMiddleware)
    app.add_middleware(ApiKeyMiddleware, api_secret_key=settings.api_secret_key)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
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


# ---------------------------------------------------------------------------
# Shared filter and pagination utilities
# ---------------------------------------------------------------------------


def apply_filters(
    query: Select[Any],
    count_query: Select[Any],
    filters: list[ColumnElement[bool]],
) -> tuple[Select[Any], Select[Any]]:
    """Apply a list of filter conditions to both the data query and count query."""
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    return query, count_query


async def build_paginated_response(
    session: AsyncSession,
    query: Select[Any],
    count_query: Select[Any],
    model_class: type[T],
    offset: int,
    limit: int,
) -> PaginatedResponse[T]:
    """Execute queries and return a PaginatedResponse."""
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    result = await session.execute(query.offset(offset).limit(limit))
    rows = result.scalars().all()

    return PaginatedResponse[model_class](  # type: ignore[valid-type]
        items=[model_class.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )
