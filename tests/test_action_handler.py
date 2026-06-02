"""Unit tests for pure functions in agent/action_handler.py (Story 15.4)."""

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
