"""Tests for the C1 CLI reasoning panel.

The panel surfaces the interpret -> route -> validate pipeline that
``copilot.process_query`` returns but the CLI previously discarded. It makes
the Tier B explainable-confidence work — and the live LLM-vs-fallback choice —
visible per turn.
"""

from rich.console import Console

from agent.confidence import RoutingDecision
from cli.interactive import InteractiveCLI, render_reasoning_panel
from models.query import ConfidenceSignals, QueryPlan
from models.shared import TargetSystem, UserIntent


def _render_to_text(renderable: object) -> str:
    """Render a Rich renderable to plain text for assertions."""
    console = Console(width=240)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def _plan(source: str, confidence: float = 0.97) -> QueryPlan:
    return QueryPlan(
        intent=UserIntent.STATUS_CHECK,
        target_systems=[TargetSystem.OMS],
        primary_entity="orders",
        confidence=confidence,
        reasoning="pending orders in OMS",
        interpretation_source=source,
        confidence_signals=ConfidenceSignals(
            all_filter_fields_known=True,
            entity_unambiguous=True,
            single_clear_intent=True,
        ),
    )


def test_reasoning_panel_shows_pipeline_fields():
    """The panel renders intent, interpretation source, and confidence."""
    text = _render_to_text(
        render_reasoning_panel(_plan("llm"), RoutingDecision.EXECUTE.value, errors=[])
    )
    assert "status_check" in text  # intent
    assert "llm" in text  # interpretation source
    assert "97" in text  # confidence percentage


def test_reasoning_panel_distinguishes_fallback_from_llm():
    """A fallback turn is visibly distinguishable from an LLM-driven turn."""
    llm_text = _render_to_text(
        render_reasoning_panel(_plan("llm"), RoutingDecision.EXECUTE.value, errors=[])
    )
    fallback_text = _render_to_text(
        render_reasoning_panel(_plan("fallback"), RoutingDecision.EXECUTE.value, errors=[])
    )
    assert "llm" in llm_text
    assert "fallback" in fallback_text
    assert llm_text != fallback_text


def test_reasoning_panel_reports_validation_outcome():
    """Validation errors surface in the panel instead of being swallowed."""
    text = _render_to_text(
        render_reasoning_panel(
            _plan("llm"),
            RoutingDecision.EXECUTE.value,
            errors=["Unknown field 'foo' for systems ['oms']."],
        )
    )
    assert "foo" in text


async def test_reasoning_command_toggles_flag():
    """The /reasoning command flips the always-on panel on and off."""
    cli = InteractiveCLI()
    assert cli.show_reasoning is True
    await cli.handle_command("/reasoning")
    assert cli.show_reasoning is False
    await cli.handle_command("/reasoning")
    assert cli.show_reasoning is True
