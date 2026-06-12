"""Data generator using Faker with cross-system consistency rules."""

import random
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from faker import Faker

from seed.constants import (
    CARRIER_MIX,
    CARRIERS,
    CUSTOMER_TIERS,
    EXCEPTION_TYPES,
    FULFILLMENT_CENTERS,
    ORDER_CHANNELS,
    PRODUCT_CATALOG,
    US_REGIONS,
)
from seed.context import SeedContext

# Shipped/delivered orders feed shipment generation, but order statuses are not
# ShipmentStatus members. Map the two that occur; anything else is in transit.
_ORDER_TO_SHIPMENT_STATUS = {"shipped": "in_transit", "delivered": "delivered"}


def _weighted_choice(options: dict[str, float]) -> str:
    """Pick a single key from a dict of {option: weight}."""
    keys = list(options.keys())
    weights = [options[k] for k in keys]
    return random.choices(keys, weights=weights, k=1)[0]


class DataGenerator:
    """Deterministic seed data generator for the supply-chain ops assistant.

    All outputs are reproducible given the same ``seed_value``.
    """

    def __init__(self, seed_value: int = 42) -> None:
        self.fake = Faker()
        Faker.seed(seed_value)
        random.seed(seed_value)
        self.ctx = SeedContext()
        self.now = datetime.now(UTC)
        # Flash sale was 2-3 days ago
        self.ctx.flash_sale_date = (self.now - timedelta(days=2)).date().isoformat()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_all(self) -> dict[str, list[dict[str, Any]]]:
        """Generate all data in topological order. Returns dict of entity lists."""
        centers = self._generate_centers()
        inventory = self._generate_inventory()
        orders = self._generate_orders(500)
        line_items = self._generate_line_items(orders)
        exceptions = self._generate_exceptions(orders)
        shipments = self._generate_shipments()
        tracking_events = self._generate_tracking_events(shipments)

        return {
            "fulfillment_centers": centers,
            "inventory": inventory,
            "orders": orders,
            "line_items": line_items,
            "exceptions": exceptions,
            "shipments": shipments,
            "tracking_events": tracking_events,
        }

    # ------------------------------------------------------------------
    # Fulfillment centers
    # ------------------------------------------------------------------

    def _generate_centers(self) -> list[dict[str, Any]]:
        """Return fulfillment centers with current utilization added.

        Two centers are marked "hot" (>85 % utilization).
        """
        centers: list[dict[str, Any]] = []
        hot_indices = random.sample(range(len(FULFILLMENT_CENTERS)), k=2)

        for idx, fc in enumerate(FULFILLMENT_CENTERS):
            center = dict(fc)  # shallow copy
            if idx in hot_indices:
                center["current_utilization"] = round(random.uniform(0.86, 0.97), 2)
            else:
                center["current_utilization"] = round(random.uniform(0.45, 0.80), 2)
            centers.append(center)
        return centers

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------

    def _generate_inventory(self) -> list[dict[str, Any]]:
        """Create inventory rows: each SKU stocked at 2-4 random centers.

        Backordered SKUs get near-zero available quantity.
        """
        # Pre-select ~8 % of SKUs as backordered
        num_backordered = max(1, len(PRODUCT_CATALOG) // 12)
        backordered_products = random.sample(PRODUCT_CATALOG, k=num_backordered)
        for prod in backordered_products:
            sku = str(prod["sku"])
            self.ctx.register_backorder(sku)

        center_ids = [str(fc["id"]) for fc in FULFILLMENT_CENTERS]
        inventory: list[dict[str, Any]] = []

        for prod in PRODUCT_CATALOG:
            sku = str(prod["sku"])
            num_centers = random.randint(2, 4)
            chosen_centers = random.sample(center_ids, k=num_centers)

            for cid in chosen_centers:
                if sku in self.ctx.backordered_skus:
                    on_hand = random.randint(0, 5)
                    quantity_available = random.randint(0, min(on_hand, 2))
                    quantity_reserved = on_hand - quantity_available
                else:
                    on_hand = random.randint(50, 500)
                    quantity_reserved = random.randint(0, on_hand // 4)
                    quantity_available = on_hand - quantity_reserved

                inventory.append(
                    {
                        "sku": sku,
                        "center_id": cid,
                        "on_hand": on_hand,
                        "quantity_available": quantity_available,
                        "quantity_reserved": quantity_reserved,
                        "reorder_point": random.randint(20, 60),
                        "last_replenishment": (self.now - timedelta(days=random.randint(1, 14)))
                        .date()
                        .isoformat(),
                    }
                )
        return inventory

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def _generate_orders(self, count: int = 500) -> list[dict[str, Any]]:
        """Generate *count* orders spanning the last 30 days.

        Weekday volume is ~30 % higher than weekends and the flash-sale
        date gets a 3x spike.
        """
        center_ids = [str(fc["id"]) for fc in FULFILLMENT_CENTERS]

        # Build a date-weight list for the last 30 days
        date_weights: list[tuple[date, float]] = []
        flash_date = date.fromisoformat(str(self.ctx.flash_sale_date))
        for offset in range(30):
            d = (self.now - timedelta(days=offset)).date()
            weight = 1.0
            # Weekday boost
            if d.weekday() < 5:
                weight *= 1.3
            # Flash sale spike
            if d == flash_date:
                weight *= 3.0
            date_weights.append((d, weight))

        dates = [dw[0] for dw in date_weights]
        weights = [dw[1] for dw in date_weights]

        # Status distribution weights
        status_options: dict[str, float] = {
            "pending": 0.15,
            "processing": 0.15,
            "shipped": 0.40,
            "delivered": 0.20,
            "cancelled": 0.05,
            "exception": 0.05,
        }

        orders: list[dict[str, Any]] = []
        for seq in range(1, count + 1):
            order_date = random.choices(dates, weights=weights, k=1)[0]
            order_ts = datetime(
                order_date.year,
                order_date.month,
                order_date.day,
                random.randint(0, 23),
                random.randint(0, 59),
                random.randint(0, 59),
                tzinfo=UTC,
            )

            order_id = f"ORD-{order_date.year}-{seq:06d}"
            status = _weighted_choice(status_options)
            channel = _weighted_choice(ORDER_CHANNELS)
            tier = _weighted_choice(CUSTOMER_TIERS)
            fc_id = random.choice(center_ids)

            # Customer data
            customer_name = self.fake.name()
            customer_email = self.fake.email()

            # Shipping region
            region_info = random.choice(US_REGIONS)
            states: list[str] = region_info["states"]  # type: ignore[assignment]
            ship_state = random.choice(states)
            ship_city = self.fake.city()
            ship_zip = self.fake.zipcode()

            # Promised delivery date. Still-active orders are promised in the near
            # future relative to now, so a meaningful subset lands inside the
            # /orders/at-risk window ([now, now+2d]); terminal/shipped orders carry
            # a historical promise relative to their creation.
            if status in ("pending", "processing", "exception"):
                promised_ts = self.now + timedelta(days=random.randint(1, 5))
            else:
                promised_ts = order_ts + timedelta(days=random.randint(2, 5))

            order: dict[str, Any] = {
                "order_id": order_id,
                "status": status,
                "channel": channel,
                "customer_tier": tier,
                "customer_name": customer_name,
                "customer_email": customer_email,
                "fulfillment_center_id": fc_id,
                "shipping_address": {
                    "city": ship_city,
                    "state": ship_state,
                    "zip": ship_zip,
                    "region": str(region_info["region"]),
                },
                "created_at": order_ts.isoformat(),
                "updated_at": (order_ts + timedelta(hours=random.randint(0, 48))).isoformat(),
                "promised_delivery_date": promised_ts.isoformat(),
            }

            orders.append(order)
            self.ctx.register_order(order_id, order)

        return orders

    # ------------------------------------------------------------------
    # Line items
    # ------------------------------------------------------------------

    def _generate_line_items(self, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Create 1-4 line items per order.

        Line-item status is consistent with the parent order status.
        Some items are marked backordered.
        """
        line_items: list[dict[str, Any]] = []
        line_seq = 0

        # Map order status -> valid line-item statuses
        status_map: dict[str, list[str]] = {
            "pending": ["pending"],
            "processing": ["allocated", "picking"],
            "shipped": ["shipped"],
            "delivered": ["delivered"],
            "cancelled": ["cancelled"],
            "exception": ["pending", "exception"],
        }

        for order in orders:
            num_items = random.randint(1, 4)
            chosen_products = random.sample(PRODUCT_CATALOG, k=min(num_items, len(PRODUCT_CATALOG)))
            order_id = str(order["order_id"])
            fc_id = str(order["fulfillment_center_id"])
            order_status = str(order["status"])

            for prod in chosen_products:
                line_seq += 1
                sku = str(prod["sku"])
                qty = random.randint(1, 3)
                min_price = float(str(prod["min_price"]))
                max_price = float(str(prod["max_price"]))
                unit_price = round(random.uniform(min_price, max_price), 2)

                # Determine line-item status
                valid_statuses = status_map.get(order_status, ["pending"])
                li_status = random.choice(valid_statuses)

                # ~5 % chance of backordered for pending/processing orders
                is_backordered = False
                if order_status in ("pending", "processing", "exception"):
                    if sku in self.ctx.backordered_skus or random.random() < 0.05:
                        is_backordered = True
                        li_status = "backordered"
                        self.ctx.register_backorder(sku)

                # Track allocation for non-cancelled, non-backordered items
                if li_status not in ("cancelled", "backordered"):
                    self.ctx.register_allocation(sku, fc_id, qty)

                line_items.append(
                    {
                        "line_item_id": f"LI-{line_seq:07d}",
                        "order_id": order_id,
                        "sku": sku,
                        "product_name": str(prod["name"]),
                        "quantity": qty,
                        "unit_price": unit_price,
                        "line_total": round(unit_price * qty, 2),
                        "status": li_status,
                        "is_backordered": is_backordered,
                    }
                )
        return line_items

    # ------------------------------------------------------------------
    # Exceptions
    # ------------------------------------------------------------------

    def _generate_exceptions(self, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Generate 40-60 open + 100+ resolved exceptions.

        SLA breach orders automatically get sla_at_risk exceptions.
        """
        exceptions: list[dict[str, Any]] = []
        exc_seq = 0

        # Ensure SLA-breach orders get exceptions
        for oid in self.ctx.get_sla_breach_orders():
            exc_seq += 1
            created = self.now - timedelta(hours=random.randint(6, 72))
            exceptions.append(
                {
                    "exception_id": f"EXC-{exc_seq:04d}",
                    "order_id": oid,
                    "type": "sla_at_risk",
                    "status": "open",
                    "severity": "high",
                    "description": "Shipment may miss committed delivery window.",
                    "created_at": created.isoformat(),
                    "resolved_at": None,
                }
            )
            self.ctx.exception_order_ids.add(oid)

        # Candidate orders for exceptions
        exception_orders = [o for o in orders if str(o["status"]) == "exception"]
        other_orders = [o for o in orders if str(o["status"]) not in ("cancelled", "delivered")]

        # Open exceptions: target 40-60
        open_target = random.randint(40, 60) - len(exceptions)
        # Always cover exception-status orders first
        open_pool = exception_orders + random.sample(
            other_orders, k=min(open_target, len(other_orders))
        )
        random.shuffle(open_pool)

        for order in open_pool[:open_target]:
            oid = str(order["order_id"])
            if oid in self.ctx.exception_order_ids:
                continue
            exc_seq += 1
            exc_type = _weighted_choice(EXCEPTION_TYPES)
            created = self.now - timedelta(hours=random.randint(1, 96))
            severity = random.choice(["low", "medium", "high"])

            exceptions.append(
                {
                    "exception_id": f"EXC-{exc_seq:04d}",
                    "order_id": oid,
                    "type": exc_type,
                    "status": "open",
                    "severity": severity,
                    "description": self._exception_description(exc_type),
                    "created_at": created.isoformat(),
                    "resolved_at": None,
                }
            )
            self.ctx.exception_order_ids.add(oid)

        # Resolved exceptions: 100+
        resolved_target = random.randint(100, 140)
        resolved_pool = random.sample(orders, k=min(resolved_target * 2, len(orders)))
        resolved_count = 0

        for order in resolved_pool:
            if resolved_count >= resolved_target:
                break
            oid = str(order["order_id"])
            exc_seq += 1
            exc_type = _weighted_choice(EXCEPTION_TYPES)
            created = self.now - timedelta(days=random.randint(2, 28))
            resolved = created + timedelta(hours=random.randint(1, 48))

            exceptions.append(
                {
                    "exception_id": f"EXC-{exc_seq:04d}",
                    "order_id": oid,
                    "type": exc_type,
                    "status": "resolved",
                    "severity": random.choice(["low", "medium", "high"]),
                    "description": self._exception_description(exc_type),
                    "created_at": created.isoformat(),
                    "resolved_at": resolved.isoformat(),
                }
            )
            resolved_count += 1

        return exceptions

    @staticmethod
    def _exception_description(exc_type: str) -> str:
        """Return a short human-readable description for an exception type."""
        descriptions: dict[str, str] = {
            "address_invalid": "Shipping address failed validation.",
            "payment_failed": "Payment authorization declined by processor.",
            "item_backordered": "One or more items not available in warehouse.",
            "sla_at_risk": "Shipment may miss committed delivery window.",
            "damaged_in_warehouse": "Item found damaged during pick/pack.",
            "wrong_item_picked": "Pick verification flagged incorrect item.",
            "customer_requested_cancel": "Customer requested order cancellation.",
            "carrier_rejection": "Carrier rejected package at handoff.",
        }
        return descriptions.get(exc_type, f"Exception of type {exc_type}.")

    # ------------------------------------------------------------------
    # Shipments
    # ------------------------------------------------------------------

    def _generate_shipments(self) -> list[dict[str, Any]]:
        """One shipment per shipped/delivered order.

        Carrier selected per CARRIER_MIX weights.  Most shipments are
        on_track; a subset are at_risk or breached.
        """
        shipped_ids = self.ctx.get_shipped_orders()
        carriers_by_name = {str(c["name"]): c for c in CARRIERS}
        shipments: list[dict[str, Any]] = []

        sla_status_options: dict[str, float] = {
            "on_track": 0.75,
            "at_risk": 0.15,
            "breached": 0.10,
        }

        for seq, order_id in enumerate(shipped_ids, start=1):
            carrier_name = _weighted_choice(CARRIER_MIX)
            carrier = carriers_by_name[carrier_name]
            service_levels = carrier["service_levels"]
            levels: list[str] = service_levels  # type: ignore[assignment]
            service = random.choice(levels)

            origin_center = self.ctx.get_center_for_order(order_id)
            order_data = self.ctx.orders[order_id]
            order_created = datetime.fromisoformat(str(order_data["created_at"]))

            ship_date = order_created + timedelta(hours=random.randint(4, 36))
            est_delivery = ship_date + timedelta(days=random.randint(2, 7))

            sla_status = _weighted_choice(sla_status_options)

            # Register breached shipments
            if sla_status == "breached":
                self.ctx.register_sla_breach(order_id)

            shipment_id = f"SHP-{ship_date.strftime('%Y%m%d')}-{seq:05d}"
            self.ctx.shipment_order_map[shipment_id] = order_id

            shipments.append(
                {
                    "shipment_id": shipment_id,
                    "order_id": order_id,
                    "carrier": carrier_name,
                    "service_level": str(service),
                    "origin_center_id": origin_center,
                    "destination_zip": str(order_data["shipping_address"]["zip"]),
                    "destination_state": str(order_data["shipping_address"]["state"]),
                    "tracking_number": uuid.uuid4().hex[:20].upper(),
                    "sla_status": sla_status,
                    "shipped_at": ship_date.isoformat(),
                    "estimated_delivery": est_delivery.date().isoformat(),
                    # Order statuses are not ShipmentStatus members; map them.
                    "status": _ORDER_TO_SHIPMENT_STATUS.get(
                        str(order_data["status"]), "in_transit"
                    ),
                }
            )

        return shipments

    # ------------------------------------------------------------------
    # Tracking events
    # ------------------------------------------------------------------

    def _generate_tracking_events(self, shipments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Generate 2-6 tracking events per shipment with realistic progression."""
        event_progressions: list[str] = [
            "label_created",
            "picked_up",
            "in_transit",
            "out_for_delivery",
            "delivered",
        ]

        events: list[dict[str, Any]] = []
        event_seq = 0

        for shipment in shipments:
            ship_ts = datetime.fromisoformat(str(shipment["shipped_at"]))
            shipment_id = str(shipment["shipment_id"])
            status = str(shipment["status"])

            # Determine how far along the progression to go
            if status == "delivered":
                max_step = len(event_progressions)
            else:
                max_step = random.randint(2, 4)

            num_events = min(random.randint(2, 6), max_step)
            # Select the first num_events from the progression
            selected = event_progressions[:num_events]

            current_ts = ship_ts
            for step in selected:
                event_seq += 1
                current_ts = current_ts + timedelta(
                    hours=random.randint(2, 18),
                    minutes=random.randint(0, 59),
                )
                location = self.fake.city() + ", " + self.fake.state_abbr()

                events.append(
                    {
                        "event_id": f"EVT-{event_seq:07d}",
                        "shipment_id": shipment_id,
                        "event_type": step,
                        "timestamp": current_ts.isoformat(),
                        "location": location,
                        "details": self._tracking_detail(step),
                    }
                )

        return events

    @staticmethod
    def _tracking_detail(event_type: str) -> str:
        """Return a human-readable detail string for a tracking event type."""
        details: dict[str, str] = {
            "label_created": "Shipping label created, awaiting carrier pickup.",
            "picked_up": "Package picked up by carrier.",
            "in_transit": "Package in transit to destination hub.",
            "out_for_delivery": "Package out for delivery.",
            "delivered": "Package delivered to recipient.",
        }
        return details.get(event_type, f"Tracking event: {event_type}.")
