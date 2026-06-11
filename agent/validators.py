"""Business rule validation with field type registry.

Validates QueryPlan and ActionProposal objects against known field
definitions, valid operators, status transition rules, and safety caps.
"""

from __future__ import annotations

from config.settings import get_settings
from models.action import ActionProposal, ActionType
from models.query import QueryPlan

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


async def validate_query_plan(plan: QueryPlan) -> list[str]:
    """Validate a QueryPlan against the field registry and operator rules.

    Returns a list of error messages. An empty list means the plan is valid.
    """
    errors: list[str] = []

    # Check that target_systems is non-empty (unless clarification)
    if not plan.target_systems and plan.intent.value != "clarification_needed":
        errors.append("QueryPlan must specify at least one target system.")

    # Validate each filter
    for f in plan.filters:
        matched = False
        for system in plan.target_systems:
            # A system can host more than one entity (oms → orders AND
            # exceptions), so match the field against any entity registered
            # under it rather than a single hard-coded entity.
            field_type = next(
                (
                    ftype
                    for (sys, _entity, field), ftype in FIELD_REGISTRY.items()
                    if sys == system.value and field == f.field
                ),
                None,
            )
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
                    allowed = next(
                        (
                            ops
                            for (sys_, _entity, fld), ops in DISPATCHABLE_OPERATORS.items()
                            if sys_ == system.value and fld == f.field
                        ),
                        None,
                    )
                    if allowed is None:
                        executable = sorted(
                            {fld for (s, _e, fld) in DISPATCHABLE_OPERATORS if s == system.value}
                        )
                        errors.append(
                            f"Filter field '{f.field}' is recognized but cannot be executed "
                            f"by the query dispatcher yet. Executable {system.value} fields: "
                            f"{executable}"
                        )
                    elif f.operator not in allowed:
                        errors.append(
                            f"Operator '{f.operator}' on '{f.field}' is not executable; "
                            f"only {sorted(allowed)} is supported for this field."
                        )
                break

        if not matched and plan.target_systems:
            errors.append(
                f"Unknown field '{f.field}' for systems {[s.value for s in plan.target_systems]}."
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
