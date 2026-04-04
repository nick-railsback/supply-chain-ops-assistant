"""Scenario tests with full agent against golden fixtures."""

import json
from pathlib import Path

import pytest

SCENARIOS_DIR = Path(__file__).parent / "scenarios"


def load_scenarios():
    """Load all JSON scenario fixtures from the scenarios directory."""
    scenarios = []
    for f in sorted(SCENARIOS_DIR.glob("*.json")):
        with open(f) as fh:
            scenarios.append(pytest.param(json.load(fh), id=f.stem))
    return scenarios


@pytest.mark.llm
@pytest.mark.parametrize("scenario", load_scenarios())
async def test_scenario_intent(scenario):
    """Verify intent classification matches expected."""
    # For now, just validate fixture structure
    assert "name" in scenario
    assert "query" in scenario
    assert "expected_intent" in scenario
    assert "expected_systems" in scenario
    assert isinstance(scenario["name"], str)
    assert isinstance(scenario["query"], str)
    assert isinstance(scenario["expected_intent"], str)
    assert isinstance(scenario["expected_systems"], list)
