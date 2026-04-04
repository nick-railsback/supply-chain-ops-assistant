"""Structured logging setup with structlog."""

import contextvars
import logging
import uuid
from typing import Any

import structlog

trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)
span_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("span_id", default=None)
parent_span_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "parent_span_id", default=None
)


def new_trace() -> str:
    """Generate a new trace ID and set it in the context."""
    tid = uuid.uuid4().hex[:16]
    trace_id_var.set(tid)
    return tid


def new_span(function_name: str = "") -> str:
    """Generate a new span ID, preserving the current span as parent."""
    current = span_id_var.get()
    if current:
        parent_span_id_var.set(current)
    sid = uuid.uuid4().hex[:12]
    span_id_var.set(sid)
    return sid


def inject_trace_context(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor that injects trace context into every log entry."""
    tid = trace_id_var.get()
    if tid:
        event_dict["trace_id"] = tid
    sid = span_id_var.get()
    if sid:
        event_dict["span_id"] = sid
    psid = parent_span_id_var.get()
    if psid:
        event_dict["parent_span_id"] = psid
    return event_dict


def setup_logging(log_level: str = "INFO", json_output: bool = True) -> None:
    """Initialize structlog for the application."""
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        inject_trace_context,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
