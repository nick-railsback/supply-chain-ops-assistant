"""Action proposal reasoner, confirmation gate, and execution skill.

Provides the full action pipeline:
  1. ``propose_action`` — analyse a user request and build an ActionProposal
  2. ``confirm_action`` — present the proposal for human review
  3. ``execute_action`` — carry out a confirmed proposal via OpsClient
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from agent.llm import LLMUnavailable, structured_call
from agent.validators import (
    ACTIONS_WITH_A_DISPATCHER_SUPPLIED_CHANGE,
    mutated_entities,
    validate_action_proposal,
)
from config.prompts import PROPOSE_ACTION_SYSTEM, PROPOSE_ACTION_USER
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
    ActionType.ADJUST_INVENTORY: [
        "adjust inventory",
        "inventory count",
        "adjust stock",
        "recount",
        "set on hand",
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

# Changes touching money force HIGH risk regardless of target count.
_FINANCIAL_FIELDS = frozenset({"order_value", "shipping_cost"})

# Entities no single-target write to is routine, whatever action type carries
# it. A count restated on the shelf is not reversible by re-running anything.
_MEDIUM_FLOOR_ENTITIES = frozenset({"inventory"})

_MEDIUM_TARGET_MAX = 10  # <= this -> MEDIUM; above -> HIGH
_AUTO_CONFIRM_TARGET_MAX = 5  # LOW risk above this still requires confirmation
_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}

# The risk rules the model reads are rendered from the constants above, so the
# prompt cannot drift from what _assess_risk enforces. Composed once at import
# (byte-stable, prompt-cache friendly).
PROPOSE_ACTION_SYSTEM_PROMPT = PROPOSE_ACTION_SYSTEM.format(
    medium_target_max=_MEDIUM_TARGET_MAX,
    auto_confirm_target_max=_AUTO_CONFIRM_TARGET_MAX,
    irreversible_statuses=", ".join(sorted(_IRREVERSIBLE_STATUSES)),
    financial_fields=", ".join(sorted(_FINANCIAL_FIELDS)),
)


# ===================================================================
# Risk assessment
# ===================================================================


def _assess_risk(
    target_ids: list[str],
    changes: dict[str, Any],
    action_type: ActionType | None = None,
) -> RiskLevel:
    """Determine risk level from the targets and the change characteristics.

    Rules:
      - 1 target → LOW
      - 2–10 targets → MEDIUM
      - >10 targets → HIGH
      - Escalations, and anything writing to an inventory record → at least
        MEDIUM
      - Irreversible status transitions → HIGH (override)
      - Financial-field changes → HIGH (override)

    The inventory floor keys on the entity the write lands on, not on the
    action's label: restating a physical count is never routine, so reaching
    an inventory record through bulk_update cannot buy a lower gate than
    adjust_inventory would have.
    """
    new_status = changes.get("status", "")
    if isinstance(new_status, str) and new_status in _IRREVERSIBLE_STATUSES:
        return RiskLevel.HIGH
    if _FINANCIAL_FIELDS & changes.keys():
        return RiskLevel.HIGH

    target_count = len(target_ids)
    if target_count > _MEDIUM_TARGET_MAX:
        return RiskLevel.HIGH
    if (
        target_count > 1
        or action_type == ActionType.ESCALATE_ORDER
        or _MEDIUM_FLOOR_ENTITIES & mutated_entities(action_type, target_ids)
    ):
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _apply_risk_floor(
    action_type: ActionType | None,
    target_ids: list[str],
    changes: dict[str, Any],
    claimed_risk: RiskLevel | str | None = None,
    claimed_confirm: bool = False,
) -> tuple[RiskLevel, bool]:
    """Merge the server-computed risk floor with claimed values, raise-only.

    The single place the floor formula lives: ``propose_action`` applies it
    when a proposal is built, and ``execute_action`` re-applies it at the
    mutation boundary — so a proposal constructed or mutated anywhere else
    cannot carry a lowered gate past the floor.
    """
    target_count = len(target_ids)
    risk = _assess_risk(target_ids, changes, action_type)
    if isinstance(claimed_risk, str) and claimed_risk in {r.value for r in RiskLevel}:
        claimed_risk = RiskLevel(claimed_risk)
    if isinstance(claimed_risk, RiskLevel):
        risk = max(risk, claimed_risk, key=_RISK_ORDER.__getitem__)
    confirm = risk != RiskLevel.LOW or target_count > _AUTO_CONFIRM_TARGET_MAX
    return risk, confirm or claimed_confirm


# Explicit entity ids in a query (e.g. "escalate order ORD-2025-0001").
_ENTITY_ID_PATTERN = re.compile(r"\b(?:ORD|EXC|SHP|INV)-[A-Za-z0-9-]+\b")

# The id field each action's entity carries in context rows.
_ACTION_ID_FIELDS: dict[ActionType, tuple[str, ...]] = {
    ActionType.UPDATE_ORDER_STATUS: ("order_id",),
    ActionType.ESCALATE_ORDER: ("order_id",),
    ActionType.UPDATE_EXCEPTION: ("exception_id",),
    ActionType.ASSIGN_EXCEPTION: ("exception_id",),
    ActionType.FLAG_SHIPMENTS: ("shipment_id",),
    ActionType.ADJUST_INVENTORY: ("inventory_id",),
    ActionType.BULK_UPDATE: ("id", "order_id", "exception_id", "shipment_id", "inventory_id"),
}


def _fallback_target_ids(
    user_query: str,
    relevant_data: list[dict[str, Any]],
    action_type: ActionType,
) -> list[str]:
    """Pick the rule path's targets without fanning out across the context.

    Ids named explicitly in the query win, intersected with the context so a
    typo can't target an unfetched row. Otherwise only rows carrying the id
    field of the action's entity become targets — a context of mixed entities
    never all becomes targets of a single action.
    """
    id_fields = _ACTION_ID_FIELDS[action_type]
    context_ids: list[str] = []
    for row in relevant_data:
        for id_field in id_fields:
            if id_field in row:
                context_ids.append(str(row[id_field]))
                break

    explicit = _ENTITY_ID_PATTERN.findall(user_query)
    if explicit:
        context_set = set(context_ids)
        return [eid for eid in explicit if eid in context_set]
    return context_ids


def _status_by_target(relevant_data: list[dict[str, Any]]) -> dict[str, str]:
    """Map each context row's entity id to its current status.

    The single contract both proposal paths use to ground transition
    validation in the queried context. Join-correlated rows prefix non-key
    fields with the system (``oms_status``), so both spellings are read; rows
    without an id or status are skipped — the validator then rejects any
    target it can't find here rather than borrowing another row's status.
    """
    statuses: dict[str, str] = {}
    for row in relevant_data:
        entity_id = row.get("order_id") or row.get("id")
        status = row.get("status") or row.get("oms_status")
        if entity_id and status:
            statuses[str(entity_id)] = str(status)
    return statuses


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
        import json

        prompt = PROPOSE_ACTION_USER.format(
            user_query=user_query,
            relevant_data=json.dumps(relevant_data, default=str),
        )
        schema = ActionProposal.model_json_schema()
        # The model grades its own risk_level / requires_confirmation —
        # merged below with the server floor, raise-only. The validator-only
        # current_statuses ground truth must never come from the model.
        schema.get("properties", {}).pop("current_statuses", None)
        # Only the call itself may degrade to the rule path: a proposal the
        # validator rejects must surface to the operator as an error, never
        # silently become a different proposal.
        data: dict[str, Any] | None = None
        try:
            data, usage = await structured_call(
                system=PROPOSE_ACTION_SYSTEM_PROMPT,
                user=prompt,
                tool_name="emit_action_proposal",
                tool_description="Return a safe, auditable ActionProposal for the user's request.",
                input_schema=schema,
            )
            logger.debug("propose_action usage=%s", usage)
        except LLMUnavailable:
            pass  # fall through to the rule-based path
        except Exception as exc:
            logger.warning("LLM action proposal failed, falling back to rule-based: %s", exc)

        if data is not None:
            # The model's risk claims are advisory: recompute server-side and
            # let the claim raise risk/confirmation, never lower them (SEC-1).
            claimed_risk = data.pop("risk_level", None)
            claimed_confirm = bool(data.pop("requires_confirmation", False))
            try:
                proposed_type = ActionType(data.get("action_type", ""))
            except ValueError:
                proposed_type = None  # model_validate rejects it below
            data["risk_level"], data["requires_confirmation"] = _apply_risk_floor(
                proposed_type,
                data.get("target_ids", []),
                data.get("changes", {}),
                claimed_risk,
                claimed_confirm,
            )
            # Mirror the rule path: the transition validator needs each target's
            # current status, which the model must never supply itself.
            data.pop("current_statuses", None)
            if data.get("action_type") == ActionType.UPDATE_ORDER_STATUS.value and data.get(
                "changes", {}
            ).get("status"):
                statuses = _status_by_target(relevant_data)
                data["current_statuses"] = {
                    tid: statuses[tid]
                    for tid in map(str, data.get("target_ids", []))
                    if tid in statuses
                }
            proposal = ActionProposal.model_validate(data)
            errors = await validate_action_proposal(proposal)
            if errors:
                raise ValueError(f"Action validation failed: {'; '.join(errors)}")
            return proposal

    # Rule-based fallback
    action_type = _detect_action_type(user_query)
    target_ids = _fallback_target_ids(user_query, relevant_data, action_type)

    # Extract changes from the first data row or build from query context
    changes: dict[str, Any] = {}
    if relevant_data:
        changes = relevant_data[0].get("changes", {})

    # Status updates need each target's current status to validate transitions.
    # Capture them as validator-only metadata (ActionProposal.current_statuses)
    # from the context rows — never into `changes`, so they can't leak onto the
    # wire, into the impact summary, or into the human-facing proposal summary.
    current_statuses: dict[str, str] | None = None
    if action_type == ActionType.UPDATE_ORDER_STATUS and changes.get("status"):
        statuses = _status_by_target(relevant_data)
        current_statuses = {tid: statuses[tid] for tid in target_ids if tid in statuses}

    target_count = len(target_ids)
    risk, requires_confirmation = _apply_risk_floor(action_type, target_ids, changes)

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
        requires_confirmation=requires_confirmation,
        current_statuses=current_statuses,
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
    elif "inventory" in action_name:
        entity_noun = "inventory record" if len(proposal.target_ids) == 1 else "inventory records"
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

    Fail-safe gate: the confirmation floor is recomputed here, at the mutation
    boundary, from the proposal's own targets and changes — merged raise-only
    with the carried ``requires_confirmation`` — so a proposal constructed or
    mutated outside ``propose_action`` cannot lower its own gate. If the
    resulting floor requires confirmation, this refuses to mutate anything
    unless ``confirmed=True`` is passed explicitly (obtained from
    ``confirm_action`` or the CLI's ``prompt_confirmation``) and raises
    ``ActionNotConfirmedError`` before touching any backend.
    """
    _, requires_confirmation = _apply_risk_floor(
        proposal.action_type,
        proposal.target_ids,
        proposal.changes,
        proposal.risk_level,
        proposal.requires_confirmation,
    )
    if requires_confirmation and not confirmed:
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
    # Last stop before the wire: a changeless PATCH is accepted by the services
    # and would land in ActionResult.successful, telling the operator a mutation
    # they approved took effect when nothing moved. Only the two actions the
    # dispatcher supplies a change for below may arrive empty.
    if not changes and action_type not in ACTIONS_WITH_A_DISPATCHER_SUPPLIED_CHANGE:
        raise ValueError(
            f"Refusing to {action_type.value} '{target_id}': no change was named, so the "
            f"request would modify nothing and still be reported as applied."
        )

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

    elif action_type == ActionType.ADJUST_INVENTORY:
        await client.update_inventory(target_id, changes)

    elif action_type == ActionType.BULK_UPDATE:
        # Bulk update: try to infer the entity type from the target ID prefix
        if target_id.startswith("ORD"):
            await client.update_order(target_id, changes)
        elif target_id.startswith("EXC"):
            await client.update_exception(target_id, changes)
        elif target_id.startswith("SHP"):
            await client.update_shipment(target_id, changes)
        elif target_id.startswith("INV"):
            await client.update_inventory(target_id, changes)
        else:
            raise ValueError(
                f"Cannot route bulk update for target '{target_id}': unknown ID prefix."
            )
    else:
        raise ValueError(f"Unsupported action type: {action_type}")
