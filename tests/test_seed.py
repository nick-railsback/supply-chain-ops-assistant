"""Regression tests for the seed path feeding the at-risk orders feature.

/orders/at-risk filters promised_delivery_date IS NOT NULL and within [now, now+2d]
for non-shipped/delivered/cancelled orders. The seed previously hard-coded every
promised_delivery_date to None, so the feature returned zero rows regardless of
order state. These tests pin the seed path to populate it.
"""

from datetime import timedelta

from seed.generator import DataGenerator
from seed.seed_db import _map_orders

_ACTIVE_STATUSES = {"pending", "processing", "exception"}


def test_map_orders_passes_promised_delivery_date_through():
    """_map_orders must carry the generator's promised_delivery_date, not drop it."""
    orders = [
        {
            "order_id": "ORD-2026-000001",
            "customer_name": "Test Customer",
            "customer_email": "test@example.com",
            "customer_tier": "standard",
            "status": "pending",
            "channel": "web",
            "created_at": "2026-06-01T00:00:00+00:00",
            "updated_at": "2026-06-01T00:00:00+00:00",
            "promised_delivery_date": "2026-06-03T00:00:00+00:00",
            "fulfillment_center_id": "FC-EAST",
            "shipping_address": {},
        }
    ]
    rows = _map_orders(orders, line_items=[])
    assert rows[0]["promised_delivery_date"] == "2026-06-03T00:00:00+00:00"


def test_generated_orders_all_have_promised_delivery_date():
    """Every generated order carries a non-null promised_delivery_date."""
    gen = DataGenerator(seed_value=42)
    rows = _map_orders(gen._generate_orders(50), line_items=[])
    assert all(r["promised_delivery_date"] is not None for r in rows)


def test_seed_path_yields_at_risk_eligible_orders():
    """The seed path produces at least one order that satisfies the at-risk
    filter: active status with a promised date inside the [now, now+2d] window."""
    gen = DataGenerator(seed_value=42)
    rows = _map_orders(gen._generate_orders(100), line_items=[])

    now_str = gen.now.isoformat()
    cutoff_str = (gen.now + timedelta(days=2)).isoformat()
    at_risk = [
        r
        for r in rows
        if r["status"] in _ACTIVE_STATUSES
        and r["promised_delivery_date"] is not None
        and now_str <= r["promised_delivery_date"] <= cutoff_str
    ]
    assert at_risk, "seed path should yield at least one at-risk-eligible order"
