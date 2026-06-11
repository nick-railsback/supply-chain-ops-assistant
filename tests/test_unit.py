"""Unit tests for routing, parsing, validation, formatting."""

import pytest

from agent.confidence import ConfidenceRouter, RoutingDecision
from agent.validators import validate_action_proposal, validate_query_plan
from models.action import ActionProposal, ActionType
from models.query import DataFilter, QueryPlan
from models.shared import RiskLevel, TargetSystem, UserIntent


class TestConfidenceRouter:
    def test_execute_high_confidence(self, sample_query_plan):
        router = ConfidenceRouter()
        plan = sample_query_plan(intent=UserIntent.STATUS_CHECK, confidence=0.90)
        assert router.route(plan) == RoutingDecision.EXECUTE

    def test_flag_medium_confidence(self, sample_query_plan):
        router = ConfidenceRouter()
        plan = sample_query_plan(intent=UserIntent.STATUS_CHECK, confidence=0.60)
        assert router.route(plan) == RoutingDecision.EXECUTE_AND_FLAG

    def test_clarify_low_confidence(self, sample_query_plan):
        router = ConfidenceRouter()
        plan = sample_query_plan(intent=UserIntent.STATUS_CHECK, confidence=0.30)
        assert router.route(plan) == RoutingDecision.CLARIFY

    def test_action_request_highest_threshold(self, sample_query_plan):
        router = ConfidenceRouter()
        # 0.85 should be EXECUTE for STATUS_CHECK but EXECUTE_AND_FLAG for ACTION_REQUEST
        plan_status = sample_query_plan(intent=UserIntent.STATUS_CHECK, confidence=0.85)
        plan_action = sample_query_plan(intent=UserIntent.ACTION_REQUEST, confidence=0.85)
        assert router.route(plan_status) == RoutingDecision.EXECUTE
        assert router.route(plan_action) == RoutingDecision.EXECUTE_AND_FLAG

    def test_exactly_at_auto_threshold(self, sample_query_plan):
        router = ConfidenceRouter()
        # status_check auto threshold is 0.75
        plan = sample_query_plan(intent=UserIntent.STATUS_CHECK, confidence=0.75)
        assert router.route(plan) == RoutingDecision.EXECUTE

    def test_exactly_at_flag_threshold(self, sample_query_plan):
        router = ConfidenceRouter()
        # status_check flag threshold is 0.45
        plan = sample_query_plan(intent=UserIntent.STATUS_CHECK, confidence=0.45)
        assert router.route(plan) == RoutingDecision.EXECUTE_AND_FLAG

    def test_clarification_needed_routes_to_clarify(self, sample_query_plan):
        # clarification_needed has no per-intent threshold; routing must not
        # crash looking one up — a clarification plan always asks the user.
        router = ConfidenceRouter()
        plan = sample_query_plan(intent=UserIntent.CLARIFICATION_NEEDED, confidence=0.2)
        assert router.route(plan) == RoutingDecision.CLARIFY


class TestValidation:
    async def test_valid_query_plan_passes(self, sample_query_plan):
        plan = sample_query_plan()
        errors = await validate_query_plan(plan)
        assert errors == []

    async def test_invalid_filter_field(self, sample_query_plan):
        plan = sample_query_plan(
            filters=[DataFilter(field="nonexistent_field", operator="eq", value="test")]
        )
        errors = await validate_query_plan(plan)
        assert any("nonexistent_field" in e for e in errors)

    async def test_bulk_update_cap(self, sample_action_proposal):
        # Over 50 targets should be flagged for BULK_UPDATE action type
        proposal = sample_action_proposal(
            action_type=ActionType.BULK_UPDATE,
            target_ids=[f"EXC-{i:04d}" for i in range(60)],
        )
        errors = await validate_action_proposal(proposal)
        assert any("bulk" in e.lower() or "cap" in e.lower() or "50" in e for e in errors)

    async def test_cap_applies_to_all_action_types(self, sample_action_proposal):
        # The cap is not bulk-only: 51 targets fails for FLAG_SHIPMENTS too;
        # exactly 50 passes (boundary).
        over = sample_action_proposal(
            action_type=ActionType.FLAG_SHIPMENTS,
            target_ids=[f"SHP-{i:08d}-00001" for i in range(51)],
        )
        at_cap = sample_action_proposal(
            action_type=ActionType.FLAG_SHIPMENTS,
            target_ids=[f"SHP-{i:08d}-00001" for i in range(50)],
        )
        over_errors = await validate_action_proposal(over)
        assert over_errors != []
        assert all("cap" in e.lower() or "50" in e for e in over_errors)
        assert await validate_action_proposal(at_cap) == []

    async def test_cross_system_requires_join_key(self, sample_query_plan):
        plan = sample_query_plan(
            target_systems=[TargetSystem.OMS, TargetSystem.WMS],
            requires_join=True,
        )
        errors = await validate_query_plan(plan)
        assert any("join_key" in e for e in errors)

    async def test_empty_target_ids_rejected(self):
        proposal = ActionProposal(
            action_type=ActionType.UPDATE_EXCEPTION,
            target_ids=[],
            changes={"status": "resolved"},
            reasoning="Test",
            impact_summary="Test",
            risk_level=RiskLevel.LOW,
        )
        errors = await validate_action_proposal(proposal)
        assert any("target_id" in e.lower() for e in errors)

    async def test_valid_action_proposal_passes(self, sample_action_proposal):
        proposal = sample_action_proposal()
        errors = await validate_action_proposal(proposal)
        assert errors == []

    async def test_changes_outside_patch_contract_rejected(self, sample_action_proposal):
        """A change the service's PATCH contract forbids fails validation here,
        before the operator is asked to confirm an action that can only 422."""
        proposal = sample_action_proposal(
            action_type=ActionType.UPDATE_EXCEPTION,
            changes={"severity": "low"},
        )
        errors = await validate_action_proposal(proposal)
        assert len(errors) == 1
        assert "severity" in errors[0]
        assert "assigned_to" in errors[0] and "status" in errors[0]  # the allowed set

    async def test_flag_shipments_unknown_change_rejected(self, sample_action_proposal):
        proposal = sample_action_proposal(
            action_type=ActionType.FLAG_SHIPMENTS,
            target_ids=["SHP-20250301-00001"],
            changes={"carrier": "FedEx"},
        )
        errors = await validate_action_proposal(proposal)
        assert any("carrier" in e for e in errors)

    async def test_bulk_update_validates_changes_per_target_entity(
        self, sample_action_proposal
    ):
        """notes is patchable on orders but not shipments; a bulk update over
        both entities is rejected for the entity that can't express it."""
        proposal = sample_action_proposal(
            action_type=ActionType.BULK_UPDATE,
            target_ids=["ORD-2025-000001", "SHP-20250301-00001"],
            changes={"notes": "expedite"},
        )
        errors = await validate_action_proposal(proposal)
        assert len(errors) == 1
        assert "shipment" in errors[0]

    async def test_patchable_changes_pass(self, sample_action_proposal):
        proposal = sample_action_proposal(
            action_type=ActionType.ASSIGN_EXCEPTION,
            changes={"assigned_to": "Sarah Chen"},
        )
        assert await validate_action_proposal(proposal) == []

    async def test_oms_exception_filter_fields_validate(self, sample_query_plan):
        """Exception fields validate when the plan actually queries exceptions
        (the dispatcher branches to list_exceptions on primary_entity)."""
        plan = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            primary_entity="exception",
            filters=[
                DataFilter(field="severity", operator="eq", value="critical"),
                DataFilter(field="date_from", operator="gte", value="2026-01-01"),
            ],
        )
        errors = await validate_query_plan(plan)
        assert errors == []

    async def test_cross_entity_filter_rejected(self, sample_query_plan):
        """An exception field on an order-entity plan is rejected: the order
        dispatch branch never reads it, so passing validation would mean the
        unfiltered order list is returned as the 'filtered' answer."""
        plan = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            primary_entity="order",
            filters=[DataFilter(field="severity", operator="eq", value="critical")],
        )
        errors = await validate_query_plan(plan)
        assert len(errors) == 1
        assert "severity" in errors[0]
        assert "exception" in errors[0]  # hint at the entity that has the field

    async def test_cross_entity_date_filter_rejected(self, sample_query_plan):
        plan = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            primary_entity="order",
            filters=[DataFilter(field="date_from", operator="gte", value="2026-01-01")],
        )
        errors = await validate_query_plan(plan)
        assert any("date_from" in e for e in errors)

    async def test_cross_system_join_filters_validate_per_system(self, sample_query_plan):
        """A join plan carries one primary_entity, but each system dispatches
        its own entity (TMS always queries shipments) — a shipment field on an
        order-entity join plan must keep validating."""
        plan = sample_query_plan(
            target_systems=[TargetSystem.OMS, TargetSystem.TMS],
            primary_entity="order",
            requires_join=True,
            join_key="order_id",
            filters=[DataFilter(field="sla_status", operator="eq", value="breached")],
        )
        errors = await validate_query_plan(plan)
        assert errors == []

    async def test_negated_boolean_filter_rejected(self, sample_query_plan):
        """The backends can only select the positive (at-risk orders, low
        stock); a value=False filter would execute as 'no filter at all' and
        present the full list as the negated answer — reject it instead."""
        plan = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            primary_entity="order",
            filters=[DataFilter(field="at_risk", operator="eq", value=False)],
        )
        errors = await validate_query_plan(plan)
        assert len(errors) == 1
        assert "at_risk" in errors[0]
        assert "true" in errors[0].lower()

    async def test_negated_low_stock_filter_rejected(self, sample_query_plan):
        plan = sample_query_plan(
            target_systems=[TargetSystem.WMS],
            primary_entity="inventory",
            filters=[DataFilter(field="below_reorder_point", operator="eq", value=False)],
        )
        errors = await validate_query_plan(plan)
        assert any("below_reorder_point" in e for e in errors)

    async def test_positive_boolean_filter_still_valid(self, sample_query_plan):
        plan = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            primary_entity="order",
            filters=[DataFilter(field="at_risk", operator="eq", value=True)],
        )
        assert await validate_query_plan(plan) == []

    async def test_plural_entity_spelling_resolves_to_orders(self, sample_query_plan):
        """The interpreter and fixtures spell the entity both 'order' and
        'orders'; the dispatcher treats anything that isn't 'exception' as
        orders, and validation must agree."""
        plan = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            primary_entity="orders",
            filters=[DataFilter(field="channel", operator="eq", value="web")],
        )
        assert await validate_query_plan(plan) == []

    async def test_unknown_oms_field_still_rejected(self, sample_query_plan):
        """A field that exists under no OMS entity is still flagged."""
        plan = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            filters=[DataFilter(field="not_a_real_field", operator="eq", value="x")],
        )
        errors = await validate_query_plan(plan)
        assert any("not_a_real_field" in e for e in errors)

    async def test_at_risk_filter_field_validates(self, sample_query_plan):
        """The rule interpreter emits DataFilter(field='at_risk') for at-risk
        queries; the OMS order schema must accept it, or validation rejects the
        plan before the at_risk dispatch branch can run."""
        plan = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            filters=[DataFilter(field="at_risk", operator="eq", value=True)],
        )
        errors = await validate_query_plan(plan)
        assert errors == []

    async def test_unmapped_field_rejected(self, sample_query_plan):
        """A field the registry knows but the dispatcher never executes (priority)
        is rejected, not silently dropped."""
        plan = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            filters=[DataFilter(field="priority", operator="eq", value="urgent")],
        )
        errors = await validate_query_plan(plan)
        assert any("cannot be executed" in e for e in errors)

    async def test_unexecutable_operator_rejected(self, sample_query_plan):
        """status passes the type check for 'in', but the dispatcher only honors
        'eq', so 'in' must be rejected."""
        plan = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            filters=[DataFilter(field="status", operator="in", value=["pending", "processing"])],
        )
        errors = await validate_query_plan(plan)
        assert any("not executable" in e for e in errors)

    async def test_order_value_gte_accepted_eq_rejected(self, sample_query_plan):
        """order_value dispatches as min_value (a >= floor); only gte is honest."""
        ok = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            filters=[DataFilter(field="order_value", operator="gte", value=100)],
        )
        bad = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            filters=[DataFilter(field="order_value", operator="eq", value=100)],
        )
        assert await validate_query_plan(ok) == []
        assert await validate_query_plan(bad) != []

    async def test_dispatchable_eq_filters_still_pass(self, sample_query_plan):
        """The shortcut/eq filters the dispatcher really executes still validate."""
        oms_exc = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            primary_entity="exception",
            filters=[DataFilter(field="severity", operator="eq", value="critical")],
        )
        oms_ord = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            primary_entity="order",
            filters=[DataFilter(field="at_risk", operator="eq", value=True)],
        )
        tms = sample_query_plan(
            target_systems=[TargetSystem.TMS],
            filters=[DataFilter(field="sla_status", operator="eq", value="breached")],
        )
        assert await validate_query_plan(oms_exc) == []
        assert await validate_query_plan(oms_ord) == []
        assert await validate_query_plan(tms) == []


class TestPydanticModels:
    def test_query_plan_confidence_bounds(self):
        with pytest.raises(Exception):
            QueryPlan(
                intent=UserIntent.STATUS_CHECK,
                target_systems=[TargetSystem.OMS],
                primary_entity="orders",
                filters=[],
                confidence=1.5,  # Out of bounds
                reasoning="test",
            )

    def test_query_plan_confidence_negative(self):
        with pytest.raises(Exception):
            QueryPlan(
                intent=UserIntent.STATUS_CHECK,
                target_systems=[TargetSystem.OMS],
                primary_entity="orders",
                filters=[],
                confidence=-0.1,
                reasoning="test",
            )

    def test_data_filter_creation(self):
        f = DataFilter(field="status", operator="eq", value="open")
        assert f.field == "status"
        assert f.operator == "eq"

    def test_query_plan_defaults(self):
        plan = QueryPlan(
            intent=UserIntent.STATUS_CHECK,
            target_systems=[TargetSystem.OMS],
            primary_entity="orders",
            confidence=0.80,
            reasoning="test",
        )
        assert plan.filters == []
        assert plan.aggregation is None
        assert plan.requires_join is False

    def test_action_proposal_requires_confirmation_default(self):
        proposal = ActionProposal(
            action_type=ActionType.UPDATE_EXCEPTION,
            target_ids=["EXC-0001"],
            changes={"status": "resolved"},
            reasoning="Test",
            impact_summary="Test",
            risk_level=RiskLevel.LOW,
        )
        assert proposal.requires_confirmation is True
