"""Partial-backend-failure surfacing (UX-1).

``execute_query`` already produces ``partial_failure`` / ``error_details`` when
one backend is down, but nothing consumed them: a dead system rendered as a
clean empty "No results found" with status success. These tests pin that a
partial failure is reported as such, both in the copilot envelope and in the
CLI render.
"""

from unittest.mock import AsyncMock, patch

from rich.console import Console

from agent.copilot import Copilot
from cli.interactive import InteractiveCLI
from models.query import QueryPlan, QueryResult
from models.shared import TargetSystem, UserIntent


def _cross_system_plan() -> QueryPlan:
    return QueryPlan(
        intent=UserIntent.CROSS_SYSTEM_QUERY,
        target_systems=[TargetSystem.OMS, TargetSystem.TMS],
        primary_entity="order",
        filters=[],
        confidence=0.9,
        reasoning="orders with shipments",
        requires_join=True,
        join_key="order_id",
    )


async def test_process_query_reports_partial_status():
    partial = QueryResult(
        data=[],
        total_count=0,
        systems_queried=[TargetSystem.OMS, TargetSystem.TMS],
        partial_failure=True,
        error_details={"tms": "Service tms unavailable: boom"},
    )
    copilot = Copilot()
    with (
        patch("agent.copilot.interpret_query", AsyncMock(return_value=_cross_system_plan())),
        patch("agent.copilot.execute_query", AsyncMock(return_value=partial)),
    ):
        result = await copilot.process_query("orders with shipments")

    assert result["status"] == "partial"
    assert "tms" in result["message"]


class _FakeCopilot:
    def __init__(self, envelope: dict) -> None:
        self._envelope = envelope

    async def process_query(self, query: str) -> dict:
        return self._envelope


def _envelope(result: QueryResult, status: str) -> dict:
    return {
        "status": status,
        "plan": None,
        "routing": "execute",
        "message": "msg",
        "data": result.model_dump(),
        "errors": [],
    }


async def test_cli_renders_unreachable_systems():
    result = QueryResult(
        data=[],
        total_count=0,
        systems_queried=[TargetSystem.OMS, TargetSystem.TMS],
        partial_failure=True,
        error_details={"tms": "Service tms unavailable: boom"},
    )
    cli = InteractiveCLI()
    cli.copilot = _FakeCopilot(_envelope(result, "partial"))  # type: ignore[assignment]
    cli.show_reasoning = False
    console = Console(width=240)
    cli.console = console
    with console.capture() as capture:
        await cli.handle_query("orders with shipments")
    text = capture.get()

    assert "TMS unreachable" in text
    assert "No results found" not in text


async def test_cli_clean_empty_still_says_no_results():
    result = QueryResult(
        data=[],
        total_count=0,
        systems_queried=[TargetSystem.OMS],
        partial_failure=False,
    )
    cli = InteractiveCLI()
    cli.copilot = _FakeCopilot(_envelope(result, "success"))  # type: ignore[assignment]
    cli.show_reasoning = False
    console = Console(width=240)
    cli.console = console
    with console.capture() as capture:
        await cli.handle_query("show all orders")
    text = capture.get()

    assert "No results found for that query." in text
