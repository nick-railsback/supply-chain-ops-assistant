"""Query interpretation: natural language to a structured QueryPlan.

Two paths, LLM-first:

  * **LLM (default when a key is configured)** — Claude is called with a single
    forced tool (`emit_query_plan`), so the interpretation comes back as
    schema-valid arguments rather than free-text JSON to parse. Confidence is
    derived deterministically from model-emitted signals (see
    ``_confidence_from_signals``), and one repair retry is attempted on a
    validation failure before degrading.
  * **Rule-based (typed fallback)** — a deterministic keyword/regex interpreter
    that recognizes a subset of phrasings. It runs when no key is set, when the
    SDK is missing, or when the LLM path errors out.

Which path produced a plan is recorded on ``QueryPlan.interpretation_source`` so
a fallback is never silent. ``evals/`` measures both paths against gold labels.
"""

from __future__ import annotations

import logging
import re
import time

from agent.llm import LLMUnavailable, structured_call
from agent.validators import validate_query_plan
from config.prompts import INTERPRET_QUERY_SYSTEM, INTERPRET_QUERY_USER
from models.oms import ExceptionStatus, ExceptionType, OrderChannel, OrderStatus
from models.query import ConfidenceSignals, DataFilter, QueryPlan
from models.shared import Severity, TargetSystem, UserIntent
from models.tms import ShipmentStatus, SLAStatus
from seed.constants import CARRIERS, CUSTOMER_TIERS, FULFILLMENT_CENTERS, PRODUCT_CATALOG

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Live enum injection (context engineering)
# ---------------------------------------------------------------------------


def _field_value_reference() -> str:
    """Assemble the allowed-value domains for enum / fixed-domain fields from the
    canonical models and seed constants, so the interpreter sees the real values
    it may emit — not just field names.

    Built once at import (see ``INTERPRET_SYSTEM_PROMPT``); the string is stable,
    so the system-prompt block still hits the prompt cache.
    """
    categories = sorted({str(p["category"]) for p in PRODUCT_CATALOG})
    centers = [str(c["id"]) for c in FULFILLMENT_CENTERS]
    carriers = [str(c["name"]) for c in CARRIERS]

    def line(label: str, values: list[str]) -> str:
        return f"  {label}: " + ", ".join(values)

    return "\n".join(
        [
            "# Allowed values for enum / fixed-domain fields",
            "# (emit a filter value only from the matching list)",
            line("oms order.status", [s.value for s in OrderStatus]),
            line("oms order.channel", [s.value for s in OrderChannel]),
            line("oms order.customer_tier", list(CUSTOMER_TIERS)),
            line("oms exception.exception_type", [s.value for s in ExceptionType]),
            line("oms exception.severity", [s.value for s in Severity]),
            line("oms exception.status", [s.value for s in ExceptionStatus]),
            line("wms inventory.category", categories),
            line("wms inventory.fulfillment_center", centers),
            line("tms shipment.carrier", carriers),
            line("tms shipment.shipment_status", [s.value for s in ShipmentStatus]),
            line("tms shipment.sla_status", [s.value for s in SLAStatus]),
        ]
    )


# The interpreter system prompt = static domain knowledge + live value domains.
INTERPRET_SYSTEM_PROMPT = INTERPRET_QUERY_SYSTEM + "\n" + _field_value_reference()

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _build_prompt(
    user_query: str,
    conversation_context: list[dict[str, str]],
) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for the LLM call.

    Returns the fully-rendered prompt pair sent to the model. The system prompt
    supplies domain knowledge; the tool schema (not the prompt) enforces output
    structure.
    """
    context_str = ""
    if conversation_context:
        lines = [
            f"  {turn.get('role', 'user')}: {turn.get('content', '')}"
            for turn in conversation_context
        ]
        context_str = "\n".join(lines)
    else:
        context_str = "  (no prior conversation)"

    system_prompt = INTERPRET_SYSTEM_PROMPT
    user_prompt = INTERPRET_QUERY_USER.format(
        user_query=user_query,
        conversation_context=context_str,
    )
    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Rule-based fallback interpreter
# ---------------------------------------------------------------------------

# Pattern tuples: (compiled regex, intent, target_systems, primary_entity, extra_filters)
_PATTERNS: list[tuple[re.Pattern[str], UserIntent, list[TargetSystem], str, list[DataFilter]]] = [
    # --- Orders ---
    (
        re.compile(r"\b(?:show|list|get|find|display)\b.*\borders\b", re.IGNORECASE),
        UserIntent.STATUS_CHECK,
        [TargetSystem.OMS],
        "order",
        [],
    ),
    (
        re.compile(r"\bat[- ]?risk\b.*\borders?\b|\borders?\b.*\bat[- ]?risk\b", re.IGNORECASE),
        UserIntent.STATUS_CHECK,
        [TargetSystem.OMS],
        "order",
        [DataFilter(field="at_risk", operator="eq", value=True)],
    ),
    (
        re.compile(r"\bpending\b.*\borders?\b|\borders?\b.*\bpending\b", re.IGNORECASE),
        UserIntent.STATUS_CHECK,
        [TargetSystem.OMS],
        "order",
        [DataFilter(field="status", operator="eq", value="pending")],
    ),
    # --- Exceptions ---
    (
        re.compile(
            r"\b(?:show|list|get|find|display)\b.*\bexceptions?\b",
            re.IGNORECASE,
        ),
        UserIntent.STATUS_CHECK,
        [TargetSystem.OMS],
        "exception",
        [],
    ),
    # --- Inventory ---
    (
        re.compile(
            r"\b(?:show|list|get|find|display)\b.*\b(?:inventory|stock)\b",
            re.IGNORECASE,
        ),
        UserIntent.STATUS_CHECK,
        [TargetSystem.WMS],
        "inventory",
        [],
    ),
    (
        re.compile(r"\blow[- ]?stock\b", re.IGNORECASE),
        UserIntent.STATUS_CHECK,
        [TargetSystem.WMS],
        "inventory",
        [DataFilter(field="below_reorder_point", operator="eq", value=True)],
    ),
    # --- Shipments ---
    (
        re.compile(
            r"\b(?:show|list|get|find|display)\b.*\bshipments?\b",
            re.IGNORECASE,
        ),
        UserIntent.STATUS_CHECK,
        [TargetSystem.TMS],
        "shipment",
        [],
    ),
    (
        re.compile(r"\bsla\b.*\bbreach", re.IGNORECASE),
        UserIntent.STATUS_CHECK,
        [TargetSystem.TMS],
        "shipment",
        [DataFilter(field="sla_status", operator="eq", value="breached")],
    ),
    # --- Cross-system ---
    (
        re.compile(
            r"\b(?:orders?\b.*\bshipments?\b|shipments?\b.*\borders?\b)",
            re.IGNORECASE,
        ),
        UserIntent.CROSS_SYSTEM_QUERY,
        [TargetSystem.OMS, TargetSystem.TMS],
        "order",
        [],
    ),
]


def _rule_based_interpret(user_query: str) -> QueryPlan | None:
    """Attempt to match user_query against known patterns.

    Returns a QueryPlan on match, or None if no pattern matches.
    """
    for pattern, intent, targets, entity, filters in _PATTERNS:
        if pattern.search(user_query):
            requires_join = len(targets) > 1
            join_key = "order_id" if requires_join else None
            return QueryPlan(
                intent=intent,
                target_systems=targets,
                primary_entity=entity,
                filters=list(filters),
                confidence=0.75,
                reasoning=f"Rule-based match for '{entity}' query",
                requires_join=requires_join,
                join_key=join_key,
            )
    return None


# ---------------------------------------------------------------------------
# LLM interpreter (tool-use, structured output)
# ---------------------------------------------------------------------------

# A curated tool schema — deliberately NOT QueryPlan.model_json_schema(). The
# Pydantic schema has an `Any`-typed DataFilter.value and would leak internal
# shape; inlining the enums and field descriptions guides the model far better.
INTERPRET_TOOL_NAME = "emit_query_plan"
INTERPRET_TOOL_DESCRIPTION = (
    "Return the structured interpretation of the user's supply-chain operations query."
)
INTERPRET_TOOL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": [i.value for i in UserIntent]},
        "target_systems": {
            "type": "array",
            "items": {"type": "string", "enum": [s.value for s in TargetSystem]},
            "description": "oms=orders, wms=inventory, tms=shipments. Empty for clarification.",
        },
        "primary_entity": {
            "type": "string",
            "description": "order | exception | inventory | shipment | unknown",
        },
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "operator": {
                        "type": "string",
                        "enum": [
                            "eq",
                            "neq",
                            "in",
                            "not_in",
                            "gt",
                            "gte",
                            "lt",
                            "lte",
                            "between",
                            "contains",
                            "starts_with",
                        ],
                    },
                    "value": {"description": "string, number, bool, or list"},
                },
                "required": ["field", "operator", "value"],
            },
        },
        "requires_join": {"type": "boolean"},
        "join_key": {"type": ["string", "null"]},
        "reasoning": {"type": "string", "description": "one sentence: how you read the query"},
        # These booleans drive the confidence score deterministically.
        "signals": {
            "type": "object",
            "properties": {
                "all_filter_fields_known": {"type": "boolean"},
                "entity_unambiguous": {"type": "boolean"},
                "single_clear_intent": {"type": "boolean"},
                "time_reference_resolved": {
                    "type": "boolean",
                    "description": "true if no time reference, or it is fully resolved",
                },
            },
            "required": [
                "all_filter_fields_known",
                "entity_unambiguous",
                "single_clear_intent",
                "time_reference_resolved",
            ],
        },
        "model_confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "your own 0–1 confidence (stored for comparison)",
        },
    },
    "required": ["intent", "target_systems", "primary_entity", "filters", "reasoning", "signals"],
}


def _confidence_from_signals(s: ConfidenceSignals, intent: UserIntent) -> float:
    """Explainable confidence: derived from named signals, not a magic number."""
    if intent is UserIntent.CLARIFICATION_NEEDED:
        return 0.2
    base = 0.55
    base += 0.20 * s.single_clear_intent
    base += 0.10 * s.entity_unambiguous
    base += 0.10 * s.all_filter_fields_known
    base += 0.05 * s.time_reference_resolved
    return round(min(base, 0.99), 2)  # never claim certainty


def _plan_from_tool_input(data: dict, source: str) -> QueryPlan:
    """Map the tool_use input dict to a QueryPlan with explainable confidence."""
    signals = ConfidenceSignals(**data.get("signals", {}))
    intent = UserIntent(data["intent"])
    return QueryPlan(
        intent=intent,
        target_systems=[TargetSystem(s) for s in data.get("target_systems", [])],
        primary_entity=data.get("primary_entity", "unknown"),
        filters=[DataFilter(**f) for f in data.get("filters", [])],
        requires_join=bool(data.get("requires_join", False)),
        join_key=data.get("join_key"),
        confidence=_confidence_from_signals(signals, intent),
        reasoning=data.get("reasoning", ""),
        interpretation_source=source,
        confidence_signals=signals,
        model_confidence=data.get("model_confidence"),
    )


async def _call_interpreter(system_prompt: str, user_prompt: str) -> tuple[dict, dict]:
    """Call the interpreter tool, returning (tool_input, metrics).

    metrics carries input/output token counts and the wall-clock latency of the
    call, for observability (logged here and surfaced on the QueryPlan).
    """
    start = time.monotonic()
    data, usage = await structured_call(
        system=system_prompt,
        user=user_prompt,
        tool_name=INTERPRET_TOOL_NAME,
        tool_description=INTERPRET_TOOL_DESCRIPTION,
        input_schema=INTERPRET_TOOL_SCHEMA,
        temperature=0.0,
    )
    metrics = {**usage, "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    logger.debug("interpret metrics=%s", metrics)
    return data, metrics


def _attach_metrics(plan: QueryPlan, metrics: dict) -> QueryPlan:
    """Record token usage and latency on a plan (sum across repair attempts)."""
    plan.input_tokens = metrics.get("input_tokens")
    plan.output_tokens = metrics.get("output_tokens")
    plan.latency_ms = metrics.get("latency_ms")
    return plan


def _combine_metrics(first: dict, second: dict) -> dict:
    """Aggregate two interpreter calls (initial + repair) into one metrics dict."""

    def _add(a: float | None, b: float | None) -> float | None:
        return (a or 0) + (b or 0) if (a is not None or b is not None) else None

    return {
        "input_tokens": _add(first.get("input_tokens"), second.get("input_tokens")),
        "output_tokens": _add(first.get("output_tokens"), second.get("output_tokens")),
        "latency_ms": _add(first.get("latency_ms"), second.get("latency_ms")),
    }


async def llm_interpret(
    user_query: str,
    conversation_context: list[dict[str, str]],
) -> QueryPlan:
    """Tool-use interpretation with ONE repair retry on validation failure."""
    system_prompt, user_prompt = _build_prompt(user_query, conversation_context)

    data, metrics = await _call_interpreter(system_prompt, user_prompt)
    plan = _plan_from_tool_input(data, source="llm")
    errors = await validate_query_plan(plan)
    if not errors:
        return _attach_metrics(plan, metrics)

    # One repair attempt: feed the validator's complaints back to the model.
    repair_prompt = (
        f"{user_prompt}\n\nYour previous plan failed validation:\n"
        + "\n".join(f"- {e}" for e in errors)
        + "\n\nReturn a corrected plan."
    )
    data, repair_metrics = await _call_interpreter(system_prompt, repair_prompt)
    plan = _plan_from_tool_input(data, source="llm_repaired")
    _attach_metrics(plan, _combine_metrics(metrics, repair_metrics))
    errors = await validate_query_plan(plan)
    if errors:
        raise ValueError(f"LLM plan failed validation after repair: {errors}")
    return plan


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _summarize_plan(plan: QueryPlan) -> str:
    """One-line summary of an interpretation, stored as conversation context so a
    later turn can resolve references ("those", "the same ones") back to it.
    """
    systems = ", ".join(s.value for s in plan.target_systems) or "none"
    if plan.filters:
        flt = "; ".join(f"{f.field} {f.operator} {f.value}" for f in plan.filters)
    else:
        flt = "no filters"
    return f"interpreted as {plan.intent.value} on [{systems}] ({flt})"


def _suggest_alternatives(user_query: str) -> list[str]:
    """Suggest alternative queries based on partial regex matches.

    Returns a list of example queries the user could try.
    """
    query_lower = user_query.lower()
    suggestions: list[str] = []

    # Check for partial keyword matches
    if "order" in query_lower:
        suggestions.extend(
            [
                "show all orders",
                "list pending orders",
                "show at-risk orders",
            ]
        )
    if "exception" in query_lower or "error" in query_lower or "issue" in query_lower:
        suggestions.extend(
            [
                "show exceptions",
                "list critical exceptions",
            ]
        )
    if "inventory" in query_lower or "stock" in query_lower or "warehouse" in query_lower:
        suggestions.extend(
            [
                "show inventory",
                "show low-stock items",
            ]
        )
    if "shipment" in query_lower or "shipping" in query_lower or "delivery" in query_lower:
        suggestions.extend(
            [
                "show shipments",
                "show sla breaches",
            ]
        )
    if "update" in query_lower or "assign" in query_lower or "change" in query_lower:
        suggestions.extend(
            [
                "assign exceptions to [name]",
                "update order status to shipped",
            ]
        )
    if "report" in query_lower:
        suggestions.extend(
            [
                "generate exception summary report",
                "show sla compliance report",
            ]
        )

    # If no partial matches, return supported categories
    if not suggestions:
        suggestions = [
            "I can help with: order lookups, exception tracking, "
            "inventory status, shipment tracking, SLA compliance, "
            "and operational reports.",
        ]

    return suggestions


def _rule_fallback(user_query: str, source: str) -> QueryPlan:
    """Rule-based interpretation, tagged with WHY we fell back (never silent)."""
    plan = _rule_based_interpret(user_query)
    if plan is None:
        plan = QueryPlan(
            intent=UserIntent.CLARIFICATION_NEEDED,
            target_systems=[],
            primary_entity="unknown",
            filters=[],
            confidence=0.2,
            reasoning="Could not determine intent from the query — requesting clarification.",
        )
    plan.interpretation_source = source
    return plan


async def interpret_query(
    user_query: str,
    conversation_context: list[dict[str, str]],
) -> QueryPlan:
    """Interpret a natural-language query into a structured QueryPlan.

    LLM-first: Claude tool-use is attempted whenever a key is configured. The
    rule-based interpreter is a typed fallback, and the reason for any fallback
    is surfaced on ``QueryPlan.interpretation_source`` (``rule_based`` when the
    LLM is simply unavailable, ``fallback`` when an LLM attempt errored out).
    """
    try:
        return await llm_interpret(user_query, conversation_context)
    except LLMUnavailable:
        logger.debug("LLM unavailable; using rule-based interpreter")
        return _rule_fallback(user_query, source="rule_based")
    except Exception as exc:  # noqa: BLE001 — degrade, but record WHY
        logger.warning("LLM interpretation failed (%s); falling back to rule-based", exc)
        return _rule_fallback(user_query, source="fallback")
