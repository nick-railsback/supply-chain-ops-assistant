"""Tests for rule-based query interpreter (Story 15.6)."""

import pytest

from agent.query_interpreter import _rule_based_interpret, interpret_query
from models.shared import TargetSystem, UserIntent


# ---------------------------------------------------------------------------
# _rule_based_interpret tests
# ---------------------------------------------------------------------------


class TestRuleBasedInterpret:
    def test_show_all_orders(self):
        plan = _rule_based_interpret("show all orders")
        assert plan is not None
        assert plan.intent == UserIntent.STATUS_CHECK
        assert TargetSystem.OMS in plan.target_systems
        assert plan.primary_entity == "order"

    def test_list_pending_orders(self):
        plan = _rule_based_interpret("what orders are pending")
        assert plan is not None
        assert plan.intent == UserIntent.STATUS_CHECK
        assert TargetSystem.OMS in plan.target_systems
        assert any(f.field == "status" and f.value == "pending" for f in plan.filters)

    def test_at_risk_orders(self):
        plan = _rule_based_interpret("which orders are at-risk")
        assert plan is not None
        assert plan.intent == UserIntent.STATUS_CHECK
        assert TargetSystem.OMS in plan.target_systems
        assert any(f.field == "at_risk" and f.value is True for f in plan.filters)

    def test_show_exceptions(self):
        plan = _rule_based_interpret("show all exceptions")
        assert plan is not None
        assert plan.intent == UserIntent.STATUS_CHECK
        assert TargetSystem.OMS in plan.target_systems
        assert plan.primary_entity == "exception"

    def test_list_inventory(self):
        plan = _rule_based_interpret("list inventory levels")
        assert plan is not None
        assert plan.intent == UserIntent.STATUS_CHECK
        assert TargetSystem.WMS in plan.target_systems
        assert plan.primary_entity == "inventory"

    def test_low_stock(self):
        plan = _rule_based_interpret("what items are low stock")
        assert plan is not None
        assert plan.intent == UserIntent.STATUS_CHECK
        assert TargetSystem.WMS in plan.target_systems
        assert any(
            f.field == "below_reorder_point" and f.value is True for f in plan.filters
        )

    def test_show_shipments(self):
        plan = _rule_based_interpret("show shipments")
        assert plan is not None
        assert plan.intent == UserIntent.STATUS_CHECK
        assert TargetSystem.TMS in plan.target_systems
        assert plan.primary_entity == "shipment"

    def test_sla_breaches(self):
        plan = _rule_based_interpret("show sla breaches")
        assert plan is not None
        assert plan.intent == UserIntent.STATUS_CHECK
        assert TargetSystem.TMS in plan.target_systems
        assert any(
            f.field == "sla_status" and f.value == "breached" for f in plan.filters
        )

    def test_cross_system_orders_shipments(self):
        plan = _rule_based_interpret("correlate orders with shipments data")
        assert plan is not None
        assert plan.intent == UserIntent.CROSS_SYSTEM_QUERY
        assert TargetSystem.OMS in plan.target_systems
        assert TargetSystem.TMS in plan.target_systems
        assert plan.requires_join is True
        assert plan.join_key == "order_id"

    def test_unmatched_returns_none(self):
        plan = _rule_based_interpret("xyzzy plugh foo bar")
        assert plan is None


# ---------------------------------------------------------------------------
# interpret_query (async public API) tests
# ---------------------------------------------------------------------------


class TestInterpretQuery:
    async def test_interpret_query_clarification(self):
        """Unmatched query returns CLARIFICATION_NEEDED."""
        plan = await interpret_query("xyzzy plugh foo bar", [])
        assert plan.intent == UserIntent.CLARIFICATION_NEEDED
        assert plan.confidence < 0.5
