"""Intent dispatch end-to-end (ARCH-1, UX-2).

process_query previously ran every plan as a read regardless of intent, so the
report and action pipelines were unreachable from the CLI. These tests pin that
process_query branches on plan.intent and that the CLI owns the confirmation
decision (the copilot never prompts).
"""

from unittest.mock import AsyncMock, patch

from rich.console import Console

from agent.copilot import Copilot
from cli.interactive import InteractiveCLI
from models.query import QueryPlan, QueryResult
from models.shared import TargetSystem, UserIntent


def _plan(intent: UserIntent, confidence: float, entity: str = "order") -> QueryPlan:
    return QueryPlan(
        intent=intent,
        target_systems=[TargetSystem.OMS],
        primary_entity=entity,
        filters=[],
        confidence=confidence,
        reasoning="test plan",
    )


# ---------------------------------------------------------------------------
# Copilot-level dispatch
# ---------------------------------------------------------------------------


async def test_report_intent_calls_generate_report(sample_report_output):
    plan = _plan(UserIntent.REPORT, 0.9, entity="report")
    report = sample_report_output()
    exec_mock = AsyncMock()
    copilot = Copilot()
    with (
        patch("agent.copilot.interpret_query", AsyncMock(return_value=plan)),
        patch("agent.report_generator.generate_report", AsyncMock(return_value=report)),
        patch("agent.copilot.execute_query", exec_mock),
    ):
        result = await copilot.process_query("give me a morning ops standup report")

    assert result["status"] == "report"
    assert result["report"] is report
    exec_mock.assert_not_called()


async def test_action_intent_returns_proposal_without_executing(sample_action_proposal):
    plan = _plan(UserIntent.ACTION_REQUEST, 0.95)
    context = QueryResult(
        data=[{"order_id": "ORD-2025-001", "status": "pending"}],
        total_count=1,
        systems_queried=[TargetSystem.OMS],
    )
    proposal = sample_action_proposal(requires_confirmation=True)
    copilot = Copilot()
    with (
        patch("agent.copilot.interpret_query", AsyncMock(return_value=plan)),
        patch("agent.copilot.execute_query", AsyncMock(return_value=context)),
        patch("agent.action_handler.propose_action", AsyncMock(return_value=proposal)),
    ):
        result = await copilot.process_query("resolve exception EXC-0042")

    assert result["status"] == "action_proposed"
    assert result["proposal"] is proposal


async def test_action_proposal_validation_error_returns_error_status():
    plan = _plan(UserIntent.ACTION_REQUEST, 0.95)
    context = QueryResult(data=[], total_count=0, systems_queried=[TargetSystem.OMS])
    copilot = Copilot()
    with (
        patch("agent.copilot.interpret_query", AsyncMock(return_value=plan)),
        patch("agent.copilot.execute_query", AsyncMock(return_value=context)),
        patch(
            "agent.action_handler.propose_action",
            AsyncMock(side_effect=ValueError("Action validation failed: bad transition")),
        ),
    ):
        result = await copilot.process_query("mark order delivered")

    assert result["status"] == "error"


async def test_status_check_path_unchanged():
    plan = _plan(UserIntent.STATUS_CHECK, 0.9)
    res = QueryResult(
        data=[{"order_id": "ORD-2025-001"}],
        total_count=1,
        systems_queried=[TargetSystem.OMS],
    )
    copilot = Copilot()
    with (
        patch("agent.copilot.interpret_query", AsyncMock(return_value=plan)),
        patch("agent.copilot.execute_query", AsyncMock(return_value=res)),
    ):
        result = await copilot.process_query("show all orders")

    assert result["status"] == "success"
    assert result["data"] is not None
    assert result["report"] is None
    assert result["proposal"] is None


# ---------------------------------------------------------------------------
# CLI-level confirmation flow
# ---------------------------------------------------------------------------


class _FakeCopilot:
    def __init__(self, envelope: dict) -> None:
        self._envelope = envelope
        self.execute_confirmed_action = AsyncMock()

    async def process_query(self, query: str) -> dict:
        return self._envelope


def _envelope(status: str, **overrides: object) -> dict:
    base = {
        "status": status,
        "plan": None,
        "routing": "execute",
        "message": "msg",
        "data": None,
        "report": None,
        "proposal": None,
        "errors": [],
    }
    base.update(overrides)
    return base


async def test_cli_renders_report(sample_report_output):
    report = sample_report_output()  # title "Test Report"
    cli = InteractiveCLI()
    cli.copilot = _FakeCopilot(_envelope("report", report=report))  # type: ignore[assignment]
    cli.show_reasoning = False
    console = Console(width=240)
    cli.console = console
    with console.capture() as capture:
        await cli.handle_query("give me a report")

    assert "Test Report" in capture.get()


async def test_cli_declined_confirmation_executes_nothing(sample_action_proposal):
    proposal = sample_action_proposal(requires_confirmation=True)
    fake = _FakeCopilot(_envelope("action_proposed", proposal=proposal))
    cli = InteractiveCLI()
    cli.copilot = fake  # type: ignore[assignment]
    cli.show_reasoning = False
    console = Console(width=240)
    cli.console = console
    with (
        patch("cli.interactive.prompt_confirmation", AsyncMock(return_value=False)),
        console.capture() as capture,
    ):
        await cli.handle_query("escalate order ORD-2025-001")

    fake.execute_confirmed_action.assert_not_called()
    assert "cancelled" in capture.get().lower()
