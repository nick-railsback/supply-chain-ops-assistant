"""Integration tests for action pipeline with mock OpsClient (Story 15.5)."""

from unittest.mock import AsyncMock

import pytest

from agent.action_handler import (
    ActionNotConfirmedError,
    _dispatch_action,
    confirm_action,
    execute_action,
)
from models.action import ActionProposal, ActionType
from models.shared import RiskLevel


def _make_mock_client():
    """Create a mock OpsClient with async methods."""
    client = AsyncMock()
    client.update_order = AsyncMock(return_value=None)
    client.update_exception = AsyncMock(return_value=None)
    client.update_shipment = AsyncMock(return_value=None)
    return client


class TestExecuteAction:
    async def test_execute_action_update_order(self):
        """ORD prefix targets call patch_order via UPDATE_ORDER_STATUS."""
        client = _make_mock_client()
        proposal = ActionProposal(
            action_type=ActionType.UPDATE_ORDER_STATUS,
            target_ids=["ORD-2025-001"],
            changes={"status": "processing"},
            reasoning="Update order",
            impact_summary="Update 1 order",
            risk_level=RiskLevel.LOW,
        )
        result = await execute_action(client, proposal, confirmed=True)
        assert result.total_targets == 1
        assert len(result.successful) == 1
        assert result.successful[0] == "ORD-2025-001"
        assert len(result.failed) == 0
        client.update_order.assert_called_once_with("ORD-2025-001", {"status": "processing"})

    async def test_execute_action_assign_exception(self):
        """EXC prefix targets call patch_exception via ASSIGN_EXCEPTION."""
        client = _make_mock_client()
        proposal = ActionProposal(
            action_type=ActionType.ASSIGN_EXCEPTION,
            target_ids=["EXC-001"],
            changes={"assigned_to": "Sarah Chen"},
            reasoning="Assign exception",
            impact_summary="Assign 1 exception",
            risk_level=RiskLevel.LOW,
        )
        result = await execute_action(client, proposal, confirmed=True)
        assert len(result.successful) == 1
        assert result.successful[0] == "EXC-001"
        client.update_exception.assert_called_once_with("EXC-001", {"assigned_to": "Sarah Chen"})

    async def test_execute_action_bulk_shipment(self):
        """SHP prefix targets in BULK_UPDATE call update_shipment."""
        client = _make_mock_client()
        proposal = ActionProposal(
            action_type=ActionType.BULK_UPDATE,
            target_ids=["SHP-20250301-00001", "SHP-20250302-00002"],
            changes={"status": "delivered"},
            reasoning="Bulk update shipments",
            impact_summary="Update 2 shipments",
            risk_level=RiskLevel.MEDIUM,
        )
        result = await execute_action(client, proposal, confirmed=True)
        assert result.total_targets == 2
        assert len(result.successful) == 2
        assert client.update_shipment.call_count == 2

    async def test_execute_action_partial_failure(self):
        """One target fails, result has both successes and failures."""
        client = _make_mock_client()
        # First call succeeds, second raises
        client.update_order.side_effect = [None, Exception("DB error")]
        proposal = ActionProposal(
            action_type=ActionType.UPDATE_ORDER_STATUS,
            target_ids=["ORD-2025-001", "ORD-2025-002"],
            changes={"status": "processing"},
            reasoning="Update orders",
            impact_summary="Update 2 orders",
            risk_level=RiskLevel.MEDIUM,
        )
        result = await execute_action(client, proposal, confirmed=True)
        assert result.total_targets == 2
        assert len(result.successful) == 1
        assert len(result.failed) == 1
        assert result.failed[0]["id"] == "ORD-2025-002"
        assert "DB error" in result.failed[0]["error"]


class TestDispatchUnknownPrefix:
    async def test_dispatch_unknown_prefix(self):
        """Unknown ID prefix in BULK_UPDATE raises ValueError."""
        client = _make_mock_client()
        with pytest.raises(ValueError, match="unknown ID prefix"):
            await _dispatch_action(
                client,
                ActionType.BULK_UPDATE,
                "UNKNOWN-123",
                {"status": "foo"},
            )


# ---------------------------------------------------------------------------
# C4 — fail-safe confirmation gate
# ---------------------------------------------------------------------------


def _confirmable_proposal(requires_confirmation: bool = True) -> ActionProposal:
    return ActionProposal(
        action_type=ActionType.UPDATE_ORDER_STATUS,
        target_ids=["ORD-2025-001"],
        changes={"status": "processing"},
        reasoning="Update order",
        impact_summary="Update 1 order",
        risk_level=RiskLevel.LOW,
        requires_confirmation=requires_confirmation,
    )


class TestConfirmationGate:
    async def test_execute_refuses_unconfirmed_proposal(self):
        """A proposal requiring confirmation does not mutate without confirmed=True."""
        client = _make_mock_client()
        proposal = _confirmable_proposal(requires_confirmation=True)

        with pytest.raises(ActionNotConfirmedError):
            await execute_action(client, proposal)

        client.update_order.assert_not_called()

    async def test_execute_proceeds_when_confirmed(self):
        """Explicit confirmed=True allows the mutation to proceed."""
        client = _make_mock_client()
        proposal = _confirmable_proposal(requires_confirmation=True)

        result = await execute_action(client, proposal, confirmed=True)

        assert result.successful == ["ORD-2025-001"]
        client.update_order.assert_called_once()

    async def test_execute_proceeds_when_confirmation_not_required(self):
        """A proposal that doesn't require confirmation executes without confirmed."""
        client = _make_mock_client()
        proposal = _confirmable_proposal(requires_confirmation=False)

        result = await execute_action(client, proposal)

        assert result.successful == ["ORD-2025-001"]
        client.update_order.assert_called_once()


class TestInvalidProposalSurfaces:
    """A proposal the validator rejects reaches the operator as an error
    envelope explaining why — not as a silently substituted fallback proposal
    targeting rows the user never asked about."""

    async def test_invalid_transition_reaches_user_as_error(self, monkeypatch):
        from unittest.mock import patch

        from agent.copilot import Copilot
        from config.settings import get_settings
        from models.query import QueryPlan, QueryResult
        from models.shared import TargetSystem, UserIntent

        monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
        plan = QueryPlan(
            intent=UserIntent.ACTION_REQUEST,
            target_systems=[TargetSystem.OMS],
            primary_entity="order",
            filters=[],
            confidence=0.95,
            reasoning="test plan",
        )
        context = QueryResult(
            data=[{"order_id": "ORD-2025-001", "status": "pending"}],
            total_count=1,
            systems_queried=[TargetSystem.OMS],
        )
        tool_input = {
            "action_type": "update_order_status",
            "target_ids": ["ORD-2025-001"],
            "changes": {"status": "delivered"},
            "reasoning": "mark delivered",
            "impact_summary": "1 order",
        }
        call = AsyncMock(return_value=(tool_input, {"input_tokens": 1, "output_tokens": 1}))
        copilot = Copilot()
        with (
            patch("agent.copilot.interpret_query", AsyncMock(return_value=plan)),
            patch("agent.copilot.execute_query", AsyncMock(return_value=context)),
            patch("agent.action_handler.structured_call", call),
        ):
            result = await copilot.process_query("mark order ORD-2025-001 as delivered")

        assert result["status"] == "error"
        assert "Invalid status transition" in result["message"]
        assert result["proposal"] is None


class TestConfirmActionFailSafe:
    async def test_confirm_action_blocks_when_required(self):
        """confirm_action never auto-approves a proposal that requires confirmation."""
        assert await confirm_action(_confirmable_proposal(requires_confirmation=True)) is False

    async def test_confirm_action_allows_when_not_required(self):
        """confirm_action auto-approves only low-risk, no-confirmation-needed proposals."""
        assert await confirm_action(_confirmable_proposal(requires_confirmation=False)) is True
