"""The executable definition of a stuck order.

Covers the shared vocabulary a triager needs before any tooling exists: the
closed root-cause taxonomy, the case record model, the stuck predicate's
dependence on the instant it is handed, and the triage package's freedom from
the wall clock.

Every ``triage`` import and every file read happens *inside* a test body on
purpose. These behaviours are asserted before the package exists, and an import
at module scope would turn "the package is missing" into a collection error
instead of a failing test.

Nothing here names a concrete module, class or function inside ``triage``. The
symbols are discovered from what the package exports, so the author keeps the
naming and the layout while the behaviour stays pinned.
"""

import ast
import inspect
import json
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

# The three root causes the taxonomy is closed over.
TAXONOMY_VALUES = {"inventory", "carrier", "address_exception"}

# A value deliberately outside the taxonomy, used as rejection input.
NON_TAXONOMY_VALUE = "supplier_delay"

# The fields a case record carries. `shipment` is nullable, so it is exercised
# separately from the fields whose omission must be refused.
RECORD_FIELDS = (
    "case_id",
    "as_of",
    "label",
    "order",
    "line_items",
    "exceptions",
    "shipment",
    "inventory",
)
NON_NULLABLE_RECORD_FIELDS = tuple(f for f in RECORD_FIELDS if f != "shipment")

# Ten years, expressed as a duration so no calendar edge case (a leap day) can
# make the shift itself the reason a verdict moves.
TEN_YEARS = timedelta(days=3653)

# Parameter names that read as "the evaluation instant". Used only to locate
# the instant argument, never to require a particular spelling of it.
INSTANT_PARAM_NAMES = {
    "as_of",
    "asof",
    "at",
    "evaluated_at",
    "instant",
    "moment",
    "now",
    "when",
}

# Wall-clock calls, expressed as fully-qualified targets after import aliases
# are resolved.
BANNED_CLOCK_CALLS = {
    "datetime.datetime.now",
    "datetime.datetime.utcnow",
    "datetime.datetime.today",
    "datetime.date.today",
    "time.time",
    "time.monotonic",
}

# The same calls in their un-aliased spelling, caught even when the import that
# introduced the name is not one this file could resolve (a local import, a
# re-export).
BANNED_BARE_CALLS = {
    "datetime.now",
    "datetime.utcnow",
    "datetime.today",
    "date.today",
    "time.time",
    "time.monotonic",
}


# ---------------------------------------------------------------------------
# Locating the repo's artefacts. Read lazily, from inside test bodies.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_records() -> list[dict[str, Any]]:
    """The gold set as raw JSON objects, one per non-blank line."""
    path = _repo_root() / "evals" / "triage_dataset.jsonl"
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _import_triage() -> Any:
    import triage

    return triage


# ---------------------------------------------------------------------------
# Discovering the exported symbols by what they are, not by what they're called
# ---------------------------------------------------------------------------


def _defined_in_triage(obj: Any) -> bool:
    return getattr(obj, "__module__", "").split(".")[0] == "triage"


def _exported(module: Any, predicate: Any) -> dict[str, Any]:
    found = {}
    for name in dir(module):
        if name.startswith("_"):
            continue
        obj = getattr(module, name)
        if predicate(obj):
            found[name] = obj
    return found


def _taxonomy(module: Any) -> Any:
    """The root-cause enumeration exported from the package."""
    enums = _exported(
        module,
        lambda o: isinstance(o, type) and issubclass(o, Enum) and _defined_in_triage(o),
    )
    candidates = {n: e for n, e in enums.items() if TAXONOMY_VALUES & {m.value for m in e}}
    assert candidates, (
        "no enumeration exported from `triage` carries a root-cause value; "
        f"enumerations exported: {sorted(enums)}"
    )
    assert len(candidates) == 1, f"the root-cause enumeration is ambiguous: {sorted(candidates)}"
    return next(iter(candidates.values()))


def _record_model(module: Any) -> Any:
    """The case record model exported from the package.

    Located by the two fields that make something a labelled case rather than
    by the full field list, so the full list stays an assertion.
    """
    models = _exported(
        module,
        lambda o: isinstance(o, type) and issubclass(o, BaseModel) and _defined_in_triage(o),
    )
    candidates = {n: m for n, m in models.items() if {"case_id", "label"} <= set(m.model_fields)}
    assert candidates, (
        "no model exported from `triage` declares a labelled case; "
        f"models exported: {sorted(models)}"
    )
    # A subclass of another candidate is a specialisation, not the record model.
    roots = {
        n: m
        for n, m in candidates.items()
        if not any(m is not o and issubclass(m, o) for o in candidates.values())
    }
    assert len(roots) == 1, f"the case record model is ambiguous: {sorted(roots)}"
    return next(iter(roots.values()))


def _instant_params(func: Any) -> list[str]:
    names = []
    for name, param in inspect.signature(func).parameters.items():
        annotation = "" if param.annotation is inspect.Parameter.empty else str(param.annotation)
        if name.lower() in INSTANT_PARAM_NAMES or "datetime" in annotation:
            names.append(name)
    return names


def _stuck_predicate(module: Any) -> Any:
    """The exported callable that decides whether a case is stuck.

    Located by the shape the contract gives it — it takes the evaluation
    instant as an explicit argument alongside the case — with the name only
    used to break a tie between several such callables.
    """
    funcs = _exported(module, lambda o: inspect.isfunction(o) and _defined_in_triage(o))
    candidates = {
        n: f
        for n, f in funcs.items()
        if _instant_params(f) and len(inspect.signature(f).parameters) >= 2
    }
    if len(candidates) > 1:
        narrowed = {n: f for n, f in candidates.items() if "stuck" in n.lower()}
        if narrowed:
            candidates = narrowed
    assert candidates, (
        "no callable exported from `triage` takes an evaluation instant as an "
        f"explicit argument beside a case; callables exported: {sorted(funcs)}"
    )
    assert len(candidates) == 1, f"the stuck predicate is ambiguous: {sorted(candidates)}"
    return next(iter(candidates.values()))


def _call_predicate(func: Any, case: Any, instant: Any) -> Any:
    """Invoke by keyword, so parameter order stays the author's to choose."""
    instant_name = _instant_params(func)[0]
    others = [p for p in inspect.signature(func).parameters if p != instant_name]
    assert others, f"{func.__name__} takes an instant but no case to evaluate"
    return func(**{others[0]: case, instant_name: instant})


def _as_datetime(value: Any) -> Any:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


# ---------------------------------------------------------------------------
# Wall-clock detection over the parsed AST
# ---------------------------------------------------------------------------


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> fully-qualified target, for every import in a module."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                aliases[local] = alias.name if alias.asname else alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _dotted(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _clock_calls(source: str, label: str) -> list[str]:
    tree = ast.parse(source)
    aliases = _import_aliases(tree)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted(node.func)
        if dotted is None:
            continue
        head, _, rest = dotted.partition(".")
        resolved = aliases.get(head, head)
        qualified = f"{resolved}.{rest}" if rest else resolved
        if qualified in BANNED_CLOCK_CALLS or dotted in BANNED_BARE_CALLS:
            hits.append(f"{label}:{node.lineno} calls {dotted}()")
    return hits


def _triage_modules() -> list[Path]:
    package = _repo_root() / "triage"
    assert package.is_dir(), f"no triage package at {package}"
    modules = sorted(package.rglob("*.py"))
    assert modules, f"the triage package at {package} contains no modules"
    return modules


# ---------------------------------------------------------------------------
# The taxonomy is closed
# ---------------------------------------------------------------------------


def test_root_cause_taxonomy_has_exactly_three_members():
    # the taxonomy is closed: the package exports a root-cause enumeration
    # whose members are exactly inventory / carrier / address_exception.
    taxonomy = _taxonomy(_import_triage())
    values = {member.value for member in taxonomy}
    assert values == TAXONOMY_VALUES, f"root causes are {sorted(values)}"
    assert len(list(taxonomy)) == 3, "the enumeration carries duplicate or aliased members"


def test_root_cause_taxonomy_admits_no_fourth_value():
    # closed means closed: a fourth root cause is refused, not absorbed. Three
    # members existing is not the same claim as a fourth being impossible, so
    # the enumeration is fed a value it has to reject.
    taxonomy = _taxonomy(_import_triage())
    with pytest.raises(ValueError):
        taxonomy(NON_TAXONOMY_VALUE)


# ---------------------------------------------------------------------------
# The case record model
# ---------------------------------------------------------------------------


def test_case_record_model_declares_every_case_field():
    # a case is self-contained: the exported record model declares the case's
    # identity, its evaluation instant, its label and the four payload slots a
    # triager reads.
    model = _record_model(_import_triage())
    missing = [f for f in RECORD_FIELDS if f not in model.model_fields]
    assert not missing, f"the case record model does not declare {missing}"


def test_case_record_model_rejects_a_case_missing_a_field():
    # the record model is a check, not a container: dropping any non-nullable
    # case field must fail validation rather than quietly default away. Fed
    # input it is required to refuse, once per field.
    model = _record_model(_import_triage())
    complete = _load_records()[0]
    model.model_validate(complete)  # the control: the unmodified record passes
    for field in NON_NULLABLE_RECORD_FIELDS:
        incomplete = {k: v for k, v in complete.items() if k != field}
        with pytest.raises(ValidationError):
            model.model_validate(incomplete)


def test_case_record_model_accepts_a_case_with_no_shipment():
    # a stuck order need not have a shipment yet, so the shipment slot is
    # nullable rather than merely present.
    model = _record_model(_import_triage())
    unshipped = dict(_load_records()[0])
    unshipped["shipment"] = None
    model.model_validate(unshipped)


def test_case_record_model_rejects_a_label_outside_the_taxonomy():
    # the closed taxonomy reaches the record: a case labelled with a fourth
    # root cause is refused at validation, not stored as free text.
    model = _record_model(_import_triage())
    mislabelled = dict(_load_records()[0])
    mislabelled["label"] = NON_TAXONOMY_VALUE
    with pytest.raises(ValidationError):
        model.model_validate(mislabelled)


# ---------------------------------------------------------------------------
# The stuck predicate
# ---------------------------------------------------------------------------


def test_stuck_predicate_returns_a_boolean_verdict():
    # the predicate answers a yes/no question about a case at an instant, and
    # the answer is a bool rather than a truthy score or a reason string.
    triage = _import_triage()
    predicate = _stuck_predicate(triage)
    model = _record_model(triage)
    for raw in _load_records():
        case = model.model_validate(raw)
        verdict = _call_predicate(predicate, case, _as_datetime(case.as_of))
        assert isinstance(verdict, bool), (
            f"case {raw.get('case_id')!r}: verdict is {type(verdict).__name__}, not bool"
        )


def test_stuck_verdict_depends_on_the_instant_the_predicate_is_handed():
    # the instant is genuinely read: holding the case constant and moving only
    # the argument by ten years changes the verdict for at least one case. A
    # predicate that ignored the instant would answer identically and fail
    # here. Cases are built through ordinary validation, never constructed
    # around it.
    triage = _import_triage()
    predicate = _stuck_predicate(triage)
    model = _record_model(triage)
    moved = []
    for raw in _load_records():
        case = model.model_validate(raw)
        as_of = _as_datetime(case.as_of)
        baseline = _call_predicate(predicate, case, as_of)
        for shifted in (as_of - TEN_YEARS, as_of + TEN_YEARS):
            if _call_predicate(predicate, case, shifted) != baseline:
                moved.append(raw.get("case_id"))
                break
    assert moved, (
        "shifting the evaluation instant by ten years changed no verdict, so "
        "the predicate does not read the instant it is handed"
    )


def test_every_gold_case_is_stuck_at_its_own_evaluation_instant():
    # the gold set and the definition agree: no case is carried in the set
    # that the definition of stuck does not consider stuck.
    triage = _import_triage()
    predicate = _stuck_predicate(triage)
    model = _record_model(triage)
    not_stuck = []
    for raw in _load_records():
        case = model.model_validate(raw)
        if not _call_predicate(predicate, case, _as_datetime(case.as_of)):
            not_stuck.append(raw.get("case_id"))
    assert not not_stuck, f"gold cases the stuck predicate rejects: {not_stuck}"


# ---------------------------------------------------------------------------
# The package is replayable
# ---------------------------------------------------------------------------


def test_no_triage_module_reads_the_wall_clock():
    # replayability: a case scored today and the same case scored next year
    # must reach the same verdict, which holds only if the evaluation instant
    # arrives as an argument. Every module in the package is parsed and every
    # call resolved through its imports, so an aliased or re-exported clock
    # call is caught the same as a plain one.
    root = _repo_root()
    hits = []
    for path in _triage_modules():
        hits += _clock_calls(path.read_text(encoding="utf-8"), str(path.relative_to(root)))
    assert not hits, "triage reads the wall clock:\n" + "\n".join(hits)
