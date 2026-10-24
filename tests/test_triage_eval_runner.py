"""Black-box plumbing checks for the reference triage-eval runner behind
`make eval-triage`: gold-set wiring, the forced-tool-use call shape, the
accuracy report, and the pass/fail gate — all against a faked Claude client,
never a live one.

No test here makes a network call or requires ANTHROPIC_API_KEY. Every
Claude call in this file is intercepted by replacing `agent.llm._client`,
the same seam `tests/test_llm.py` already uses to test the shared
structured-output client, so a runner that reuses `agent.llm.structured_call`
as written is exercised end to end while a live call never leaves the
process. A runner that bypassed that shared client entirely would attempt a
real connection here and fail loudly, which is itself part of what these
tests guard.

The runner is invoked the same way `make eval-triage` invokes it: as
`python -m <its module>`, with the module discovered from the Makefile
recipe rather than guessed at and imported by name, and executed in-process
via `runpy` so nothing here calls a function inside that module by name —
only the module's own `__main__` behaviour is exercised, the same surface a
person typing `make eval-triage` would see.

The fake Claude client inspects the tool schema it's handed to find whichever
property is constrained to the three root-cause values, rather than assuming
a fixed key name, and inspects the call's own `user` text to determine which
gold-set case it's being asked to classify, rather than assuming call order
lines up with file order. Both of those are choices the eventual
implementation still gets to make freely.
"""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from anthropic.types import ToolUseBlock

from triage.taxonomy import RootCause

ROOT_CAUSE_VALUES = {member.value for member in RootCause}


# ---------------------------------------------------------------------------
# Locating the repo and the not-yet-built entrypoint, read lazily
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError(f"could not locate the repo root above {here}")


def _discover_triage_eval_module() -> str:
    """The dotted module `make eval-triage` runs, read off the Makefile
    recipe rather than hardcoded — the same discovery-by-shape technique
    this suite already uses for other not-yet-built artifacts."""
    makefile = _repo_root() / "Makefile"
    assert makefile.is_file(), f"no Makefile at {makefile}"
    lines = makefile.read_text(encoding="utf-8").splitlines()

    target_start = None
    for i, line in enumerate(lines):
        if line.startswith("eval-triage:"):
            target_start = i
            break
    assert target_start is not None, "no 'eval-triage' target found in Makefile"

    recipe_lines = []
    for line in lines[target_start + 1 :]:
        if line.startswith("\t"):
            recipe_lines.append(line)
        elif not line.strip():
            continue
        else:
            break
    assert recipe_lines, "'eval-triage' target has an empty recipe"

    tokens = [tok for line in recipe_lines for tok in line.split()]
    module = None
    for i in range(len(tokens) - 1):
        if tokens[i] == "-m" and tokens[i + 1].startswith("evals."):
            module = tokens[i + 1]
            break
    assert module is not None, (
        f"'eval-triage' recipe names no '-m evals.<module>' invocation: {tokens!r}"
    )
    return module


def _load_gold_cases() -> list[dict[str, Any]]:
    path = _repo_root() / "evals" / "triage_dataset.jsonl"
    assert path.is_file(), f"no gold-set dataset at {path}"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines, f"{path} has no cases"
    return [json.loads(ln) for ln in lines]


# ---------------------------------------------------------------------------
# A fake Claude tool-use client: schema-adaptive, case-adaptive
# ---------------------------------------------------------------------------


def _classification_property(input_schema: dict[str, Any]) -> str | None:
    """The name of whichever schema property is constrained to exactly the
    three root-cause values -- discovered by shape, not by a name this file
    would otherwise have to guess."""
    properties = input_schema.get("properties") or {}
    for name, prop in properties.items():
        if isinstance(prop, dict) and set(prop.get("enum") or []) == ROOT_CAUSE_VALUES:
            return name
    return None


def _case_for_call(user_text: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [c for c in cases if c["case_id"] in user_text]
    assert matches, f"no gold case's case_id appears in a call's content: {user_text[:200]!r}"
    assert len(matches) == 1, (
        f"more than one case_id appears in a single call's content: "
        f"{[m['case_id'] for m in matches]}"
    )
    return matches[0]


def _make_fake_client(
    cases: list[dict[str, Any]], classify: Any
) -> tuple[AsyncMock, list[dict[str, Any]]]:
    """A stand-in for `agent.llm._client()`'s return value. `classify` maps a
    case's true `label` to whatever classification the fake model should
    answer with, so callers can script an all-correct or all-wrong pass and
    know the resulting accuracy exactly, without depending on the gold set's
    real label distribution."""
    calls: list[dict[str, Any]] = []

    async def _create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        tools = kwargs["tools"]
        assert len(tools) == 1, f"expected exactly one forced tool, got {len(tools)}"
        tool = tools[0]
        prop_name = _classification_property(tool.get("input_schema") or {})
        assert prop_name is not None, (
            f"no property in the tool's input_schema has enum == {sorted(ROOT_CAUSE_VALUES)}: "
            f"{tool.get('input_schema')!r}"
        )
        user_text = kwargs["messages"][0]["content"]
        case = _case_for_call(user_text, cases)
        value = classify(case["label"])

        block = ToolUseBlock(
            type="tool_use", id="fake-call", name=tool["name"], input={prop_name: value}
        )
        message = MagicMock()
        message.content = [block]
        message.usage = MagicMock(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        return message

    client = AsyncMock()
    client.messages.create = AsyncMock(side_effect=_create)
    return client, calls


def _echo_true_label(true_label: str) -> str:
    return true_label


def _a_wrong_label(true_label: str) -> str:
    return next(v for v in ROOT_CAUSE_VALUES if v != true_label)


def _run_triage_eval(monkeypatch: Any, argv_tail: list[str], client: AsyncMock) -> int:
    """Runs the discovered module the way `python -m <module>` would, with
    the Claude client faked out. Returns the effective process exit code:
    0 for a clean return or `SystemExit(None | 0)`, non-zero otherwise."""
    module = _discover_triage_eval_module()
    monkeypatch.setattr(sys, "argv", ["eval-triage", *argv_tail])
    monkeypatch.setattr("agent.llm._client", lambda: client)
    try:
        runpy.run_module(module, run_name="__main__")
    except SystemExit as exc:
        return 0 if exc.code in (None, 0) else 1
    return 0


# ---------------------------------------------------------------------------
# The Makefile target
# ---------------------------------------------------------------------------


def test_makefile_gains_eval_triage_without_disturbing_the_existing_eval_target() -> None:
    module = _discover_triage_eval_module()
    assert module.startswith("evals."), f"discovered module {module!r} is not under evals."

    makefile_text = (_repo_root() / "Makefile").read_text(encoding="utf-8")
    assert "uv run python -m evals.run_eval $(EVAL_ARGS)" in makefile_text, (
        "the pre-existing 'eval' target's recipe no longer matches its current form"
    )


# ---------------------------------------------------------------------------
# Gold-set wiring: one call per case, each call tied to its own case
# ---------------------------------------------------------------------------


def test_every_gold_set_case_gets_exactly_one_individually_addressed_call(monkeypatch: Any) -> None:
    cases = _load_gold_cases()
    client, calls = _make_fake_client(cases, _echo_true_label)
    _run_triage_eval(monkeypatch, [], client)

    assert len(calls) == len(cases), (
        f"{len(calls)} Claude calls for {len(cases)} gold-set cases — expected exactly one each"
    )
    addressed = {_case_for_call(call["messages"][0]["content"], cases)["case_id"] for call in calls}
    all_case_ids = {c["case_id"] for c in cases}
    assert addressed == all_case_ids, (
        f"cases never individually addressed by a call: {all_case_ids - addressed}"
    )


# ---------------------------------------------------------------------------
# The forced-tool-use call shape
# ---------------------------------------------------------------------------


def test_tool_schema_constrains_classification_to_the_three_root_causes(monkeypatch: Any) -> None:
    cases = _load_gold_cases()
    client, calls = _make_fake_client(cases, _echo_true_label)
    _run_triage_eval(monkeypatch, [], client)

    assert calls, "no Claude calls were made"
    for call in calls:
        tools = call["tools"]
        assert len(tools) == 1, f"expected exactly one forced tool, got {len(tools)}"
        prop_name = _classification_property(tools[0].get("input_schema") or {})
        assert prop_name is not None, (
            f"tool input_schema constrains no property to {sorted(ROOT_CAUSE_VALUES)}: "
            f"{tools[0].get('input_schema')!r}"
        )


# ---------------------------------------------------------------------------
# The accuracy report
# ---------------------------------------------------------------------------


def test_stdout_reports_full_marks_when_every_case_is_classified_correctly(
    monkeypatch: Any, capsys: Any
) -> None:
    cases = _load_gold_cases()
    client, _calls = _make_fake_client(cases, _echo_true_label)
    _run_triage_eval(monkeypatch, [], client)
    out = capsys.readouterr().out
    assert "100%" in out, f"stdout does not report 100% accuracy when every case is right:\n{out}"


def test_stdout_reports_zero_when_every_case_is_misclassified(
    monkeypatch: Any, capsys: Any
) -> None:
    cases = _load_gold_cases()
    client, _calls = _make_fake_client(cases, _a_wrong_label)
    _run_triage_eval(monkeypatch, [], client)
    out = capsys.readouterr().out
    assert "0%" in out, f"stdout does not report 0% accuracy when every case is wrong:\n{out}"


# ---------------------------------------------------------------------------
# The threshold gate
# ---------------------------------------------------------------------------


def test_no_floor_flag_exits_zero_even_at_zero_accuracy(monkeypatch: Any) -> None:
    cases = _load_gold_cases()
    client, _calls = _make_fake_client(cases, _a_wrong_label)
    exit_code = _run_triage_eval(monkeypatch, [], client)
    assert exit_code == 0, "with no floor supplied, a 0% pass still exited non-zero"


def test_below_floor_exits_nonzero(monkeypatch: Any) -> None:
    cases = _load_gold_cases()
    client, _calls = _make_fake_client(cases, _a_wrong_label)
    exit_code = _run_triage_eval(monkeypatch, ["--min-accuracy", "0.5"], client)
    assert exit_code != 0, "0% accuracy against a 0.5 floor did not exit non-zero"


def test_at_or_above_floor_exits_zero(monkeypatch: Any) -> None:
    cases = _load_gold_cases()
    client, _calls = _make_fake_client(cases, _echo_true_label)
    exit_code = _run_triage_eval(monkeypatch, ["--min-accuracy", "1.0"], client)
    assert exit_code == 0, "100% accuracy against a 1.0 floor exited non-zero"


# ---------------------------------------------------------------------------
# Stays out of CI
# ---------------------------------------------------------------------------


def test_never_wired_into_the_ci_workflow() -> None:
    module = _discover_triage_eval_module()
    ci_path = _repo_root() / ".github" / "workflows" / "ci.yml"
    assert ci_path.is_file(), f"no CI workflow at {ci_path}"
    ci_text = ci_path.read_text(encoding="utf-8")
    assert module not in ci_text, (
        f"{module!r} appears in {ci_path} — this pass is meant to stay a local, "
        "on-demand check rather than something CI runs"
    )
    assert "eval-triage" not in ci_text, (
        f"'eval-triage' appears in {ci_path} — this pass is meant to stay a local, "
        "on-demand check rather than something CI runs"
    )
