"""WMS domain models: inventory, fulfillment centers, stock movements."""

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from models.shared import ApiModel, StrictPatch

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MovementType(StrEnum):
    """Type of stock movement."""

    INBOUND_RECEIPT = "inbound_receipt"
    OUTBOUND_PICK = "outbound_pick"
    ADJUSTMENT_POSITIVE = "adjustment_positive"
    ADJUSTMENT_NEGATIVE = "adjustment_negative"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class FulfillmentCenter(ApiModel):
    """A physical fulfillment center / warehouse."""

    center_id: str
    name: str
    region: str
    capacity_units: int
    current_utilization: float = Field(ge=0.0, le=1.0)
    active: bool


class InventoryItem(ApiModel):
    """Inventory record for a single SKU at a fulfillment center."""

    inventory_id: str
    sku: str
    product_name: str
    fulfillment_center_id: str
    quantity_on_hand: int
    quantity_allocated: int
    quantity_available: int
    reorder_point: int
    last_counted_at: datetime
    category: str
    # When this row was last written to, whichever field moved; None on a row
    # that has never been patched. last_counted_at dates a physical count, so
    # it cannot serve as the record that a mutation happened.
    updated_at: datetime | None = None


class StockMovement(ApiModel):
    """A recorded stock movement event."""

    movement_id: str
    sku: str
    fulfillment_center_id: str
    movement_type: MovementType
    quantity: int
    reference_id: str | None = None
    timestamp: datetime


class UtilizationStats(ApiModel):
    """Utilization statistics for a fulfillment center."""

    center_id: str
    center_name: str
    capacity_units: int
    current_utilization: float
    units_used: int
    units_available: int


# ---------------------------------------------------------------------------
# Patch request models (the WMS PATCH contract)
# ---------------------------------------------------------------------------


class InventoryPatch(StrictPatch):
    # quantity_allocated follows from orders and quantity_available is derived
    # from the other two, so neither is the caller's to set: both are rejected
    # by being absent here.
    quantity_on_hand: int | None = Field(default=None, ge=0)
    reorder_point: int | None = Field(default=None, ge=0)
