"""Unit tests for pure functions in agent/action_handler.py (Story 15.4)."""

from unittest.mock import AsyncMock, patch

import pytest

from agent.action_handler import (
    ActionNotConfirmedError,
    _assess_risk,
    _detect_action_type,
    execute_action,
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

    def test_assess_risk_escalation_floor(self):
        """Single-target escalations are graded at least MEDIUM."""
        result = _assess_risk(1, {}, ActionType.ESCALATE_ORDER)
        assert result == RiskLevel.MEDIUM

    def test_assess_risk_financial_field(self):
        """Any change touching a financial field forces HIGH regardless of count."""
        result = _assess_risk(1, {"order_value": 99999})
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

        assert proposal.current_statuses == {"ORD-2025-001": "pending"}
        assert "current_statuses" not in proposal.changes
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
        assert "pending" not in format_proposal_summary(proposal)

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

        assert proposal.current_statuses == {"ORD-2025-002": "shipped"}
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

    async def test_escalation_cannot_auto_execute_via_llm_path(self, monkeypatch):
        # 1 target, model claims low/no-confirm -> server floor grades the
        # escalation MEDIUM, so confirmation is required regardless.
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
        tool_input = {
            "action_type": "escalate_order",
            "target_ids": ["ORD-2025-001"],
            "changes": {},
            "reasoning": "expedite the order",
            "impact_summary": "1 order",
            "risk_level": "low",
            "requires_confirmation": False,
        }
        call = AsyncMock(return_value=(tool_input, {"input_tokens": 1, "output_tokens": 1}))
        with patch("agent.action_handler.structured_call", call):
            proposal = await propose_action(
                None, "escalate order ORD-2025-001", [{"order_id": "ORD-2025-001"}]
            )

        assert proposal.risk_level == RiskLevel.MEDIUM
        assert proposal.requires_confirmation is True

    async def test_schema_keeps_risk_fields_strips_current_status(self, monkeypatch):
        # The model grades its own risk (merged raise-only server-side), so
        # risk_level stays in the schema and stays required; the validator-only
        # current_status ground truth must never enter the schema.
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
        assert "risk_level" in properties
        assert "requires_confirmation" in properties
        assert "current_status" not in properties
        assert "risk_level" in schema.get("required", [])


class TestProposeActionPrompt:
    """The proposal system prompt is composed at import time from the risk
    constants, so the rules the model reads can't drift from the rules the
    server enforces."""

    def test_prompt_composed_from_risk_constants(self):
        from agent.action_handler import (
            _AUTO_CONFIRM_TARGET_MAX,
            _FINANCIAL_FIELDS,
            _IRREVERSIBLE_STATUSES,
            _MEDIUM_TARGET_MAX,
            PROPOSE_ACTION_SYSTEM_PROMPT,
        )

        assert str(_MEDIUM_TARGET_MAX) in PROPOSE_ACTION_SYSTEM_PROMPT
        assert str(_AUTO_CONFIRM_TARGET_MAX) in PROPOSE_ACTION_SYSTEM_PROMPT
        for status in _IRREVERSIBLE_STATUSES:
            assert status in PROPOSE_ACTION_SYSTEM_PROMPT
        for field in _FINANCIAL_FIELDS:
            assert field in PROPOSE_ACTION_SYSTEM_PROMPT
        # No unformatted placeholders survive composition.
        assert "{medium_target_max}" not in PROPOSE_ACTION_SYSTEM_PROMPT

    async def test_llm_call_uses_composed_prompt(self, monkeypatch):
        from agent.action_handler import PROPOSE_ACTION_SYSTEM_PROMPT

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

        assert call.await_args.kwargs["system"] == PROPOSE_ACTION_SYSTEM_PROMPT


class TestExecuteActionRecomputesFloor:
    """execute_action re-derives the confirmation floor from the proposal's
    own targets/changes at the mutation boundary, merging raise-only with the
    carried values — a proposal constructed or mutated with a lowered gate
    cannot reach the backends unconfirmed."""

    async def test_constructed_with_lowered_gate_is_refused(self):
        proposal = ActionProposal(
            action_type=ActionType.BULK_UPDATE,
            target_ids=[f"ORD-2025-{i:04d}" for i in range(50)],
            changes={"status": "processing"},
            reasoning="constructed outside propose_action",
            impact_summary="50 orders",
            risk_level=RiskLevel.LOW,
            requires_confirmation=False,
        )
        client = AsyncMock()

        with pytest.raises(ActionNotConfirmedError):
            await execute_action(client, proposal)
        client.update_order.assert_not_awaited()

    async def test_mutated_after_construction_is_refused(self):
        proposal = ActionProposal(
            action_type=ActionType.UPDATE_ORDER_STATUS,
            target_ids=["ORD-2025-0001"],
            changes={"status": "cancelled"},
            reasoning="cancel order",
            impact_summary="1 order",
            risk_level=RiskLevel.HIGH,
            requires_confirmation=True,
        )
        proposal.requires_confirmation = False
        client = AsyncMock()

        with pytest.raises(ActionNotConfirmedError):
            await execute_action(client, proposal)
        client.update_order.assert_not_awaited()

    async def test_genuinely_low_risk_proposal_still_executes(self):
        proposal = ActionProposal(
            action_type=ActionType.ASSIGN_EXCEPTION,
            target_ids=["EXC-0001"],
            changes={"assigned_to": "Sarah Chen"},
            reasoning="single assign",
            impact_summary="1 exception",
            risk_level=RiskLevel.LOW,
            requires_confirmation=False,
        )
        client = AsyncMock()

        result = await execute_action(client, proposal)
        assert result.successful == ["EXC-0001"]

    async def test_confirmed_high_risk_proposal_executes(self):
        proposal = ActionProposal(
            action_type=ActionType.UPDATE_ORDER_STATUS,
            target_ids=["ORD-2025-0001"],
            changes={"status": "cancelled"},
            reasoning="cancel order",
            impact_summary="1 order",
            risk_level=RiskLevel.HIGH,
            requires_confirmation=True,
        )
        client = AsyncMock()

        result = await execute_action(client, proposal, confirmed=True)
        assert result.successful == ["ORD-2025-0001"]


class TestProposeActionLLMCurrentStatus:
    """The LLM status-update path must inject current_status from context, the
    same way the rule path does, so the proposal can pass transition validation
    instead of silently burning a call and falling back (REL-2)."""

    async def test_llm_path_injects_current_status_from_context(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
        tool_input = {
            "action_type": "update_order_status",
            "target_ids": ["ORD-2025-001"],
            "changes": {"status": "processing"},
            "reasoning": "advance order",
            "impact_summary": "1 order",
        }
        call = AsyncMock(return_value=(tool_input, {"input_tokens": 1, "output_tokens": 1}))
        relevant_data = [{"order_id": "ORD-2025-001", "status": "pending"}]
        with patch("agent.action_handler.structured_call", call):
            proposal = await propose_action(
                None, "update order status to processing", relevant_data
            )

        assert proposal.current_statuses == {"ORD-2025-001": "pending"}
        assert await validate_action_proposal(proposal) == []

    async def test_llm_path_resolves_join_prefixed_rows(self, monkeypatch):
        """Join-correlated context rows carry status as ``oms_status``; the
        status map must read both spellings instead of failing the match."""
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
        tool_input = {
            "action_type": "update_order_status",
            "target_ids": ["ORD-2025-001"],
            "changes": {"status": "processing"},
            "reasoning": "advance order",
            "impact_summary": "1 order",
        }
        call = AsyncMock(return_value=(tool_input, {"input_tokens": 1, "output_tokens": 1}))
        relevant_data = [{"order_id": "ORD-2025-001", "oms_status": "pending"}]
        with patch("agent.action_handler.structured_call", call):
            proposal = await propose_action(
                None, "update order status to processing", relevant_data
            )

        assert proposal.current_statuses == {"ORD-2025-001": "pending"}
        assert await validate_action_proposal(proposal) == []


class TestValidateProposalPerTarget:
    """Status transitions are validated per target against the queried
    context: no target ever borrows another row's status, and targets absent
    from context are rejected outright."""

    def _proposal(self, target_ids, current_statuses):
        return ActionProposal(
            action_type=ActionType.UPDATE_ORDER_STATUS,
            target_ids=target_ids,
            changes={"status": "processing"},
            reasoning="advance orders",
            impact_summary=f"{len(target_ids)} orders",
            risk_level=RiskLevel.MEDIUM,
            current_statuses=current_statuses,
        )

    async def test_target_missing_from_context_is_rejected(self):
        """A hallucinated/out-of-context target id must not validate against
        another row's status."""
        proposal = self._proposal(["ORD-2025-0999"], {"ORD-2025-001": "pending"})
        errors = await validate_action_proposal(proposal)
        assert any("ORD-2025-0999" in e and "context" in e for e in errors)

    async def test_each_target_validated_against_its_own_status(self):
        """A terminal-state target is rejected even when a sibling target's
        transition is valid."""
        proposal = self._proposal(
            ["ORD-2025-001", "ORD-2025-002"],
            {"ORD-2025-001": "pending", "ORD-2025-002": "delivered"},
        )
        errors = await validate_action_proposal(proposal)
        assert len(errors) == 1
        assert "ORD-2025-002" in errors[0]
        assert "delivered" in errors[0]

    async def test_all_valid_targets_pass(self):
        proposal = self._proposal(
            ["ORD-2025-001", "ORD-2025-002"],
            {"ORD-2025-001": "pending", "ORD-2025-002": "exception"},
        )
        assert await validate_action_proposal(proposal) == []


class TestLLMProposalRejectionSurfaces:
    """A proposal the validator rejects surfaces as an error — it must not
    silently degrade into a different (rule-built) proposal."""

    async def test_llm_path_invalid_transition_raises(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
        tool_input = {
            "action_type": "update_order_status",
            "target_ids": ["ORD-2025-001"],
            "changes": {"status": "delivered"},
            "reasoning": "LLM reasoning",
            "impact_summary": "1 order",
        }
        call = AsyncMock(return_value=(tool_input, {"input_tokens": 1, "output_tokens": 1}))
        relevant_data = [{"order_id": "ORD-2025-001", "status": "pending"}]
        with patch("agent.action_handler.structured_call", call):
            with pytest.raises(ValueError) as exc_info:
                await propose_action(None, "mark order delivered", relevant_data)

        assert "Invalid status transition" in str(exc_info.value)


class TestFallbackTargets:
    """The rule fallback never fans a request out across the whole context:
    ids named explicitly in the query win, otherwise only rows carrying the
    id field of the action's entity become targets."""

    async def test_explicit_id_in_query_narrows_targets(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_enabled", False)  # force rule path

        rows = [{"order_id": f"ORD-2025-{i:04d}"} for i in range(50)]
        proposal = await propose_action(None, "escalate order ORD-2025-0001", rows)

        assert proposal.target_ids == ["ORD-2025-0001"]

    async def test_explicit_id_must_exist_in_context(self, monkeypatch):
        """An id named in the query but absent from context yields no targets
        (and therefore a validation error), never a fan-out."""
        monkeypatch.setattr(get_settings(), "llm_enabled", False)  # force rule path

        rows = [{"order_id": "ORD-2025-0001"}, {"order_id": "ORD-2025-0002"}]
        with pytest.raises(ValueError, match="at least one target_id"):
            await propose_action(None, "escalate order ORD-2025-9999", rows)

    async def test_entity_mismatched_rows_excluded(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_enabled", False)  # force rule path

        rows = [
            {"exception_id": "EXC-0001"},
            {"order_id": "ORD-2025-0001"},
            {"shipment_id": "SHP-20250301-00001"},
        ]
        proposal = await propose_action(None, "resolve exception", rows)

        assert proposal.action_type == ActionType.UPDATE_EXCEPTION
        assert proposal.target_ids == ["EXC-0001"]
