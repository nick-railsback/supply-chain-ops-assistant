"""Interpreter evaluation harness — scores natural-language → QueryPlan accuracy.

Grades the query interpreter against the gold labels in ``evals/dataset.jsonl``
across two arms:

  - ``rule``  deterministic rule-based interpreter. No API key, no services,
              runs in CI. This is the honest baseline.
  - ``llm``   Claude interpreter (``interpret_query``). Requires ``anthropic``
              installed and ``ANTHROPIC_API_KEY`` set. Opt-in; costs tokens.

Metrics:
  - intent accuracy           exact match of classified intent
  - target-system match       exact set match (Jaccard reported alongside)
  - filter extraction         micro-recall of expected (field, value) pairs
  - clarification P / R        does it correctly *decline to guess* on ambiguous
                               queries (and not over-clarify answerable ones)?
  - confidence reliability     confidence band → empirical accuracy

Usage:
    python -m evals.run_eval                  # rule arm (default)
    python -m evals.run_eval --arm llm        # llm arm (needs key + anthropic)
    python -m evals.run_eval --arm both       # comparative lift table
    python -m evals.run_eval --verbose        # per-case pass/fail detail

The ``llm`` arm calls ``interpret_query``, which falls back to the rule path on
any LLM error. To keep that honest, every arm reports its ``interpretation_source``
mix (``llm`` / ``llm_repaired`` / ``rule_based`` / ``fallback``) so a degraded
LLM scored as its fallback is visible rather than hidden.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.table import Table

from agent.query_interpreter import _rule_based_interpret, interpret_query
from models.query import QueryPlan
from models.shared import UserIntent

DATASET = Path(__file__).parent / "dataset.jsonl"
REPORT = Path(__file__).parent / "REPORT.md"
console = Console()

CLARIFY = UserIntent.CLARIFICATION_NEEDED.value


# ---------------------------------------------------------------------------
# Interpreter arms
# ---------------------------------------------------------------------------


def rule_interpret(query: str) -> QueryPlan:
    """Pure rule-based interpretation (no LLM, no env dependence)."""
    plan = _rule_based_interpret(query)
    if plan is not None:
        return plan
    # Mirror interpret_query's no-match clarification branch.
    return QueryPlan(
        intent=UserIntent.CLARIFICATION_NEEDED,
        target_systems=[],
        primary_entity="unknown",
        filters=[],
        confidence=0.2,
        reasoning="Could not determine intent from the query.",
    )


def llm_interpret(query: str) -> QueryPlan:
    """LLM interpretation via the public pipeline (rule fallback on error)."""
    return asyncio.run(interpret_query(query, []))


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _norm(value: object) -> str:
    return str(value).strip().lower()


@dataclass
class Tally:
    n: int = 0
    intent_correct: int = 0
    systems_exact: int = 0
    jaccard_sum: float = 0.0
    # filter extraction (only over cases that declare expected_filters)
    filter_cases: int = 0
    filter_expected: int = 0
    filter_matched: int = 0
    filter_cases_perfect: int = 0
    # clarification confusion matrix
    clar_tp: int = 0
    clar_fp: int = 0
    clar_fn: int = 0
    # confidence reliability: band -> [count, correct]
    bands: dict[str, list[int]] = field(default_factory=dict)
    # interpretation_source -> count (llm / llm_repaired / rule_based / fallback)
    sources: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


def _band(conf: float) -> str:
    if conf < 0.5:
        return "0.0–0.5"
    if conf < 0.7:
        return "0.5–0.7"
    if conf < 0.8:
        return "0.7–0.8"
    if conf < 0.9:
        return "0.8–0.9"
    return "0.9–1.0"


def score(plan: QueryPlan, case: dict) -> tuple[Tally, bool]:
    """Score a single plan against one gold case; returns a one-row Tally."""
    t = Tally(n=1)

    intent_ok = plan.intent.value == case["expected_intent"]
    t.intent_correct = int(intent_ok)

    pred_sys = {s.value for s in plan.target_systems}
    exp_sys = set(case["expected_systems"])
    systems_ok = pred_sys == exp_sys
    t.systems_exact = int(systems_ok)
    union = pred_sys | exp_sys
    t.jaccard_sum = (len(pred_sys & exp_sys) / len(union)) if union else 1.0

    exp_filters = case.get("expected_filters") or []
    if exp_filters:
        t.filter_cases = 1
        exp = {(f["field"], _norm(f["value"])) for f in exp_filters}
        got = {(f.field, _norm(f.value)) for f in plan.filters}
        matched = len(exp & got)
        t.filter_expected = len(exp)
        t.filter_matched = matched
        t.filter_cases_perfect = int(matched == len(exp))

    pred_clar = plan.intent.value == CLARIFY
    true_clar = case["expected_intent"] == CLARIFY
    if pred_clar and true_clar:
        t.clar_tp = 1
    elif pred_clar and not true_clar:
        t.clar_fp = 1
    elif (not pred_clar) and true_clar:
        t.clar_fn = 1

    case_correct = intent_ok and systems_ok
    t.bands[_band(plan.confidence)] = [1, int(case_correct)]
    t.sources[plan.interpretation_source] = 1

    if not case_correct:
        t.failures.append(
            f"{case['id']}: got intent={plan.intent.value} systems={sorted(pred_sys)} "
            f"(expected {case['expected_intent']} {sorted(exp_sys)})"
        )
    return t, case_correct


def aggregate(rows: list[Tally]) -> Tally:
    agg = Tally()
    for r in rows:
        agg.n += r.n
        agg.intent_correct += r.intent_correct
        agg.systems_exact += r.systems_exact
        agg.jaccard_sum += r.jaccard_sum
        agg.filter_cases += r.filter_cases
        agg.filter_expected += r.filter_expected
        agg.filter_matched += r.filter_matched
        agg.filter_cases_perfect += r.filter_cases_perfect
        agg.clar_tp += r.clar_tp
        agg.clar_fp += r.clar_fp
        agg.clar_fn += r.clar_fn
        agg.failures.extend(r.failures)
        for band, (cnt, corr) in r.bands.items():
            cur = agg.bands.setdefault(band, [0, 0])
            cur[0] += cnt
            cur[1] += corr
        for src, cnt in r.sources.items():
            agg.sources[src] = agg.sources.get(src, 0) + cnt
    return agg


# ---------------------------------------------------------------------------
# Derived metrics + rendering
# ---------------------------------------------------------------------------


def metrics(a: Tally) -> dict[str, float]:
    n = a.n or 1
    clar_p_den = a.clar_tp + a.clar_fp
    clar_r_den = a.clar_tp + a.clar_fn
    return {
        "intent_acc": a.intent_correct / n,
        "systems_acc": a.systems_exact / n,
        "systems_jaccard": a.jaccard_sum / n,
        "filter_recall": (
            (a.filter_matched / a.filter_expected) if a.filter_expected else float("nan")
        ),
        "clar_precision": (a.clar_tp / clar_p_den) if clar_p_den else float("nan"),
        "clar_recall": (a.clar_tp / clar_r_den) if clar_r_den else float("nan"),
    }


def _pct(x: float) -> str:
    return "n/a" if x != x else f"{x:.0%}"  # x != x → NaN


def run_arm(interp, dataset: list[dict]) -> Tally:
    rows = [score(interp(c["query"]), c)[0] for c in dataset]
    return aggregate(rows)


def render_single(name: str, a: Tally) -> Table:
    m = metrics(a)
    t = Table(title=f"Interpreter eval — {name} arm  (N={a.n})", title_style="bold")
    t.add_column("Metric")
    t.add_column("Score", justify="right")
    t.add_row("Intent accuracy", f"{a.intent_correct}/{a.n}  ({_pct(m['intent_acc'])})")
    t.add_row("Target-system match (exact)", f"{a.systems_exact}/{a.n}  ({_pct(m['systems_acc'])})")
    t.add_row("Target-system Jaccard", _pct(m["systems_jaccard"]))
    t.add_row(
        f"Filter extraction (over {a.filter_cases} filter cases)",
        f"{a.filter_matched}/{a.filter_expected} pairs  ({_pct(m['filter_recall'])})",
    )
    t.add_row("Clarification precision", _pct(m["clar_precision"]))
    t.add_row("Clarification recall", _pct(m["clar_recall"]))
    return t


def render_reliability(name: str, a: Tally) -> Table:
    t = Table(title=f"Confidence reliability — {name} arm", title_style="dim")
    t.add_column("Confidence band")
    t.add_column("N", justify="right")
    t.add_column("Empirical accuracy", justify="right")
    for band in ["0.0–0.5", "0.5–0.7", "0.7–0.8", "0.8–0.9", "0.9–1.0"]:
        cnt, corr = a.bands.get(band, [0, 0])
        if cnt:
            t.add_row(band, str(cnt), f"{corr / cnt:.0%}")
    return t


def render_lift(arms: dict[str, Tally]) -> Table:
    t = Table(title="Comparative lift (rule → llm)", title_style="bold")
    t.add_column("Metric")
    for name in arms:
        t.add_column(name, justify="right")
    if len(arms) == 2:
        t.add_column("Δ", justify="right")
    keys = [
        ("intent_acc", "Intent accuracy"),
        ("systems_acc", "Target-system match"),
        ("filter_recall", "Filter extraction"),
        ("clar_precision", "Clarification precision"),
        ("clar_recall", "Clarification recall"),
    ]
    mets = {name: metrics(a) for name, a in arms.items()}
    for key, label in keys:
        row = [label] + [_pct(mets[name][key]) for name in arms]
        if len(arms) == 2:
            a, b = (mets[name][key] for name in arms)
            delta = (b - a) if (a == a and b == b) else float("nan")
            row.append("n/a" if delta != delta else f"{delta:+.0%}")
        t.add_row(*row)
    return t


def write_report(arms: dict[str, Tally]) -> None:
    lines = [
        "# Interpreter Eval Report",
        "",
        "_Generated by `make eval`. Numbers are measured, not asserted._",
        "",
    ]
    for name, a in arms.items():
        m = metrics(a)
        lines += [
            f"## {name} arm (N={a.n})",
            "",
            f"- Intent accuracy: **{a.intent_correct}/{a.n} ({_pct(m['intent_acc'])})**",
            f"- Target-system match (exact): {a.systems_exact}/{a.n} ({_pct(m['systems_acc'])})",
            f"- Filter extraction: {a.filter_matched}/{a.filter_expected} pairs "
            f"({_pct(m['filter_recall'])}) over {a.filter_cases} cases",
            f"- Clarification precision / recall: "
            f"{_pct(m['clar_precision'])} / {_pct(m['clar_recall'])}",
        ]
        if a.sources:
            mix = ", ".join(f"`{src}`={cnt}" for src, cnt in sorted(a.sources.items()))
            lines.append(f"- Interpretation source mix: {mix}")
        lines.append("")
    REPORT.write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser(description="Query interpreter eval harness")
    ap.add_argument("--arm", choices=["rule", "llm", "both"], default="rule")
    ap.add_argument("--dataset", type=Path, default=DATASET)
    ap.add_argument("--verbose", action="store_true", help="print per-case failures")
    ap.add_argument(
        "--min-intent-accuracy",
        type=float,
        default=None,
        help="exit 1 if any arm's intent accuracy is below this (CI regression gate)",
    )
    ap.add_argument(
        "--min-systems-accuracy",
        type=float,
        default=None,
        help="exit 1 if any arm's target-system accuracy is below this",
    )
    args = ap.parse_args()

    dataset = [json.loads(line) for line in args.dataset.read_text().splitlines() if line.strip()]

    wanted = ["rule", "llm"] if args.arm == "both" else [args.arm]
    arms: dict[str, Tally] = {}
    for name in wanted:
        if name == "llm":
            from config.settings import get_settings

            if not get_settings().is_llm_available:
                console.print(
                    "[yellow]llm arm skipped:[/yellow] set ANTHROPIC_API_KEY (and install "
                    "`anthropic`) to run the Claude tool-use interpreter against the gold set."
                )
                continue
            arms[name] = run_arm(llm_interpret, dataset)
        else:
            arms[name] = run_arm(rule_interpret, dataset)

    if not arms:
        console.print("[red]No arms ran.[/red]")
        return

    console.print()
    for name, a in arms.items():
        console.print(render_single(name, a))
        console.print(render_reliability(name, a))
        if a.sources:
            mix = ", ".join(f"{src}={cnt}" for src, cnt in sorted(a.sources.items()))
            console.print(f"[dim]interpretation source mix → {mix}[/dim]")
        console.print()

    if len(arms) > 1:
        console.print(render_lift(arms))
        console.print()

    if args.verbose:
        for name, a in arms.items():
            if a.failures:
                console.print(f"[bold]{name} arm — misses ({len(a.failures)}):[/bold]")
                for f in a.failures:
                    console.print(f"  [red]✗[/red] {f}")
                console.print()

    write_report(arms)
    # One-line headline the author can quote.
    head = " | ".join(
        f"{name}: intent {metrics(a)['intent_acc']:.0%}, systems {metrics(a)['systems_acc']:.0%}"
        for name, a in arms.items()
    )
    console.print(f"[dim]Report written to {REPORT}. Headline → {head}[/dim]")

    # Threshold gate: a CI regression guard, evaluated after the report writes.
    breaches: list[str] = []
    for name, a in arms.items():
        m = metrics(a)
        if args.min_intent_accuracy is not None and m["intent_acc"] < args.min_intent_accuracy:
            breaches.append(
                f"{name} arm intent accuracy {m['intent_acc']:.1%} "
                f"< required {args.min_intent_accuracy:.1%}"
            )
        if args.min_systems_accuracy is not None and m["systems_acc"] < args.min_systems_accuracy:
            breaches.append(
                f"{name} arm systems accuracy {m['systems_acc']:.1%} "
                f"< required {args.min_systems_accuracy:.1%}"
            )
    if breaches:
        for b in breaches:
            console.print(f"[red]threshold not met:[/red] {b}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
