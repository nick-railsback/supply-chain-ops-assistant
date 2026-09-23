"""The frozen gold set of stuck-order cases and the disclosure that ships with it.

Covers the dataset's size and shape, the self-containment that lets it be
replayed from a fresh clone with no database and no network, the honesty of the
labeling disclosure, and the type-check coverage of the package it belongs to.

Every ``triage`` import and every file read happens *inside* a test body on
purpose: these behaviours are asserted before the dataset exists, and a read at
module scope would turn "the dataset is missing" into a collection error
instead of a failing test.

Nothing here asserts that any computed value equals a case's label. The labels
are a human judgement the system is allowed to be wrong about; an oracle that
re-derived them would destroy the only thing they are for.
"""

import ast
import json
import re
import tomllib
from enum import Enum
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel, ValidationError

from models.oms import LineItem, Order, OrderException
from models.tms import Shipment
from models.wms import InventoryItem

MIN_CASES = 15
MAX_CASES = 25

# The seven keys the disclosure block carries, and the four whose values are
# fixed by how the set was labelled rather than by what is in it.
DISCLOSURE_KEYS = {
    "seed_value",
    "captured_at",
    "case_count",
    "annotators",
    "labeling",
    "adjudication_pass",
    "inter_annotator_agreement",
}
FIXED_DISCLOSURE_VALUES = {
    "annotators": "1",
    "labeling": "blind-human",
    "adjudication_pass": "false",
    "inter_annotator_agreement": "unmeasured",
}

# The package the embedded payloads must match. Membership is tested by import
# path, so any model under it counts and no list of entities is hardcoded into
# the traversal.
DOMAIN_MODEL_ROOT = "models"

# The payload slots and domain models embedded as of today. Asserted as a lower
# bound on what the derived mapping covers, never as the mapping itself.
KNOWN_PAYLOAD_FIELDS = {"order", "line_items", "exceptions", "shipment", "inventory"}
KNOWN_DOMAIN_MODELS = {Order, LineItem, OrderException, Shipment, InventoryItem}

# The packages the build already type-checks. Adding to this list is safe;
# dropping an entry silently removes a package from the build's type check with
# every suite still green, so they are asserted alongside the new one.
MYPY_PACKAGES_ALREADY_CHECKED = ("agent", "models", "services", "seed", "cli", "config")

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

# Word families, not phrases. Criterion is that the *section* survives; the
# wording inside it is the author's to improve, and a literal-phrase oracle
# would break the first time a heading is reworded or a line rewrapped.
HAND_LABELED_RE = re.compile(
    r"\b(hand|hand-?labell?ed|hand-?assigned|by-hand|manual|manually|human|humans)\b",
    re.IGNORECASE,
)
COST_RE = re.compile(
    r"\b(cost|costs|costly|limitation|limitations|limits|trade-?offs?|weakness|weaknesses"
    r"|downside|downsides|caveat|caveats|sacrifices?|price|expense|risks?"
    r"|give[sn]?\s+up|buys?\s+us)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Locating the repo's artefacts. Read lazily, from inside test bodies.
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _dataset_path() -> Path:
    return _repo_root() / "evals" / "triage_dataset.jsonl"


def _load_records() -> list[dict[str, Any]]:
    text = _dataset_path().read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _read_disclosure() -> str:
    return (_repo_root() / "evals" / "triage_dataset.md").read_text(encoding="utf-8")


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
    enums = _exported(
        module,
        lambda o: isinstance(o, type) and issubclass(o, Enum) and _defined_in_triage(o),
    )
    candidates = {
        n: e
        for n, e in enums.items()
        if {"inventory", "carrier", "address_exception"} & {m.value for m in e}
    }
    assert candidates, (
        "no enumeration exported from `triage` carries a root-cause value; "
        f"enumerations exported: {sorted(enums)}"
    )
    assert len(candidates) == 1, f"the root-cause enumeration is ambiguous: {sorted(candidates)}"
    return next(iter(candidates.values()))


def _record_model(module: Any) -> Any:
    models = _exported(
        module,
        lambda o: isinstance(o, type) and issubclass(o, BaseModel) and _defined_in_triage(o),
    )
    candidates = {n: m for n, m in models.items() if {"case_id", "label"} <= set(m.model_fields)}
    assert candidates, (
        "no model exported from `triage` declares a labelled case; "
        f"models exported: {sorted(models)}"
    )
    roots = {
        n: m
        for n, m in candidates.items()
        if not any(m is not o and issubclass(m, o) for o in candidates.values())
    }
    assert len(roots) == 1, f"the case record model is ambiguous: {sorted(roots)}"
    return next(iter(roots.values()))


# ---------------------------------------------------------------------------
# Deriving the payload -> domain model mapping from the record model itself
# ---------------------------------------------------------------------------


def _domain_models(annotation: Any) -> set[Any]:
    """Every domain model reachable through list / optional / union wrappers."""
    if get_origin(annotation) is None:
        if (
            isinstance(annotation, type)
            and issubclass(annotation, BaseModel)
            and annotation.__module__.split(".")[0] == DOMAIN_MODEL_ROOT
        ):
            return {annotation}
        return set()
    found: set[Any] = set()
    for arg in get_args(annotation):
        found |= _domain_models(arg)
    return found


def _payload_map(record_model: Any) -> dict[str, set[Any]]:
    """Field name -> the domain models it embeds.

    Read off the record model's own annotations rather than listed here, so a
    payload slot added to the record later is covered by the same assertion
    with no edit to this file.
    """
    mapping = {}
    for name, field in record_model.model_fields.items():
        models = _domain_models(field.annotation)
        if models:
            mapping[name] = models
    return mapping


def _check_payload(value: Any, models: set[Any], trail: str, problems: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _check_payload(item, models, f"{trail}[{index}]", problems)
        return
    if not isinstance(value, dict):
        problems.append(f"{trail}: expected an object payload, got {type(value).__name__}")
        return
    failures = []
    for model in sorted(models, key=lambda m: m.__name__):
        try:
            model.model_validate(value)
        except ValidationError as exc:
            failures.append(f"{model.__name__}: {exc.errors()}")
            continue
        undeclared = sorted(set(value) - set(model.model_fields))
        if undeclared:
            problems.append(f"{trail}: keys {model.__name__} does not declare: {undeclared}")
        return
    problems.append(f"{trail}: matches no domain model. {failures}")


# ---------------------------------------------------------------------------
# Walking a record for identifiers, wherever they sit
# ---------------------------------------------------------------------------


def _values_for_key(node: Any, key: str) -> Any:
    """Every value stored under `key`, at any depth, in any nesting."""
    if isinstance(node, dict):
        for name, value in node.items():
            if name == key:
                yield value
            yield from _values_for_key(value, key)
    elif isinstance(node, list):
        for item in node:
            yield from _values_for_key(item, key)


# ---------------------------------------------------------------------------
# Reading the disclosure without a YAML dependency
# ---------------------------------------------------------------------------


def _split_disclosure(text: str) -> tuple[list[str], str]:
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", (
        "the disclosure does not open with a frontmatter fence"
    )
    closing = [i for i in range(1, len(lines)) if lines[i].strip() == "---"]
    assert closing, "the disclosure's frontmatter block is never closed"
    end = closing[0]
    return lines[1:end], "\n".join(lines[end + 1 :])


def _frontmatter_pairs(text: str) -> list[tuple[str, str]]:
    block, _ = _split_disclosure(text)
    pairs = []
    for line in block:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        assert separator, f"frontmatter line is not a key/value pair: {line!r}"
        pairs.append((key.strip(), value.strip().strip("\"'")))
    return pairs


def _sections(body: str) -> list[tuple[str, str]]:
    """(heading, body) for each heading, with the body newline-normalised.

    Collapsing the body to a single whitespace-normalised string is what keeps
    a hand-wrapped paragraph readable as present; a line-anchored match would
    report real content as absent the first time the file is rewrapped.
    """
    collected: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        heading = None if fenced else HEADING_RE.match(line)
        if heading:
            current = (heading.group(2), [])
            collected.append(current)
        elif current is not None:
            current[1].append(line)
    return [(head, " ".join(" ".join(lines).split())) for head, lines in collected]


def _capture_seed() -> int:
    """The seed the capture script drew its cases from, read off its AST."""
    path = _repo_root() / "scripts" / "capture_triage_cases.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[int] = set()

    def note(name: str | None, value: Any) -> None:
        if not name or "seed" not in name.lower():
            return
        if isinstance(value, ast.Constant) and isinstance(value.value, int):
            if not isinstance(value.value, bool):
                found.add(value.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    note(target.id, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name):
                note(node.target.id, node.value)
        elif isinstance(node, ast.keyword):
            note(node.arg, node.value)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            positional = node.args.posonlyargs + node.args.args
            defaults = node.args.defaults
            for arg, default in zip(positional[len(positional) - len(defaults) :], defaults):
                note(arg.arg, default)
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
                if default is not None:
                    note(arg.arg, default)

    assert len(found) == 1, (
        "the capture script must name exactly one integer seed for the "
        f"disclosure to be checkable against it; found {sorted(found)}"
    )
    return found.pop()


# ---------------------------------------------------------------------------
# The dataset's size and shape
# ---------------------------------------------------------------------------


def test_gold_set_holds_between_fifteen_and_twenty_five_records():
    # a set small enough to label by hand and large enough to score: one JSON
    # object per line, between fifteen and twenty-five of them inclusive.
    lines = [ln for ln in _dataset_path().read_text(encoding="utf-8").splitlines() if ln.strip()]
    records = []
    for number, line in enumerate(lines, start=1):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"line {number} is not valid JSON: {exc}") from exc
        assert isinstance(parsed, dict), f"line {number} is not a JSON object"
        records.append(parsed)
    assert MIN_CASES <= len(records) <= MAX_CASES, f"the gold set holds {len(records)} records"


def test_every_case_is_uniquely_identified():
    # cases are addressable: every record carries a case_id and no two share one.
    case_ids = [record.get("case_id") for record in _load_records()]
    assert all(case_ids), "a record carries no case_id"
    duplicates = sorted({cid for cid in case_ids if case_ids.count(cid) > 1})
    assert not duplicates, f"case_id values used more than once: {duplicates}"


def test_every_case_validates_against_the_exported_record_model():
    # the file on disk and the definition in the package agree.
    model = _record_model(_import_triage())
    failures = []
    for record in _load_records():
        try:
            model.model_validate(record)
        except ValidationError as exc:
            failures.append(f"{record.get('case_id')}: {exc.errors()}")
    assert not failures, "cases the record model rejects:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# The taxonomy over the gold set
# ---------------------------------------------------------------------------


def test_every_case_label_is_a_taxonomy_member():
    taxonomy = _taxonomy(_import_triage())
    permitted = {member.value for member in taxonomy}
    labels = {record.get("label") for record in _load_records()}
    assert labels <= permitted, f"labels outside the taxonomy: {sorted(labels - permitted)}"


def test_every_taxonomy_member_labels_at_least_one_case():
    # no root cause is unrepresented, so a scored pass can be wrong about each
    # of the three rather than only about the ones that happen to appear.
    taxonomy = _taxonomy(_import_triage())
    labels = {record.get("label") for record in _load_records()}
    unrepresented = sorted({member.value for member in taxonomy} - labels)
    assert not unrepresented, f"root causes no case carries: {unrepresented}"


# ---------------------------------------------------------------------------
# Self-containment: a case names nothing outside itself
# ---------------------------------------------------------------------------


def test_every_case_is_referentially_closed():
    # referential closure: the whole record is walked for any key named
    # order_id or sku at whatever depth it sits, so a payload slot added later
    # is covered by the same assertion. Every order_id in a record is that
    # record's own order, and every sku it names is stocked in its own
    # inventory. Nothing points outside the case.
    problems = []
    for record in _load_records():
        case_id = record.get("case_id", "<unidentified>")
        order = record.get("order")
        if not isinstance(order, dict) or not order.get("order_id"):
            problems.append(f"{case_id}: the record has no order_id of its own")
            continue
        own = order["order_id"]

        order_ids = list(_values_for_key(record, "order_id"))
        assert order_ids, f"{case_id}: no order_id anywhere in the record"
        foreign = sorted({oid for oid in order_ids if oid != own})
        if foreign:
            problems.append(f"{case_id}: names order_id {foreign}, but is order {own}")

        inventory = record.get("inventory") or []
        stocked = {item.get("sku") for item in inventory if isinstance(item, dict)}
        skus = list(_values_for_key(record, "sku"))
        assert skus, f"{case_id}: no sku anywhere in the record"
        unstocked = sorted({sku for sku in skus if sku not in stocked})
        if unstocked:
            problems.append(f"{case_id}: names sku {unstocked}, absent from its own inventory")
    assert not problems, "cases that name something outside themselves:\n" + "\n".join(problems)


def test_payload_slots_are_derived_from_the_record_model():
    # the payload-to-model mapping is read off the record model's annotations
    # rather than listed by this test, which is what lets a slot added to the
    # record later be validated without this assertion being rewritten. The
    # entities embedded today are asserted as a floor on that derivation, not
    # as its definition.
    mapping = _payload_map(_record_model(_import_triage()))
    assert mapping, "the record model embeds no domain model at all"
    assert KNOWN_PAYLOAD_FIELDS <= set(mapping), (
        f"payload slots not resolved to a domain model: "
        f"{sorted(KNOWN_PAYLOAD_FIELDS - set(mapping))}"
    )
    embedded = {model for models in mapping.values() for model in models}
    missing = sorted(m.__name__ for m in KNOWN_DOMAIN_MODELS - embedded)
    assert not missing, f"domain models the record no longer embeds: {missing}"


def test_every_embedded_payload_validates_against_its_domain_model():
    # a snapshot that has drifted from the shape the services return fails
    # here rather than sitting quietly wrong. No payload field is exempt:
    # every slot the record model resolves to a domain model is validated, and
    # a key the model does not declare counts as drift too.
    model = _record_model(_import_triage())
    mapping = _payload_map(model)
    problems: list[str] = []
    for record in _load_records():
        case_id = record.get("case_id", "<unidentified>")
        for field, models in mapping.items():
            if field not in record:
                if model.model_fields[field].is_required():
                    problems.append(f"{case_id}.{field}: absent from the record")
                continue
            _check_payload(record[field], models, f"{case_id}.{field}", problems)
    assert not problems, "payloads that do not match the domain models:\n" + "\n".join(problems)


# ---------------------------------------------------------------------------
# The labeling disclosure
# ---------------------------------------------------------------------------


def test_disclosure_frontmatter_carries_exactly_the_seven_keys():
    # the disclosure states how the set was labelled, in the form a test can
    # hold to a value. The key set is exact in both directions: a missing key
    # hides a caveat, an extra one is a claim nothing checks.
    pairs = _frontmatter_pairs(_read_disclosure())
    keys = [key for key, _ in pairs]
    repeated = sorted({k for k in keys if keys.count(k) > 1})
    assert not repeated, f"frontmatter keys declared more than once: {repeated}"
    assert set(keys) == DISCLOSURE_KEYS, (
        f"missing: {sorted(DISCLOSURE_KEYS - set(keys))}, "
        f"unexpected: {sorted(set(keys) - DISCLOSURE_KEYS)}"
    )


def test_disclosure_states_the_labeling_process_it_actually_used():
    # one annotator, labelling blind, with no adjudication pass and no
    # measured agreement. The set makes no claim to a process it did not run.
    frontmatter = dict(_frontmatter_pairs(_read_disclosure()))
    for key, expected in FIXED_DISCLOSURE_VALUES.items():
        actual = frontmatter.get(key, "")
        assert actual.strip().lower() == expected, f"{key} discloses {actual!r}, not {expected!r}"


def test_disclosure_counts_and_seed_match_reality_not_merely_presence():
    # the two facts that can silently drift are checked against the things
    # they describe: the record count against the dataset, and the seed
    # against the script that captured from it. A stale disclosure fails here
    # rather than sitting quietly wrong.
    frontmatter = dict(_frontmatter_pairs(_read_disclosure()))
    assert int(frontmatter["case_count"]) == len(_load_records()), (
        f"case_count discloses {frontmatter['case_count']}, "
        f"the dataset holds {len(_load_records())}"
    )
    assert int(frontmatter["seed_value"]) == _capture_seed(), (
        f"seed_value discloses {frontmatter['seed_value']}, "
        f"the capture script drew from {_capture_seed()}"
    )


def test_disclosure_carries_two_non_empty_prose_sections():
    # the reasoning survives beside the facts: one section for why the labels
    # were assigned by hand, one for what that choice costs, each with a body
    # under it. Only headings and non-emptiness are asserted — the wording is
    # the author's, and bodies are whitespace-normalised so rewrapping a
    # paragraph never reads as deleting it.
    _, body = _split_disclosure(_read_disclosure())
    sections = _sections(body)
    assert len(sections) >= 2, f"the disclosure carries {len(sections)} prose sections, not two"
    headings = [heading for heading, _ in sections]
    bodies = dict(sections)

    rationale = [h for h in headings if HAND_LABELED_RE.search(h)]
    assert rationale, f"no section explains the hand labelling; headings are {headings}"
    cost = [h for h in headings if COST_RE.search(h)]
    assert cost, f"no section states what hand labelling costs; headings are {headings}"

    distinct = [(a, b) for a in rationale for b in cost if a != b]
    assert distinct, "the rationale and its cost share one heading rather than being two sections"
    for heading in distinct[0]:
        assert bodies[heading], f"section {heading!r} has a heading but no body"


# ---------------------------------------------------------------------------
# The build type-checks what this adds, and still type-checks what it had
# ---------------------------------------------------------------------------


def test_mypy_checks_triage_without_dropping_a_package_it_already_checked():
    # type-check coverage only grows. `triage` joins the checked list, and
    # every package already on it stays: dropping one removes a package from
    # the build's type check silently, with the whole suite still green. The
    # preservation half is the half no new feature would think to assert.
    config = tomllib.loads((_repo_root() / "pyproject.toml").read_text(encoding="utf-8"))
    checked = config["tool"]["mypy"]["files"]
    assert "triage" in checked, f"mypy does not type-check triage; it checks {checked}"
    dropped = [pkg for pkg in MYPY_PACKAGES_ALREADY_CHECKED if pkg not in checked]
    assert not dropped, f"packages no longer type-checked: {dropped}"
