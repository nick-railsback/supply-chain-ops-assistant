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

from agent.llm import LLMUnavailable, structured_call
from agent.validators import validate_action_proposal
from config.prompts import PROPOSE_ACTION_SYSTEM, PROPOSE_ACTION_USER  # noqa: F401
from models.action import ActionProposal, ActionResult, ActionType
from models.shared import RiskLevel
from services.client import OpsClient

logger = logging.getLogger(__name__)


class ActionNotConfirmedError(RuntimeError):
    """Raised when ``execute_action`` is asked to run a proposal that requires
    confirmation without explicit confirmation.

    The library refuses to mutate backend systems on a risky proposal unless a
    human (or an explicit ``confirmed=True``) has approved it — it never
    defaults to "yes".
    """


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

# Irreversible statuses that force HIGH risk.
# cancelled: terminal OrderStatus (see validators.ORDER_STATUS_TRANSITIONS)
# returned:  irreversible ShipmentStatus (models/tms.py)
_IRREVERSIBLE_STATUSES = frozenset({"cancelled", "returned"})

_MEDIUM_TARGET_MAX = 10  # <= this -> MEDIUM; above -> HIGH
_AUTO_CONFIRM_TARGET_MAX = 5  # LOW risk above this still requires confirmation
_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}


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
    if target_count <= _MEDIUM_TARGET_MAX:
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

    # Try LLM-based proposal generation, routed through the shared structured
    # client (forced tool-use + guaranteed client teardown — see agent/llm.py).
    if settings.is_llm_available:
        try:
            import json

            prompt = PROPOSE_ACTION_USER.format(
                user_query=user_query,
                relevant_data=json.dumps(relevant_data, default=str),
            )
            schema = ActionProposal.model_json_schema()
            # Server-side fields: the model must never emit risk, its own
            # confirmation gate, or the validator-only current_status metadata.
            for server_side in ("current_status", "risk_level", "requires_confirmation"):
                schema.get("properties", {}).pop(server_side, None)
            # risk_level has no default, so it is in "required" — drop it there
            # too or the API rejects the tool schema.
            schema["required"] = [r for r in schema.get("required", []) if r != "risk_level"]
            data, usage = await structured_call(
                system=PROPOSE_ACTION_SYSTEM,
                user=prompt,
                tool_name="emit_action_proposal",
                tool_description="Return a safe, auditable ActionProposal for the user's request.",
                input_schema=schema,
            )
            logger.debug("propose_action usage=%s", usage)
            # The model's risk claims are advisory: recompute server-side and
            # let the claim raise risk/confirmation, never lower them (SEC-1).
            claimed_risk = data.pop("risk_level", None)  # defensive: schema omits it
            claimed_confirm = bool(data.pop("requires_confirmation", False))
            target_count = len(data.get("target_ids", []))
            computed = _assess_risk(target_count, data.get("changes", {}))
            if claimed_risk in {r.value for r in RiskLevel}:
                computed = max(computed, RiskLevel(claimed_risk), key=_RISK_ORDER.__getitem__)
            data["risk_level"] = computed
            confirm_floor = computed != RiskLevel.LOW or target_count > _AUTO_CONFIRM_TARGET_MAX
            data["requires_confirmation"] = confirm_floor or claimed_confirm
            # Mirror the rule path: the transition validator needs the order's
            # current status, which the model must never supply itself.
            data.pop("current_status", None)
            if (
                data.get("action_type") == ActionType.UPDATE_ORDER_STATUS.value
                and data.get("changes", {}).get("status")
                and relevant_data
            ):
                wanted_ids = set(map(str, data.get("target_ids", [])))
                row = next(
                    (r for r in relevant_data if str(r.get("order_id", "")) in wanted_ids),
                    relevant_data[0],
                )
                data["current_status"] = row.get("status")
            proposal = ActionProposal.model_validate(data)
            errors = await validate_action_proposal(proposal)
            if errors:
                raise ValueError(f"Action validation failed: {'; '.join(errors)}")
            return proposal
        except LLMUnavailable:
            pass  # fall through to the rule-based path
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

    # Status updates need the order's current status to validate the transition.
    # Capture it as validator-only metadata (ActionProposal.current_status) from
    # the target row — never into `changes`, so it can't leak onto the wire, into
    # the impact summary, or into the human-facing proposal summary.
    current_status: str | None = None
    if action_type == ActionType.UPDATE_ORDER_STATUS and changes.get("status") and relevant_data:
        current_status = relevant_data[0].get("status")

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
        requires_confirmation=risk != RiskLevel.LOW or target_count > _AUTO_CONFIRM_TARGET_MAX,
        current_status=current_status,
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
    """Decide whether a proposal may proceed *without* an interactive prompt.

    Fail-safe by default: auto-approve only proposals that don't require
    confirmation (low-risk, small-batch — see ``propose_action``). Anything
    that requires confirmation returns ``False`` so the caller must obtain
    explicit human approval (the CLI does this via ``prompt_confirmation``).
    The library never defaults to "yes" on a risky mutation.
    """
    summary = format_proposal_summary(proposal)
    logger.info("Action confirmation requested:\n%s", summary)
    return not proposal.requires_confirmation


# ===================================================================
# Story 7.3 — Action Execution Skill
# ===================================================================


async def execute_action(
    client: OpsClient,
    proposal: ActionProposal,
    *,
    confirmed: bool = False,
) -> ActionResult:
    """Execute a confirmed ActionProposal against backend services.

    Routes each target to the correct ``OpsClient`` update method based on
    ``proposal.action_type``, tracks per-target success/failure, and returns
    an ``ActionResult``.

    Fail-safe gate: if ``proposal.requires_confirmation`` is set, this refuses
    to mutate anything unless ``confirmed=True`` is passed explicitly (obtained
    from ``confirm_action`` or the CLI's ``prompt_confirmation``). Otherwise it
    raises ``ActionNotConfirmedError`` before touching any backend.
    """
    if proposal.requires_confirmation and not confirmed:
        raise ActionNotConfirmedError(
            f"Refusing to execute {proposal.action_type.value}: proposal requires "
            f"confirmation but was not confirmed."
        )

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
                f"Cannot route bulk update for target '{target_id}': unknown ID prefix."
            )
    else:
        raise ValueError(f"Unsupported action type: {action_type}")
