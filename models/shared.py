"""Shared enums, base classes, and common types."""

from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Base classes
# ---------------------------------------------------------------------------


class ApiModel(BaseModel):
    """Base model with ORM-mode support."""

    model_config = ConfigDict(from_attributes=True)


class StrictPatch(BaseModel):
    """Base for PATCH request bodies: unknown fields are rejected (422).

    Without this, pydantic's default ``extra="ignore"`` silently drops a
    misspelled or unsupported change while the mutation reports success.
    Every patch model must inherit it so the next one can't regress.
    """

    model_config = ConfigDict(extra="forbid")


class PaginatedResponse(BaseModel, Generic[T]):
    """Wrapper for paginated list responses."""

    items: list[T]
    total: int
    offset: int
    limit: int


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TargetSystem(StrEnum):
    """Backend system identifiers."""

    OMS = "oms"
    WMS = "wms"
    TMS = "tms"


class UserIntent(StrEnum):
    """Classified intent of a user query."""

    STATUS_CHECK = "status_check"
    CROSS_SYSTEM_QUERY = "cross_system_query"
    ANALYSIS = "analysis"
    ACTION_REQUEST = "action_request"
    REPORT = "report"
    CLARIFICATION_NEEDED = "clarification_needed"


class Severity(StrEnum):
    """Severity levels for exceptions / alerts."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLevel(StrEnum):
    """Risk assessment levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ---------------------------------------------------------------------------
# ID format regex patterns
# ---------------------------------------------------------------------------

ORDER_ID_PATTERN = r"^ORD-\d{4}-\d{6}$"
SHIPMENT_ID_PATTERN = r"^SHP-\d{8}-\d{5}$"
EXCEPTION_ID_PATTERN = r"^EXC-\d{4}$"
LINE_ITEM_ID_PATTERN = r"^LI-[a-f0-9]{8}$"
INVENTORY_ID_PATTERN = r"^INV-[a-f0-9]{8}$"
MOVEMENT_ID_PATTERN = r"^MOV-[a-f0-9]{8}$"
CENTER_ID_PATTERN = r"^FC-[A-Z]{3}-\d{2}$"
