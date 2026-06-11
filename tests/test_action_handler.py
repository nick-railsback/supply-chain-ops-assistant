"""Unit tests for pure functions in agent/action_handler.py (Story 15.4)."""

from unittest.mock import AsyncMock, patch

import pytest

from agent.action_handler import (
    _assess_risk,
    _detect_action_type,
    format_proposal_summary,
    propose_action,
)
from agent.validators import validate_action_proposal
from config.settings import get_settings
from models.action import ActionProposal, ActionType
from models.shared import RiskLevel

# ---------------------------------------------------------------------------
# _assess_risk tests
# ---------------------------------------------------------------------------


class TestAssessRisk:
    def test_assess_risk_low(self):
        """Single target, non-irreversible status -> LOW."""
        result = _assess_risk(1, {"status": "processing"})
        assert result == RiskLevel.LOW

    def test_assess_risk_medium(self):
        """5 targets -> MEDIUM."""
        result = _assess_risk(5, {"status": "shipped"})
        assert result == RiskLevel.MEDIUM

    def test_assess_risk_high_count(self):
        """15 targets -> HIGH (count-based)."""
        result = _assess_risk(15, {"status": "processing"})
        assert result == RiskLevel.HIGH

    def test_assess_risk_high_cancelled(self):
        """Cancelled status overrides to HIGH regardless of count."""
        result = _assess_risk(1, {"status": "cancelled"})
        assert result == RiskLevel.HIGH

    def test_assess_risk_high_returned(self):
        """Returned status overrides to HIGH regardless of count."""
        result = _assess_risk(1, {"status": "returned"})
        assert result == RiskLevel.HIGH


# ---------------------------------------------------------------------------
# _detect_action_type tests
# ---------------------------------------------------------------------------


class TestDetectActionType:
    def test_detect_action_type_update_order(self):
        result = _detect_action_type("update order status to shipped")
        assert result == ActionType.UPDATE_ORDER_STATUS

    def test_detect_action_type_assign_exception(self):
        result = _detect_action_type("assign exception to Sarah Chen")
        assert result == ActionType.ASSIGN_EXCEPTION

    def test_detect_action_type_escalate(self):
        result = _detect_action_type("escalate this order immediately")
        assert result == ActionType.ESCALATE_ORDER

    def test_detect_action_type_fallback(self):
        """Unmatched query falls back to BULK_UPDATE."""
        result = _detect_action_type("do something random with data")
        assert result == ActionType.BULK_UPDATE


# ---------------------------------------------------------------------------
# format_proposal_summary tests
# ---------------------------------------------------------------------------


class TestFormatProposalSummary:
    def test_format_proposal_summary(self):
        proposal = ActionProposal(
            action_type=ActionType.ASSIGN_EXCEPTION,
            target_ids=["EXC-001", "EXC-002", "EXC-003"],
            changes={"assigned_to": "Sarah Chen"},
            reasoning="Assign critical exceptions",
            impact_summary="This will assign 3 exceptions to Sarah Chen",
            risk_level=RiskLevel.MEDIUM,
        )
        summary = format_proposal_summary(proposal)
        assert "3 exceptions" in summary
        assert "Sarah Chen" in summary
        assert "medium" in summary
        assert "assign_exception" in summary


# ---------------------------------------------------------------------------
# propose_action — B4 regression
# ---------------------------------------------------------------------------


class TestProposeActionStatusUpdate:
    """Regression tests for B4: UPDATE_ORDER_STATUS proposals must capture the
    order's ``current_status`` so the transition validator can run — as
    validator-only metadata (``ActionProposal.current_status``), never leaked
    into the dispatched ``changes``.
    """

    async def test_captures_current_status_and_passes_validation(self, monkeypatch):
        """A valid pending -> processing request validates, with current_status
        captured off-band rather than mixed into the dispatched changes."""
        monkeypatch.setattr(get_settings(), "llm_enabled", False)  # force rule path

        row = {
            "order_id": "ORD-2025-001",
            "status": "pending",
            "changes": {"status": "processing"},
        }
        proposal = await propose_action(None, "update order status to processing", [row])

        assert proposal.current_status == "pending"
        assert "current_status" not in proposal.changes
        assert await validate_action_proposal(proposal) == []

    async def test_current_status_not_dispatched_or_rendered(self, monkeypatch):
        """current_status is validator-only: it must not appear in the changes
        sent to the backend or in the human-facing proposal summary."""
        monkeypatch.setattr(get_settings(), "llm_enabled", False)  # force rule path

        row = {
            "order_id": "ORD-2025-001",
            "status": "pending",
            "changes": {"status": "processing"},
        }
        proposal = await propose_action(None, "update order status to processing", [row])

        assert proposal.changes == {"status": "processing"}
        assert "current_status" not in format_proposal_summary(proposal)

    async def test_shipped_to_delivered_is_valid(self, monkeypatch):
        """The corrected transition map allows the real shipped -> delivered move
        (the drifted map only allowed shipped -> in_transit)."""
        monkeypatch.setattr(get_settings(), "llm_enabled", False)  # force rule path

        row = {
            "order_id": "ORD-2025-002",
            "status": "shipped",
            "changes": {"status": "delivered"},
        }
        proposal = await propose_action(None, "update order status to delivered", [row])

        assert proposal.current_status == "shipped"
        assert await validate_action_proposal(proposal) == []

    async def test_invalid_transition_fails_on_transition_rule(self, monkeypatch):
        """An invalid pending -> delivered request fails on the transition rule,
        not on the missing-current_status guard."""
        monkeypatch.setattr(get_settings(), "llm_enabled", False)  # force rule path

        row = {
            "order_id": "ORD-2025-001",
            "status": "pending",
            "changes": {"status": "delivered"},
        }
        with pytest.raises(ValueError) as exc_info:
            await propose_action(None, "update order status to delivered", [row])

        message = str(exc_info.value)
        assert "Invalid status transition" in message


# ---------------------------------------------------------------------------
# propose_action — LLM path lifecycle (#8)
# ---------------------------------------------------------------------------


class TestProposeActionLLM:
    """The LLM proposal path must route through agent.llm.structured_call
    (forced tool-use + guaranteed client teardown), never a hand-rolled
    AsyncAnthropic client that leaks its httpx pool.
    """

    async def test_routes_through_structured_call(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")

        tool_input = {
            "action_type": "assign_exception",
            "target_ids": ["EXC-001"],
            "changes": {"assigned_to": "Sarah Chen"},
            "reasoning": "LLM reasoning",
            "impact_summary": "Assign 1 exception",
            "risk_level": "low",
            "requires_confirmation": False,
        }
        call = AsyncMock(return_value=(tool_input, {"input_tokens": 1, "output_tokens": 1}))
        with (
            patch("agent.action_handler.structured_call", call),
            patch("anthropic.AsyncAnthropic") as raw_client,
        ):
            proposal = await propose_action(
                None, "assign exception EXC-001 to Sarah Chen", [{"exception_id": "EXC-001"}]
            )

        call.assert_awaited_once()
        raw_client.assert_not_called()
        # The returned proposal is the LLM's (rule path would set a different reasoning).
        assert proposal.reasoning == "LLM reasoning"
        assert proposal.action_type == ActionType.ASSIGN_EXCEPTION

    async def test_falls_back_to_rule_path_on_error(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")

        call = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("agent.action_handler.structured_call", call):
            proposal = await propose_action(
                None, "assign exception EXC-001 to Sarah Chen", [{"exception_id": "EXC-001"}]
            )

        # Fell back to the rule path, which builds reasoning from the query.
        assert proposal.reasoning.startswith("Action requested via:")


# ---------------------------------------------------------------------------
# propose_action — server-side risk recompute (SEC-1)
# ---------------------------------------------------------------------------


class TestProposeActionRiskFloor:
    """The model's risk claims are advisory: server recompute can raise risk
    and requires_confirmation, never lower them (SEC-1)."""

    async def test_llm_cannot_lower_requires_confirmation(self, monkeypatch):
        # 12 targets -> rule floor is HIGH/confirm, whatever the model claims.
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
        tool_input = {
            "action_type": "bulk_update",
            "target_ids": [f"EXC-{i:04d}" for i in range(12)],
            "changes": {"status": "investigating"},
            "reasoning": "bulk triage",
            "impact_summary": "12 exceptions",
            "risk_level": "low",
            "requires_confirmation": False,
        }
        call = AsyncMock(return_value=(tool_input, {"input_tokens": 1, "output_tokens": 1}))
        with patch("agent.action_handler.structured_call", call):
            proposal = await propose_action(None, "bulk update exceptions", [{}])

        assert proposal.risk_level == RiskLevel.HIGH
        assert proposal.requires_confirmation is True

    async def test_llm_can_raise_but_not_lower_risk(self, monkeypatch):
        # 1 target, model claims high -> stays HIGH (raise allowed).
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
        claims_high = {
            "action_type": "assign_exception",
            "target_ids": ["EXC-0001"],
            "changes": {"assigned_to": "Sarah Chen"},
            "reasoning": "single assign",
            "impact_summary": "1 exception",
            "risk_level": "high",
            "requires_confirmation": True,
        }
        call = AsyncMock(return_value=(claims_high, {"input_tokens": 1, "output_tokens": 1}))
        with patch("agent.action_handler.structured_call", call):
            proposal = await propose_action(None, "assign exception", [{}])
        assert proposal.risk_level == RiskLevel.HIGH

        # 1 target, no claim -> LOW (computed), no confirmation needed.
        no_claim = {
            "action_type": "assign_exception",
            "target_ids": ["EXC-0001"],
            "changes": {"assigned_to": "Sarah Chen"},
            "reasoning": "single assign",
            "impact_summary": "1 exception",
        }
        call = AsyncMock(return_value=(no_claim, {"input_tokens": 1, "output_tokens": 1}))
        with patch("agent.action_handler.structured_call", call):
            proposal = await propose_action(None, "assign exception", [{}])
        assert proposal.risk_level == RiskLevel.LOW
        assert proposal.requires_confirmation is False

    async def test_schema_omits_server_side_fields(self, monkeypatch):
        # Capture the input_schema kwarg; risk_level / requires_confirmation /
        # current_status must be absent from properties AND from "required".
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
        tool_input = {
            "action_type": "assign_exception",
            "target_ids": ["EXC-0001"],
            "changes": {"assigned_to": "Sarah Chen"},
            "reasoning": "single assign",
            "impact_summary": "1 exception",
        }
        call = AsyncMock(return_value=(tool_input, {"input_tokens": 1, "output_tokens": 1}))
        with patch("agent.action_handler.structured_call", call):
            await propose_action(None, "assign exception", [{}])

        schema = call.await_args.kwargs["input_schema"]
        properties = schema.get("properties", {})
        for field in ("risk_level", "requires_confirmation", "current_status"):
            assert field not in properties, field
        assert "risk_level" not in schema.get("required", [])
