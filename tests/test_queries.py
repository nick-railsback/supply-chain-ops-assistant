"""Scenario fixtures, asserted against the rule interpreter in CI.

The rule layer intentionally covers a phrasing subset. Scenarios it can parse
are pinned exactly; scenarios it cannot parse are pinned as "must decline to
guess" (None -> clarification) so a future pattern that mis-classifies them
fails loudly; scenarios it partially matches (one system of a cross-system
query, or an over-eager read match) are pinned to the system set it actually
returns. Full-intent assertions run on the llm-marked variant when a key is
configured.

The tier assignments below were verified by running each query through
``_rule_based_interpret`` — not copied from a design doc. No scenario currently
maps to its full expected (intent, systems); the rule layer either declines or
matches a single system, which is why RULE_HANDLED is empty.
"""

import json
from pathlib import Path

import pytest

from agent.query_interpreter import _rule_based_interpret, interpret_query

SCENARIOS_DIR = Path(__file__).parent / "scenarios"


def load_scenarios():
    """Load all JSON scenario fixtures as (stem, data) params."""
    scenarios = []
    for f in sorted(SCENARIOS_DIR.glob("*.json")):
        with open(f) as fh:
            scenarios.append(pytest.param((f.stem, json.load(fh)), id=f.stem))
    return scenarios


# Scenarios the rule layer parses to their full expected (intent, systems).
RULE_HANDLED: dict[str, tuple[str, set[str]]] = {}

# Scenarios the rule layer cannot parse — it must decline (None), not guess.
RULE_DECLINES = {
    "01_order_status_check",
    "02_shipment_tracking",
    "03_inventory_low_stock",
    "05_exception_summary_report",
    "06_resolve_exception_action",
    "07_ambiguous_query",
    "09_order_analysis_by_channel",
}

# Scenarios the rule layer matches partially: it returns the system set below,
# but the scenario's true intent (cross-system join, or an action) is an
# LLM-path capability. Pinned so silent drift in either direction fails.
RULE_PARTIAL: dict[str, set[str]] = {
    "04_cross_system_order_shipment": {"oms"},
    "08_wms_tms_cross_system": {"wms"},
    "10_bulk_escalate_action": {"oms"},
}


@pytest.mark.parametrize("scenario", load_scenarios())
def test_scenario_rule_behavior(scenario):
    """Pin the rule interpreter's current behavior per scenario tier."""
    sid, data = scenario
    plan = _rule_based_interpret(data["query"])

    if sid in RULE_DECLINES:
        assert plan is None, f"{sid}: rule layer should decline, got {plan}"
    elif sid in RULE_PARTIAL:
        assert plan is not None, sid
        assert {s.value for s in plan.target_systems} == RULE_PARTIAL[sid], sid
    elif sid in RULE_HANDLED:
        intent, systems = RULE_HANDLED[sid]
        assert plan is not None, sid
        assert plan.intent.value == intent, sid
        assert {s.value for s in plan.target_systems} == systems, sid
    else:
        pytest.fail(f"scenario {sid} is not assigned to a tier")


@pytest.mark.parametrize("scenario", load_scenarios())
def test_scenario_fixture_structure(scenario):
    """Every scenario fixture carries the keys the eval and LLM tests rely on."""
    _sid, data = scenario
    assert isinstance(data["name"], str)
    assert isinstance(data["query"], str)
    assert isinstance(data["expected_intent"], str)
    assert isinstance(data["expected_systems"], list)


@pytest.mark.llm
@pytest.mark.parametrize("scenario", load_scenarios())
async def test_scenario_intent_llm(scenario):
    """Full interpretation against the gold labels (LLM path only)."""
    sid, data = scenario
    plan = await interpret_query(data["query"], [])
    assert plan.intent.value == data["expected_intent"], sid
    # 07 legitimately clarifies and emits no systems; assert intent only.
    if sid != "07_ambiguous_query":
        assert {s.value for s in plan.target_systems} == set(data["expected_systems"]), sid
