"""Tests for C5 observability: token usage + latency on the interpret path.

``structured_call`` already returns token usage; C5 threads it (plus wall-clock
latency) onto the QueryPlan so it is logged and shown in the reasoning panel.
"""

from unittest.mock import AsyncMock, patch

from rich.console import Console

from agent.copilot import Copilot
from agent.query_interpreter import llm_interpret
from cli.interactive import render_reasoning_panel
from models.query import QueryPlan, QueryResult
from models.shared import TargetSystem, UserIntent

_VALID_TOOL_INPUT = {
    "intent": "status_check",
    "target_systems": ["oms"],
    "primary_entity": "order",
    "filters": [],
    "reasoning": "pending orders",
    "signals": {
        "all_filter_fields_known": True,
        "entity_unambiguous": True,
        "single_clear_intent": True,
        "time_reference_resolved": True,
    },
    "model_confidence": 0.9,
}


async def test_llm_interpret_attaches_usage_and_latency():
    """A successful LLM interpretation carries token usage and a latency reading."""
    call = AsyncMock(return_value=(_VALID_TOOL_INPUT, {"input_tokens": 100, "output_tokens": 30}))
    with patch("agent.query_interpreter.structured_call", call):
        plan = await llm_interpret("show pending orders", [])

    assert plan.input_tokens == 100
    assert plan.output_tokens == 30
    assert plan.latency_ms is not None and plan.latency_ms >= 0


def test_reasoning_panel_shows_tokens_and_latency():
    """When the plan carries usage/latency, the panel surfaces them."""
    plan = QueryPlan(
        intent=UserIntent.STATUS_CHECK,
        target_systems=[TargetSystem.OMS],
        primary_entity="order",
        confidence=0.9,
        reasoning="pending orders",
        interpretation_source="llm",
        input_tokens=120,
        output_tokens=45,
        latency_ms=830.0,
    )
    console = Console(width=240)
    with console.capture() as capture:
        console.print(render_reasoning_panel(plan, "execute", errors=[]))
    text = capture.get()

    assert "120" in text  # input tokens
    assert "45" in text  # output tokens
    assert "830" in text  # latency ms


async def test_process_query_starts_a_fresh_trace():
    """Each turn opens its own trace, so one turn == one trace id across the
    three services (the CLI previously never started a trace at all)."""
    import config.logging as clog

    plan = QueryPlan(
        intent=UserIntent.STATUS_CHECK,
        target_systems=[TargetSystem.OMS],
        primary_entity="order",
        filters=[],
        confidence=0.9,
        reasoning="orders",
    )
    res = QueryResult(data=[], total_count=0, systems_queried=[TargetSystem.OMS])
    copilot = Copilot()
    with (
        patch("agent.copilot.interpret_query", AsyncMock(return_value=plan)),
        patch("agent.copilot.execute_query", AsyncMock(return_value=res)),
    ):
        await copilot.process_query("show all orders")
        first = clog.trace_id_var.get()
        await copilot.process_query("show all orders")
        second = clog.trace_id_var.get()

    assert first is not None
    assert second is not None
    assert first != second


def test_reasoning_panel_omits_usage_when_absent():
    """Rule-based turns (no usage) don't render an empty/garbled usage line."""
    plan = QueryPlan(
        intent=UserIntent.STATUS_CHECK,
        target_systems=[TargetSystem.OMS],
        primary_entity="order",
        confidence=0.75,
        reasoning="rule match",
        interpretation_source="rule_based",
    )
    console = Console(width=240)
    with console.capture() as capture:
        console.print(render_reasoning_panel(plan, "execute", errors=[]))
    text = capture.get()

    assert "Tokens" not in text
