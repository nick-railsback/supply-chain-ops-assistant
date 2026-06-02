"""SeedContext class for cross-system ID consistency tracking."""

from dataclasses import dataclass, field


@dataclass
class SeedContext:
    """Tracks cross-system IDs during data generation to enforce consistency rules.

    Generation order: fulfillment_centers -> inventory -> orders -> line_items
        -> exceptions -> shipments -> tracking_events

    Consistency rules enforced:
    1. Every shipped order has a corresponding shipment in TMS
    2. Shipment origin_center_id matches order's fulfillment_center_id
    3. inventory.quantity_allocated ~ pending/processing order quantities
    4. Backordered items in OMS have near-zero available inventory in WMS
    5. SLA breaches in TMS have matching exception records in OMS
    6. Some centers running hot (>85% utilization)
    7. Temporal patterns: weekday peaks, flash sale spike 2-3 days ago
    """

    # Order tracking
    orders: dict[str, dict] = field(default_factory=dict)  # order_id -> order data
    shipped_order_ids: list[str] = field(default_factory=list)
    order_center_map: dict[str, str] = field(default_factory=dict)  # order_id -> center_id

    # SKU tracking
    backordered_skus: set[str] = field(default_factory=set)
    sku_allocated_qty: dict[str, dict[str, int]] = field(
        default_factory=dict
    )  # sku -> {center_id: qty}

    # Shipment tracking
    shipment_order_map: dict[str, str] = field(default_factory=dict)  # shipment_id -> order_id
    sla_breach_order_ids: list[str] = field(default_factory=list)

    # Exception tracking
    exception_order_ids: set[str] = field(default_factory=set)

    # Temporal tracking
    flash_sale_date: str | None = None  # ISO date string

    def register_order(self, order_id: str, order_data: dict) -> None:
        """Register an order and track its center assignment."""
        self.orders[order_id] = order_data
        self.order_center_map[order_id] = order_data["fulfillment_center_id"]
        if order_data["status"] in ("shipped", "delivered"):
            self.shipped_order_ids.append(order_id)

    def register_backorder(self, sku: str) -> None:
        """Mark a SKU as backordered."""
        self.backordered_skus.add(sku)

    def register_allocation(self, sku: str, center_id: str, quantity: int) -> None:
        """Track allocated quantity for a SKU at a center."""
        if sku not in self.sku_allocated_qty:
            self.sku_allocated_qty[sku] = {}
        self.sku_allocated_qty[sku][center_id] = (
            self.sku_allocated_qty[sku].get(center_id, 0) + quantity
        )

    def register_sla_breach(self, order_id: str) -> None:
        """Mark an order as having an SLA breach."""
        self.sla_breach_order_ids.append(order_id)

    def get_shipped_orders(self) -> list[str]:
        """Get all order IDs that need corresponding shipments."""
        return self.shipped_order_ids

    def get_backordered_skus(self) -> set[str]:
        """Get SKUs that should have near-zero available inventory."""
        return self.backordered_skus

    def get_center_for_order(self, order_id: str) -> str:
        """Get the fulfillment center assigned to an order."""
        return self.order_center_map[order_id]

    def get_allocation_for_sku(self, sku: str, center_id: str) -> int:
        """Get total allocated quantity for a SKU at a center."""
        return self.sku_allocated_qty.get(sku, {}).get(center_id, 0)

    def get_sla_breach_orders(self) -> list[str]:
        """Get orders that need SLA-at-risk exception records."""
        return self.sla_breach_order_ids
