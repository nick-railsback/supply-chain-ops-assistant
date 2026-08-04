"""Action proposal, action result, and action type models."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from models.shared import RiskLevel


class ActionType(StrEnum):
    """Supported mutation action types."""

    UPDATE_ORDER_STATUS = "update_order_status"
    UPDATE_EXCEPTION = "update_exception"
    ASSIGN_EXCEPTION = "assign_exception"
    ESCALATE_ORDER = "escalate_order"
    FLAG_SHIPMENTS = "flag_shipments"
    ADJUST_INVENTORY = "adjust_inventory"
    BULK_UPDATE = "bulk_update"


class ActionProposal(BaseModel):
    """Proposed action awaiting user confirmation."""

    action_type: ActionType
    target_ids: list[str]
    changes: dict[str, Any]
    reasoning: str
    impact_summary: str
    risk_level: RiskLevel
    requires_confirmation: bool = True
    # Validator-only metadata: each target's status before the change, keyed
    # by target id, used to validate every transition individually. Never
    # dispatched (kept out of ``changes``).
    current_statuses: dict[str, str] | None = None


class ActionResult(BaseModel):
    """Outcome of an executed action."""

    action_type: ActionType
    total_targets: int
    successful: list[str]
    failed: list[dict[str, str]]
    execution_time_ms: float
