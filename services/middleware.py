"""Trace middleware for X-Trace-ID/X-Span-ID header propagation."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config.logging import new_span, new_trace, span_id_var, trace_id_var


class TraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        trace_id = request.headers.get("x-trace-id") or new_trace()
        span_id = request.headers.get("x-span-id") or new_span()
        trace_id_var.set(trace_id)
        span_id_var.set(span_id)
        response = await call_next(request)
        response.headers["x-trace-id"] = trace_id
        return response
