"""TMS domain models: shipments, tracking events, carrier stats."""

from datetime import datetime
from enum import StrEnum

from models.shared import ApiModel

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ShipmentStatus(StrEnum):
    """Lifecycle status of a shipment."""

    LABEL_CREATED = "label_created"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
    RETURNED = "returned"


class SLAStatus(StrEnum):
    """SLA compliance status."""

    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    BREACHED = "breached"
    MET = "met"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Shipment(ApiModel):
    """Core shipment record."""

    shipment_id: str
    order_id: str
    carrier: str
    service_level: str
    status: ShipmentStatus
    tracking_number: str
    origin_center_id: str
    destination_zip: str
    destination_state: str
    weight_lbs: float
    shipping_cost: float
    label_created_at: datetime
    estimated_delivery: datetime
    actual_delivery: datetime | None = None
    sla_target: datetime
    sla_status: SLAStatus
    flagged: bool = False


class TrackingEvent(ApiModel):
    """Single tracking event for a shipment."""

    event_id: str
    shipment_id: str
    timestamp: datetime
    location: str
    status: str
    description: str


class ShipmentWithTracking(Shipment):
    """Shipment with full tracking history."""

    tracking_events: list[TrackingEvent]


class CarrierStats(ApiModel):
    """Aggregated performance statistics for a carrier."""

    carrier: str
    on_time_rate: float
    avg_transit_days: float
    avg_cost: float
    total_shipments: int


class SLASummary(ApiModel):
    """SLA compliance summary across shipments."""

    total_shipments: int
    on_track: int
    at_risk: int
    breached: int
    met: int
    compliance_rate: float
    by_carrier: dict[str, dict[str, int]]
