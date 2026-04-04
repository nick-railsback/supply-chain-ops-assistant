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

ORDER_STATUS_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["confirmed", "cancelled"],
    "confirmed": ["processing", "cancelled"],
    "processing": ["shipped", "cancelled"],
    "shipped": ["in_transit"],
    "in_transit": ["delivered", "exception"],
    "delivered": ["returned"],
    "exception": ["processing", "cancelled"],
    "cancelled": [],
    "returned": [],
}

# ---------------------------------------------------------------------------
# Map target system to entity name used in the field registry
# ---------------------------------------------------------------------------

_SYSTEM_ENTITY_MAP: dict[str, str] = {
    "oms": "order",
    "wms": "inventory",
    "tms": "shipment",
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
            entity = _SYSTEM_ENTITY_MAP.get(system.value, plan.primary_entity)
            key = (system.value, entity, f.field)
            if key in FIELD_REGISTRY:
                matched = True
                field_type = FIELD_REGISTRY[key]
                valid_ops = VALID_OPERATORS.get(field_type, [])
                if f.operator not in valid_ops:
                    errors.append(
                        f"Operator '{f.operator}' is not valid for field "
                        f"'{f.field}' (type={field_type}). "
                        f"Valid operators: {valid_ops}"
                    )
                break

        if not matched and plan.target_systems:
            errors.append(
                f"Unknown field '{f.field}' for systems "
                f"{[s.value for s in plan.target_systems]}."
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

    # Bulk update cap
    if (
        proposal.action_type == ActionType.BULK_UPDATE
        and len(proposal.target_ids) > settings.bulk_update_cap
    ):
        errors.append(
            f"Bulk update affects {len(proposal.target_ids)} entities, "
            f"exceeding the cap of {settings.bulk_update_cap}."
        )

    # Status transition validation for order status updates
    if proposal.action_type == ActionType.UPDATE_ORDER_STATUS:
        new_status = proposal.changes.get("status")
        current_status = proposal.changes.get("current_status")

        if new_status and current_status:
            allowed = ORDER_STATUS_TRANSITIONS.get(current_status, [])
            if new_status not in allowed:
                errors.append(
                    f"Invalid status transition: '{current_status}' -> '{new_status}'. "
                    f"Allowed transitions: {allowed}"
                )
        elif new_status and not current_status:
            errors.append(
                "Status update requires 'current_status' in changes to validate transition."
            )

    return errors
