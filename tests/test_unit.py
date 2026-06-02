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

    async def test_oms_exception_filter_fields_validate(self, sample_query_plan):
        """OMS hosts both orders and exceptions; exception fields must validate."""
        plan = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            filters=[
                DataFilter(field="severity", operator="eq", value="critical"),
                DataFilter(field="date_from", operator="gte", value="2026-01-01"),
            ],
        )
        errors = await validate_query_plan(plan)
        assert errors == []

    async def test_unknown_oms_field_still_rejected(self, sample_query_plan):
        """A field that exists under no OMS entity is still flagged."""
        plan = sample_query_plan(
            target_systems=[TargetSystem.OMS],
            filters=[DataFilter(field="not_a_real_field", operator="eq", value="x")],
        )
        errors = await validate_query_plan(plan)
        assert any("not_a_real_field" in e for e in errors)


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
