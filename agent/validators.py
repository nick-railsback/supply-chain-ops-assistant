"""Business rule validation with field type registry.

Validates QueryPlan and ActionProposal objects against known field
definitions, valid operators, status transition rules, and safety caps.
"""

from __future__ import annotations

from config.settings import get_settings
from models.action import ActionProposal, ActionType
from models.oms import ExceptionPatch, OrderPatch
from models.query import QueryPlan
from models.tms import ShipmentPatch

# ---------------------------------------------------------------------------
# Field registry: (system, entity, field) -> field_type
# ---------------------------------------------------------------------------

FIELD_REGISTRY: dict[tuple[str, str, str], str] = {
    # OMS — orders
    ("oms", "order", "status"): "enum",
    ("oms", "order", "channel"): "enum",
    ("oms", "order", "customer_tier"): "enum",
    ("oms", "order", "order_date"): "date",
    ("oms", "order", "date_range_start"): "date",
    ("oms", "order", "date_range_end"): "date",
    ("oms", "order", "order_value"): "numeric",
    ("oms", "order", "priority"): "enum",
    ("oms", "order", "at_risk"): "boolean",
    # OMS — exceptions
    ("oms", "exception", "exception_type"): "enum",
    ("oms", "exception", "severity"): "enum",
    ("oms", "exception", "status"): "enum",
    ("oms", "exception", "date_from"): "date",
    ("oms", "exception", "date_to"): "date",
    # WMS — inventory
    ("wms", "inventory", "sku"): "string",
    ("wms", "inventory", "category"): "enum",
    ("wms", "inventory", "fulfillment_center"): "string",
    ("wms", "inventory", "quantity_available"): "numeric",
    ("wms", "inventory", "low_stock_flag"): "boolean",
    ("wms", "inventory", "reorder_point"): "numeric",
    ("wms", "inventory", "below_reorder_point"): "boolean",
    # TMS — shipments
    ("tms", "shipment", "carrier"): "enum",
    ("tms", "shipment", "shipment_status"): "enum",
    ("tms", "shipment", "sla_status"): "enum",
    ("tms", "shipment", "ship_date"): "date",
    ("tms", "shipment", "delivery_date"): "date",
    ("tms", "shipment", "date_range_start"): "date",
    ("tms", "shipment", "date_range_end"): "date",
    ("tms", "shipment", "tracking_number"): "string",
}

# ---------------------------------------------------------------------------
# Dispatchable filters: what agent.copilot._dispatch_single_system actually
# executes, and the only operator semantics it honors. _extract_filters
# ignores DataFilter.operator entirely, so any pair not listed here would be
# silently mis-executed. Update in lockstep with the dispatcher.
# ---------------------------------------------------------------------------
DISPATCHABLE_OPERATORS: dict[tuple[str, str, str], frozenset[str]] = {
    ("oms", "order", "at_risk"): frozenset({"eq"}),
    ("oms", "order", "status"): frozenset({"eq"}),
    ("oms", "order", "channel"): frozenset({"eq"}),
    ("oms", "order", "customer_tier"): frozenset({"eq"}),
    ("oms", "order", "date_range_start"): frozenset({"gte"}),
    ("oms", "order", "date_range_end"): frozenset({"lte"}),
    ("oms", "order", "order_value"): frozenset({"gte"}),  # dispatcher maps to min_value
    ("oms", "exception", "exception_type"): frozenset({"eq"}),
    ("oms", "exception", "severity"): frozenset({"eq"}),
    ("oms", "exception", "status"): frozenset({"eq"}),
    ("oms", "exception", "date_from"): frozenset({"gte"}),
    ("oms", "exception", "date_to"): frozenset({"lte"}),
    ("wms", "inventory", "below_reorder_point"): frozenset({"eq"}),
    ("wms", "inventory", "sku"): frozenset({"eq"}),
    ("wms", "inventory", "fulfillment_center"): frozenset({"eq"}),
    ("wms", "inventory", "category"): frozenset({"eq"}),
    ("tms", "shipment", "sla_status"): frozenset({"eq"}),
    ("tms", "shipment", "carrier"): frozenset({"eq"}),
    ("tms", "shipment", "shipment_status"): frozenset({"eq"}),
    ("tms", "shipment", "date_range_start"): frozenset({"gte"}),
    ("tms", "shipment", "date_range_end"): frozenset({"lte"}),
}

# Boolean shortcut filters whose backends can only select the positive case
# (there is no "orders NOT at risk" endpoint). A value other than True would
# dispatch as "no filter at all", so it is rejected at validation.
_TRUE_ONLY_BOOLEAN_FIELDS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("oms", "order", "at_risk"),
        ("wms", "inventory", "below_reorder_point"),
    }
)

# ---------------------------------------------------------------------------
# Valid operators per field type
# ---------------------------------------------------------------------------

VALID_OPERATORS: dict[str, list[str]] = {
    "string": ["eq", "neq", "contains", "starts_with"],
    "enum": ["eq", "neq", "in", "not_in"],
    "numeric": ["eq", "neq", "gt", "gte", "lt", "lte", "between"],
    "date": ["eq", "gt", "gte", "lt", "lte", "between"],
    "boolean": ["eq"],
}

# ---------------------------------------------------------------------------
# Patchable change fields, derived from the PATCH contracts the services
# enforce (extra="forbid"). Adding a field to a patch model permits it here
# automatically; the validator can't drift from what the backends accept.
# ---------------------------------------------------------------------------

_PATCHABLE_FIELDS: dict[str, frozenset[str]] = {
    "order": frozenset(OrderPatch.model_fields),
    "exception": frozenset(ExceptionPatch.model_fields),
    "shipment": frozenset(ShipmentPatch.model_fields),
}

_ACTION_ENTITY: dict[ActionType, str] = {
    ActionType.UPDATE_ORDER_STATUS: "order",
    ActionType.ESCALATE_ORDER: "order",
    ActionType.UPDATE_EXCEPTION: "exception",
    ActionType.ASSIGN_EXCEPTION: "exception",
    ActionType.FLAG_SHIPMENTS: "shipment",
}

# BULK_UPDATE routes per target by id prefix (same map _dispatch_action uses).
_ID_PREFIX_ENTITY: dict[str, str] = {"ORD": "order", "EXC": "exception", "SHP": "shipment"}

# ---------------------------------------------------------------------------
# Order status transition map
# ---------------------------------------------------------------------------

# Keys and values are real OrderStatus members only (see models/oms.py).
# delivered and cancelled are terminal.
ORDER_STATUS_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["processing", "cancelled"],
    "processing": ["shipped", "cancelled", "exception"],
    "shipped": ["delivered", "exception"],
    "delivered": [],
    "exception": ["processing", "cancelled"],
    "cancelled": [],
}

# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _effective_entity(system: str, primary_entity: str) -> str:
    """The entity the dispatcher will actually query for *system*.

    Mirrors ``agent.copilot._dispatch_single_system`` exactly: TMS always
    queries shipments, WMS always inventory, and OMS branches to exceptions
    only when the plan's primary entity is 'exception' — any other spelling
    ('order', 'orders', 'unknown', ...) lists orders. Validation must judge a
    filter against this entity, not against any entity the system hosts, or
    cross-entity filters pass and are then silently dropped at dispatch.
    """
    if system == "oms":
        return "exception" if primary_entity == "exception" else "order"
    return {"wms": "inventory", "tms": "shipment"}.get(system, primary_entity)


async def validate_query_plan(plan: QueryPlan) -> list[str]:
    """Validate a QueryPlan against the field registry and operator rules.

    Returns a list of error messages. An empty list means the plan is valid.
    """
    errors: list[str] = []

    # Check that target_systems is non-empty (unless clarification)
    if not plan.target_systems and plan.intent.value != "clarification_needed":
        errors.append("QueryPlan must specify at least one target system.")

    # Validate each filter against the entity each system will actually query
    for f in plan.filters:
        matched = False
        for system in plan.target_systems:
            entity = _effective_entity(system.value, plan.primary_entity)
            field_type = FIELD_REGISTRY.get((system.value, entity, f.field))
            if field_type is not None:
                matched = True
                valid_ops = VALID_OPERATORS.get(field_type, [])
                if f.operator not in valid_ops:
                    errors.append(
                        f"Operator '{f.operator}' is not valid for field "
                        f"'{f.field}' (type={field_type}). "
                        f"Valid operators: {valid_ops}"
                    )
                else:
                    # Type-valid is not enough: the dispatcher executes only a
                    # subset of fields and ignores the operator, so reject pairs
                    # it would silently mis-run (e.g. order_value lt -> min_value).
                    allowed = DISPATCHABLE_OPERATORS.get((system.value, entity, f.field))
                    if allowed is None:
                        executable = sorted(
                            {
                                fld
                                for (s, e, fld) in DISPATCHABLE_OPERATORS
                                if s == system.value and e == entity
                            }
                        )
                        errors.append(
                            f"Filter field '{f.field}' is recognized but cannot be executed "
                            f"by the query dispatcher yet. Executable {system.value} {entity} "
                            f"fields: {executable}"
                        )
                    elif f.operator not in allowed:
                        errors.append(
                            f"Operator '{f.operator}' on '{f.field}' is not executable; "
                            f"only {sorted(allowed)} is supported for this field."
                        )
                    elif (
                        system.value,
                        entity,
                        f.field,
                    ) in _TRUE_ONLY_BOOLEAN_FIELDS and f.value is not True:
                        errors.append(
                            f"Filter '{f.field} {f.operator} {f.value}' cannot be executed: "
                            f"the backend only supports selecting '{f.field}' eq true. Drop "
                            f"the filter to list everything, or query the positive case."
                        )
                break

        if not matched and plan.target_systems:
            queried = sorted(
                {
                    f"{s.value} {_effective_entity(s.value, plan.primary_entity)}"
                    for s in plan.target_systems
                }
            )
            # If the field lives on a sibling entity, say so — the plan's
            # primary_entity is what's wrong, not the filter.
            other_entities = sorted(
                {
                    entity_
                    for (sys_, entity_, fld) in FIELD_REGISTRY
                    if any(sys_ == s.value for s in plan.target_systems) and fld == f.field
                }
            )
            hint = (
                f" The field exists on entity '{other_entities[0]}'; set primary_entity "
                f"to '{other_entities[0]}' if that was the intent."
                if other_entities
                else ""
            )
            errors.append(
                f"Filter field '{f.field}' is not available on the entities this plan "
                f"queries ({queried}); the dispatcher would silently ignore it.{hint}"
            )

    # Cross-system query must specify a join key
    if plan.requires_join and not plan.join_key:
        errors.append("Cross-system query requires a join_key.")

    return errors


async def validate_action_proposal(proposal: ActionProposal) -> list[str]:
    """Validate an ActionProposal against business rules and safety caps.

    Returns a list of error messages. An empty list means the proposal is valid.
    """
    errors: list[str] = []
    settings = get_settings()

    # Must have at least one target
    if not proposal.target_ids:
        errors.append("ActionProposal must specify at least one target_id.")

    # Target cap — applies to every action type, not just bulk_update
    if len(proposal.target_ids) > settings.bulk_update_cap:
        errors.append(
            f"Action affects {len(proposal.target_ids)} entities, "
            f"exceeding the cap of {settings.bulk_update_cap}."
        )

    # Changes must be expressible by the target entity's PATCH contract — the
    # services forbid unknown fields (422), so rejecting here keeps a doomed
    # proposal from passing human confirmation first.
    if proposal.changes:
        entity = _ACTION_ENTITY.get(proposal.action_type)
        entities = (
            {entity}
            if entity is not None
            else {
                _ID_PREFIX_ENTITY[tid[:3]]
                for tid in proposal.target_ids
                if tid[:3] in _ID_PREFIX_ENTITY
            }
        )
        for ent in sorted(entities):
            unknown = sorted(set(proposal.changes) - _PATCHABLE_FIELDS[ent])
            if unknown:
                errors.append(
                    f"Changes {unknown} cannot be applied to {ent} targets; the {ent} "
                    f"PATCH contract accepts only {sorted(_PATCHABLE_FIELDS[ent])}."
                )

    # Status transition validation for order status updates: every target is
    # checked against its own context status — a target absent from the queried
    # context is rejected rather than borrowing another row's status.
    if proposal.action_type == ActionType.UPDATE_ORDER_STATUS:
        new_status = proposal.changes.get("status")
        if new_status:
            statuses = proposal.current_statuses or {}
            for target_id in proposal.target_ids:
                current = statuses.get(target_id)
                if current is None:
                    errors.append(
                        f"Target '{target_id}' was not found in the queried context; "
                        f"cannot validate its current status for the transition."
                    )
                    continue
                allowed = ORDER_STATUS_TRANSITIONS.get(current, [])
                if new_status not in allowed:
                    errors.append(
                        f"Invalid status transition for '{target_id}': "
                        f"'{current}' -> '{new_status}'. Allowed transitions: {allowed}"
                    )

    return errors
