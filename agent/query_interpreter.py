"""Query interpretation reasoner for natural language to QueryPlan.

Converts free-form user queries into structured QueryPlan objects.
Currently uses a rule-based fallback; LLM integration is stubbed for
future wiring once the Anthropic SDK is available.
"""

from __future__ import annotations

import logging
import re

from config.prompts import INTERPRET_QUERY_SYSTEM, INTERPRET_QUERY_USER
from config.settings import get_settings
from models.query import DataFilter, QueryPlan
from models.shared import TargetSystem, UserIntent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _build_prompt(
    user_query: str,
    conversation_context: list[dict[str, str]],
) -> tuple[str, str]:
    """Build (system_prompt, user_prompt) for the LLM call.

    Returns the fully-rendered prompt pair that will be sent to the model
    once LLM integration is wired up.
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

    system_prompt = INTERPRET_QUERY_SYSTEM
    user_prompt = INTERPRET_QUERY_USER.format(
        user_query=user_query,
        conversation_context=context_str,
    )
    return system_prompt, user_prompt


# ---------------------------------------------------------------------------
# Rule-based fallback interpreter
# ---------------------------------------------------------------------------

# Pattern tuples: (compiled regex, intent, target_systems, primary_entity, extra_filters)
_PATTERNS: list[
    tuple[re.Pattern[str], UserIntent, list[TargetSystem], str, list[DataFilter]]
] = [
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
# Public API
# ---------------------------------------------------------------------------


def _suggest_alternatives(user_query: str) -> list[str]:
    """Suggest alternative queries based on partial regex matches.

    Returns a list of example queries the user could try.
    """
    query_lower = user_query.lower()
    suggestions: list[str] = []

    # Check for partial keyword matches
    if "order" in query_lower:
        suggestions.extend([
            "show all orders",
            "list pending orders",
            "show at-risk orders",
        ])
    if "exception" in query_lower or "error" in query_lower or "issue" in query_lower:
        suggestions.extend([
            "show exceptions",
            "list critical exceptions",
        ])
    if "inventory" in query_lower or "stock" in query_lower or "warehouse" in query_lower:
        suggestions.extend([
            "show inventory",
            "show low-stock items",
        ])
    if "shipment" in query_lower or "shipping" in query_lower or "delivery" in query_lower:
        suggestions.extend([
            "show shipments",
            "show sla breaches",
        ])
    if "update" in query_lower or "assign" in query_lower or "change" in query_lower:
        suggestions.extend([
            "assign exceptions to [name]",
            "update order status to shipped",
        ])
    if "report" in query_lower:
        suggestions.extend([
            "generate exception summary report",
            "show sla compliance report",
        ])

    # If no partial matches, return supported categories
    if not suggestions:
        suggestions = [
            "I can help with: order lookups, exception tracking, "
            "inventory status, shipment tracking, SLA compliance, "
            "and operational reports.",
        ]

    return suggestions


async def interpret_query(
    user_query: str,
    conversation_context: list[dict[str, str]],
) -> QueryPlan:
    """Interpret a natural-language query into a structured QueryPlan.

    Tries LLM interpretation first (when available), falls back to
    rule-based pattern matching, then to clarification.
    """
    settings = get_settings()
    system_prompt, user_prompt = _build_prompt(user_query, conversation_context)

    # Try LLM interpretation if available
    if settings.is_llm_available:
        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            message = await client.messages.create(
                model=settings.llm_model,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=1024,
            )
            text = message.content[0].text
            return QueryPlan.model_validate_json(text)
        except Exception as exc:
            logger.warning("LLM query interpretation failed: %s", exc)
            logger.debug("LLM raw response: %s", locals().get("text", "N/A"))
    else:
        logger.debug("LLM unavailable, using rule-based interpreter")

    # Rule-based fallback
    plan = _rule_based_interpret(user_query)
    if plan is not None:
        return plan

    # If nothing matches, request clarification
    return QueryPlan(
        intent=UserIntent.CLARIFICATION_NEEDED,
        target_systems=[],
        primary_entity="unknown",
        filters=[],
        confidence=0.2,
        reasoning="Could not determine intent from the query — requesting clarification.",
    )
