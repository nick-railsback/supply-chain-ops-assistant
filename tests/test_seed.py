"""Regression tests for the seed path feeding the at-risk orders feature.

/orders/at-risk filters promised_delivery_date IS NOT NULL and within [now, now+2d]
for non-shipped/delivered/cancelled orders. The seed previously hard-coded every
promised_delivery_date to None, so the feature returned zero rows regardless of
order state. These tests pin the seed path to populate it.
"""

import sqlite3
from datetime import timedelta
from pathlib import Path

from seed.generator import DataGenerator
from seed.seed_db import _create_tables, _map_orders

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


def test_seed_tables_are_the_orm_tables():
    """The seeder fills the very tables the services declare — no parallel copy."""
    from seed.seed_db import inventory_table, orders_table, shipments_table
    from services.oms_api import Base as OMSBase
    from services.tms_api import Base as TMSBase
    from services.wms_api import Base as WMSBase

    assert orders_table is OMSBase.metadata.tables["orders"]
    assert shipments_table is TMSBase.metadata.tables["shipments"]
    assert inventory_table is WMSBase.metadata.tables["inventory"]


def test_mapped_shipments_have_destinations_and_valid_statuses():
    """Shipment rows carry real destinations and only ShipmentStatus values
    (the generator previously copied order statuses, e.g. 'shipped')."""
    from models.tms import ShipmentStatus
    from seed.seed_db import _map_shipments

    data = DataGenerator(seed_value=42).generate_all()
    rows = _map_shipments(data["shipments"])
    valid = {s.value for s in ShipmentStatus}
    assert all(r["destination_zip"] and r["destination_state"] for r in rows)
    assert all(r["status"] in valid for r in rows)


async def test_reset_recreates_drifted_schema(tmp_path):
    """The compose seed service relies on --reset to cure schema drift: a
    pre-existing ./data volume created before new columns (shipments.flagged,
    orders.priority) only picks up the current schema via drop-and-recreate —
    create_all alone never ALTERs an existing table, leaving every read to
    fail with 'no such column'."""
    from services.tms_api import Base as TMSBase

    db = tmp_path / "tms.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE shipments (shipment_id TEXT PRIMARY KEY, order_id TEXT)")
        conn.execute("INSERT INTO shipments VALUES ('SHP-1', 'ORD-1')")

    def columns() -> set[str]:
        with sqlite3.connect(db) as conn:
            return {row[1] for row in conn.execute("PRAGMA table_info(shipments)")}

    # Without reset, the stale schema survives — the documented failure mode.
    await _create_tables(TMSBase.metadata, db, drop_first=False)
    assert "flagged" not in columns()

    # With reset (what compose runs), the real schema lands.
    await _create_tables(TMSBase.metadata, db, drop_first=True)
    assert "flagged" in columns()


def test_compose_seed_service_resets():
    """docker-compose's seed service must pass --reset (parity with the
    Makefile's seed target); without it a volume from an older schema 500s
    on every request until the flag is discovered by hand."""
    compose = (Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text()
    seed_commands = [line for line in compose.splitlines() if "seed.seed_db" in line]
    assert seed_commands, "compose must define the seed service command"
    assert all("--reset" in line for line in seed_commands)
