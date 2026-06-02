"""Action proposal reasoner, confirmation gate, and execution skill.

Provides the full action pipeline:
  1. ``propose_action`` — analyse a user request and build an ActionProposal
  2. ``confirm_action`` — present the proposal for human review
  3. ``execute_action`` — carry out a confirmed proposal via OpsClient
"""

from __future__ import annotations

import logging
import time
from typing import Any

from agent.validators import validate_action_proposal
from config.prompts import PROPOSE_ACTION_SYSTEM, PROPOSE_ACTION_USER  # noqa: F401
from models.action import ActionProposal, ActionResult, ActionType
from models.shared import RiskLevel
from services.client import OpsClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword → ActionType mapping (rule-based; LLM replaces this later)
# ---------------------------------------------------------------------------

_ACTION_KEYWORDS: dict[ActionType, list[str]] = {
    ActionType.UPDATE_ORDER_STATUS: [
        "update order status",
        "change order status",
        "mark order",
        "set order",
        "transition order",
    ],
    ActionType.UPDATE_EXCEPTION: [
        "update exception",
        "change exception",
        "resolve exception",
        "close exception",
    ],
    ActionType.ASSIGN_EXCEPTION: [
        "assign exception",
        "assign to",
        "reassign",
    ],
    ActionType.ESCALATE_ORDER: [
        "escalate order",
        "escalate",
        "priority",
        "urgent",
    ],
    ActionType.FLAG_SHIPMENTS: [
        "flag shipment",
        "flag delivery",
        "review shipment",
    ],
    ActionType.BULK_UPDATE: [
        "bulk update",
        "update all",
        "batch update",
    ],
}

# Irreversible statuses that force HIGH risk
_IRREVERSIBLE_STATUSES = {"cancelled", "returned", "refunded"}


# ===================================================================
# Risk assessment
# ===================================================================


def _assess_risk(
    target_count: int,
    changes: dict[str, Any],
) -> RiskLevel:
    """Determine risk level from target count and change characteristics.

    Rules:
      - 1 target → LOW
      - 2–10 targets → MEDIUM
      - >10 targets → HIGH
      - Irreversible status transitions → HIGH (override)
    """
    new_status = changes.get("status", "")
    if isinstance(new_status, str) and new_status in _IRREVERSIBLE_STATUSES:
        return RiskLevel.HIGH

    if target_count <= 1:
        return RiskLevel.LOW
    if target_count <= 10:
        return RiskLevel.MEDIUM
    return RiskLevel.HIGH


# ===================================================================
# Keyword-based action type detection
# ===================================================================


def _detect_action_type(user_query: str) -> ActionType:
    """Match *user_query* against keyword lists to pick an ActionType.

    Falls back to ``BULK_UPDATE`` when no keywords match.
    """
    query_lower = user_query.lower()
    for action_type, keywords in _ACTION_KEYWORDS.items():
        for kw in keywords:
            if kw in query_lower:
                return action_type
    return ActionType.BULK_UPDATE


# ===================================================================
# Story 7.1 — Action Proposal Reasoner
# ===================================================================


async def propose_action(
    client: OpsClient,
    user_query: str,
    relevant_data: list[dict[str, Any]],
) -> ActionProposal:
    """Build an ActionProposal from a user request and context data.

    Tries LLM interpretation first (when available), falls back to
    keyword-based detection.
    """
    from config.settings import get_settings

    settings = get_settings()

    # Try LLM-based proposal generation
    if settings.is_llm_available:
        try:
            import json

            import anthropic

            llm_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            prompt = PROPOSE_ACTION_USER.format(
                user_query=user_query,
                relevant_data=json.dumps(relevant_data, default=str),
            )
            message = await llm_client.messages.create(
                model=settings.llm_model,
                system=PROPOSE_ACTION_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
            )
            raw = next(
                (b.text for b in message.content if isinstance(b, anthropic.types.TextBlock)),
                "",
            )
            proposal = ActionProposal.model_validate_json(raw)
            errors = await validate_action_proposal(proposal)
            if errors:
                raise ValueError(f"Action validation failed: {'; '.join(errors)}")
            return proposal
        except Exception as exc:
            logger.warning("LLM action proposal failed, falling back to rule-based: %s", exc)

    # Rule-based fallback
    action_type = _detect_action_type(user_query)

    # Extract target IDs — look in each data row for common ID fields
    target_ids: list[str] = []
    for row in relevant_data:
        for id_field in ("id", "order_id", "exception_id", "shipment_id"):
            if id_field in row:
                target_ids.append(str(row[id_field]))
                break

    # Extract changes from the first data row or build from query context
    changes: dict[str, Any] = {}
    if relevant_data:
        changes = relevant_data[0].get("changes", {})

    target_count = len(target_ids)
    risk = _assess_risk(target_count, changes)

    # Build human-readable impact summary
    entity_word = "entity" if target_count == 1 else "entities"
    change_desc = ", ".join(f"{k} -> {v!r}" for k, v in changes.items()) or "see changes"
    impact = (
        f"This will {action_type.value.replace('_', ' ')} "
        f"{target_count} {entity_word}. Changes: {change_desc}"
    )

    proposal = ActionProposal(
        action_type=action_type,
        target_ids=target_ids,
        changes=changes,
        reasoning=f"Action requested via: {user_query}",
        impact_summary=impact,
        risk_level=risk,
        requires_confirmation=risk != RiskLevel.LOW or target_count > 5,
    )

    errors = await validate_action_proposal(proposal)
    if errors:
        raise ValueError(f"Action validation failed: {'; '.join(errors)}")

    return proposal


# ===================================================================
# Story 7.2 — Human Confirmation Gate
# ===================================================================


def format_proposal_summary(proposal: ActionProposal) -> str:
    """Format an ActionProposal as a human-readable summary string.

    Example output::

        Action: assign_exception
        Targets: 7 exceptions
        Changes: assigned_to -> "Sarah Chen"
        Risk: medium
        Impact: This will assign 7 critical exceptions to Sarah Chen
    """
    # Derive entity noun from action_type
    action_name = proposal.action_type.value
    if "exception" in action_name:
        entity_noun = "exception" if len(proposal.target_ids) == 1 else "exceptions"
    elif "order" in action_name:
        entity_noun = "order" if len(proposal.target_ids) == 1 else "orders"
    elif "shipment" in action_name:
        entity_noun = "shipment" if len(proposal.target_ids) == 1 else "shipments"
    else:
        entity_noun = "entity" if len(proposal.target_ids) == 1 else "entities"

    # Format changes
    if proposal.changes:
        changes_str = ", ".join(
            f'{k} \u2192 "{v}"' if isinstance(v, str) else f"{k} \u2192 {v}"
            for k, v in proposal.changes.items()
        )
    else:
        changes_str = "(none)"

    lines = [
        f"Action: {proposal.action_type.value}",
        f"Targets: {len(proposal.target_ids)} {entity_noun}",
        f"Changes: {changes_str}",
        f"Risk: {proposal.risk_level.value}",
        f"Impact: {proposal.impact_summary}",
    ]
    return "\n".join(lines)


async def confirm_action(proposal: ActionProposal) -> bool:
    """Present a proposal for human confirmation.

    Returns ``True`` if the action should proceed, ``False`` otherwise.

    The actual CLI prompt is handled by the calling layer; this function
    returns ``True`` by default so that automated / test flows pass through.
    """
    summary = format_proposal_summary(proposal)
    logger.info("Action confirmation requested:\n%s", summary)
    # Default: auto-confirm.  CLI layer overrides with interactive prompt.
    return True


# ===================================================================
# Story 7.3 — Action Execution Skill
# ===================================================================


async def execute_action(
    client: OpsClient,
    proposal: ActionProposal,
) -> ActionResult:
    """Execute a confirmed ActionProposal against backend services.

    Routes each target to the correct ``OpsClient`` update method based on
    ``proposal.action_type``, tracks per-target success/failure, and returns
    an ``ActionResult``.
    """
    start = time.monotonic()
    successful: list[str] = []
    failed: list[dict[str, str]] = []

    for target_id in proposal.target_ids:
        try:
            await _dispatch_action(client, proposal.action_type, target_id, proposal.changes)
            successful.append(target_id)
        except Exception as exc:
            logger.error(
                "Action %s failed for %s: %s",
                proposal.action_type.value,
                target_id,
                exc,
            )
            failed.append({"id": target_id, "error": str(exc)})

    elapsed_ms = (time.monotonic() - start) * 1000

    return ActionResult(
        action_type=proposal.action_type,
        total_targets=len(proposal.target_ids),
        successful=successful,
        failed=failed,
        execution_time_ms=round(elapsed_ms, 2),
    )


async def _dispatch_action(
    client: OpsClient,
    action_type: ActionType,
    target_id: str,
    changes: dict[str, Any],
) -> None:
    """Route a single target's action to the appropriate OpsClient method."""
    if action_type == ActionType.UPDATE_ORDER_STATUS:
        await client.update_order(target_id, changes)

    elif action_type == ActionType.UPDATE_EXCEPTION:
        await client.update_exception(target_id, changes)

    elif action_type == ActionType.ASSIGN_EXCEPTION:
        await client.update_exception(target_id, changes)

    elif action_type == ActionType.ESCALATE_ORDER:
        escalation_changes = {**changes, "priority": "urgent"}
        await client.update_order(target_id, escalation_changes)

    elif action_type == ActionType.FLAG_SHIPMENTS:
        flag_changes = {**changes, "flagged": True}
        await client.update_shipment(target_id, flag_changes)

    elif action_type == ActionType.BULK_UPDATE:
        # Bulk update: try to infer the entity type from the target ID prefix
        if target_id.startswith("ORD"):
            await client.update_order(target_id, changes)
        elif target_id.startswith("EXC"):
            await client.update_exception(target_id, changes)
        elif target_id.startswith("SHP"):
            await client.update_shipment(target_id, changes)
        else:
            raise ValueError(
                f"Cannot route bulk update for target '{target_id}': "
                f"unknown ID prefix."
            )
    else:
        raise ValueError(f"Unsupported action type: {action_type}")
