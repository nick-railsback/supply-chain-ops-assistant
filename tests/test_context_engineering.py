"""Tests for C3 context engineering.

Covers the offline building blocks of the context work:
  * live enum-value injection into the interpreter system prompt,
  * the exceptions→OMS domain fix,
  * the per-turn plan summary that gives the interpreter referent memory.

The end-to-end behavioral lift (a follow-up resolving "the same ones" without
restating filters) is verified by the eval / demo with a live key.
"""

from unittest.mock import AsyncMock, patch

from agent.copilot import Copilot
from agent.query_interpreter import (
    INTERPRET_SYSTEM_PROMPT,
    _field_value_reference,
    _summarize_plan,
)
from models.query import DataFilter, QueryPlan, QueryResult
from models.shared import TargetSystem, UserIntent


def test_field_value_reference_lists_real_domains():
    """The injected block exposes actual allowed values, sourced from the models/constants."""
    block = _field_value_reference()
    # order status (models.oms.OrderStatus)
    assert "pending" in block and "cancelled" in block
    # carriers (seed.constants.CARRIERS)
    assert "FedEx" in block and "UPS" in block
    # customer tiers, channels
    assert "enterprise" in block and "wholesale_b2b" in block
    # fulfillment centers + sla status
    assert "FC-ATL-01" in block and "breached" in block


def test_system_prompt_maps_exceptions_to_oms():
    """The interpreter prompt now tells the model exceptions live in OMS, with fields."""
    assert "exceptions → oms" in INTERPRET_SYSTEM_PROMPT
    assert "exception_type" in INTERPRET_SYSTEM_PROMPT
    assert "severity" in INTERPRET_SYSTEM_PROMPT


def test_system_prompt_embeds_value_reference():
    """The assembled system prompt carries the live enum-value block."""
    assert _field_value_reference() in INTERPRET_SYSTEM_PROMPT


def test_summarize_plan_with_filters():
    plan = QueryPlan(
        intent=UserIntent.STATUS_CHECK,
        target_systems=[TargetSystem.OMS],
        primary_entity="order",
        filters=[DataFilter(field="status", operator="eq", value="pending")],
        confidence=0.9,
        reasoning="pending orders",
    )
    summary = _summarize_plan(plan)
    assert "status_check" in summary
    assert "oms" in summary
    assert "status" in summary and "pending" in summary


def test_summarize_plan_without_filters():
    plan = QueryPlan(
        intent=UserIntent.STATUS_CHECK,
        target_systems=[TargetSystem.OMS],
        primary_entity="order",
        filters=[],
        confidence=0.9,
        reasoning="all orders",
    )
    assert "no filters" in _summarize_plan(plan)


async def test_copilot_records_interpretation_for_referent_memory():
    """After a turn, the prior plan summary is in history so the next turn can resolve referents."""
    plan = QueryPlan(
        intent=UserIntent.STATUS_CHECK,
        target_systems=[TargetSystem.OMS],
        primary_entity="order",
        filters=[DataFilter(field="status", operator="eq", value="pending")],
        confidence=0.9,
        reasoning="pending orders",
    )
    empty = QueryResult(data=[], total_count=0, systems_queried=[TargetSystem.OMS])

    copilot = Copilot()
    with (
        patch("agent.copilot.interpret_query", AsyncMock(return_value=plan)),
        patch("agent.copilot.execute_query", AsyncMock(return_value=empty)),
    ):
        await copilot.process_query("show pending orders")

    last = copilot.conversation_history[-1]
    assert last["role"] == "assistant"
    assert last["content"] == _summarize_plan(plan)
