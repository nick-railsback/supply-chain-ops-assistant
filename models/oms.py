"""OMS domain models: orders, line items, exceptions."""

from datetime import date, datetime
from enum import StrEnum

from models.shared import ApiModel, Severity

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CustomerTier(StrEnum):
    STANDARD = "standard"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"


class OrderStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    EXCEPTION = "exception"


class OrderPriority(StrEnum):
    LOW = "low"
    STANDARD = "standard"
    HIGH = "high"
    URGENT = "urgent"


class OrderChannel(StrEnum):
    DTC_WEB = "dtc_web"
    DTC_MOBILE = "dtc_mobile"
    WHOLESALE_B2B = "wholesale_b2b"
    MARKETPLACE_AMAZON = "marketplace_amazon"
    MARKETPLACE_SHOPIFY = "marketplace_shopify"


class LineItemStatus(StrEnum):
    PENDING = "pending"
    ALLOCATED = "allocated"
    PICKED = "picked"
    PACKED = "packed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    BACKORDERED = "backordered"


class ExceptionType(StrEnum):
    ADDRESS_INVALID = "address_invalid"
    PAYMENT_FAILED = "payment_failed"
    ITEM_BACKORDERED = "item_backordered"
    SLA_AT_RISK = "sla_at_risk"
    DAMAGED_IN_WAREHOUSE = "damaged_in_warehouse"
    WRONG_ITEM_PICKED = "wrong_item_picked"
    CUSTOMER_REQUESTED_CANCEL = "customer_requested_cancel"
    CARRIER_REJECTION = "carrier_rejection"


class ExceptionStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Order(ApiModel):
    order_id: str
    customer_id: str | None = None
    customer_name: str
    customer_email: str
    customer_tier: CustomerTier
    status: OrderStatus
    channel: OrderChannel
    priority: OrderPriority = OrderPriority.STANDARD
    created_at: datetime
    updated_at: datetime | None = None
    promised_delivery_date: datetime | None = None
    fulfillment_center_id: str
    total_value: float
    currency: str = "USD"
    line_item_count: int
    notes: str | None = None


class LineItem(ApiModel):
    line_item_id: str
    order_id: str
    sku: str
    product_name: str
    quantity: int
    unit_price: float
    status: LineItemStatus


class OrderWithLineItems(Order):
    line_items: list[LineItem]


class OrderException(ApiModel):
    exception_id: str
    order_id: str
    exception_type: ExceptionType
    severity: Severity
    status: ExceptionStatus
    created_at: datetime
    resolved_at: datetime | None = None
    description: str
    assigned_to: str | None = None


class ExceptionSummary(ApiModel):
    by_type: dict[str, int]
    by_severity: dict[str, int]
    total_open: int
    total_resolved: int


class DailyStats(ApiModel):
    date: date
    total_orders: int
    total_value: float
    exception_rate: float
    orders_by_status: dict[str, int]
