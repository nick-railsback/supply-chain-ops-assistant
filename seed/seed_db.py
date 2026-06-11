"""Database seeding CLI script with --reset flag.

Creates and populates three SQLite databases (OMS, WMS, TMS) under ``data/``.
Uses SQLAlchemy Core + aiosqlite for async table creation and bulk inserts.

Usage::

    python -m seed.seed_db           # seed only if tables are empty
    python -m seed.seed_db --reset   # drop & recreate all tables
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from seed.generator import DataGenerator
from services.oms_api import Base as OMSBase
from services.tms_api import Base as TMSBase
from services.wms_api import Base as WMSBase

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
OMS_DB = DATA_DIR / "oms.db"
WMS_DB = DATA_DIR / "wms.db"
TMS_DB = DATA_DIR / "tms.db"

# ---------------------------------------------------------------------------
# Schema source of truth: the seeder creates and fills exactly the tables the
# services declare, via their Base.metadata. Adding a column to an ORM model is
# now a one-file edit. Each service declares its own DeclarativeBase, so the
# three metadata don't bleed together; services never import seed, so there's
# no import cycle.
# ---------------------------------------------------------------------------
oms_metadata = OMSBase.metadata
wms_metadata = WMSBase.metadata
tms_metadata = TMSBase.metadata

orders_table = oms_metadata.tables["orders"]
line_items_table = oms_metadata.tables["line_items"]
order_exceptions_table = oms_metadata.tables["order_exceptions"]
fulfillment_centers_table = wms_metadata.tables["fulfillment_centers"]
inventory_table = wms_metadata.tables["inventory"]
stock_movements_table = wms_metadata.tables["stock_movements"]
shipments_table = tms_metadata.tables["shipments"]
tracking_events_table = tms_metadata.tables["tracking_events"]

# ---------------------------------------------------------------------------
# Database URL helpers
# ---------------------------------------------------------------------------

DB_CONFIGS: list[tuple[Path, sa.MetaData]] = [
    (OMS_DB, oms_metadata),
    (WMS_DB, wms_metadata),
    (TMS_DB, tms_metadata),
]


def _url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path}"


# ---------------------------------------------------------------------------
# Mapping helpers: generator dicts -> table rows
# ---------------------------------------------------------------------------

# Lookup product catalog for category info
_PRODUCT_BY_SKU: dict[str, dict[str, object]] = {}


def _build_product_index() -> None:
    from seed.constants import PRODUCT_CATALOG

    for p in PRODUCT_CATALOG:
        _PRODUCT_BY_SKU[str(p["sku"])] = p


def _map_orders(
    orders: list[dict[str, Any]], line_items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Map generator order dicts to the orders table schema."""
    # Pre-compute per-order aggregates from line items
    order_totals: dict[str, float] = {}
    order_li_counts: dict[str, int] = {}
    for li in line_items:
        oid = li["order_id"]
        order_totals[oid] = order_totals.get(oid, 0.0) + li["line_total"]
        order_li_counts[oid] = order_li_counts.get(oid, 0) + 1

    rows: list[dict[str, Any]] = []
    for o in orders:
        oid = o["order_id"]
        addr = o.get("shipping_address", {})
        rows.append(
            {
                "order_id": oid,
                "customer_id": None,
                "customer_name": o["customer_name"],
                "customer_email": o["customer_email"],
                "customer_tier": o["customer_tier"],
                "status": o["status"],
                "channel": o["channel"],
                "created_at": o["created_at"],
                "updated_at": o["updated_at"],
                "promised_delivery_date": o.get("promised_delivery_date"),
                "fulfillment_center_id": o["fulfillment_center_id"],
                "total_value": round(order_totals.get(oid, 0.0), 2),
                "currency": "USD",
                "line_item_count": order_li_counts.get(oid, 0),
                "notes": json.dumps(addr) if addr else None,
            }
        )
    return rows


def _map_line_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "line_item_id": li["line_item_id"],
            "order_id": li["order_id"],
            "sku": li["sku"],
            "product_name": li["product_name"],
            "quantity": li["quantity"],
            "unit_price": li["unit_price"],
            "status": li["status"],
        }
        for li in items
    ]


def _map_exceptions(exceptions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "exception_id": e["exception_id"],
            "order_id": e["order_id"],
            "exception_type": e["type"],
            "severity": e["severity"],
            "status": e["status"],
            "created_at": e["created_at"],
            "resolved_at": e.get("resolved_at"),
            "description": e["description"],
            "assigned_to": None,
        }
        for e in exceptions
    ]


def _map_centers(centers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "center_id": c["id"],
            "name": c["name"],
            "region": c["region"],
            "capacity_units": c["capacity_units"],
            "current_utilization": c["current_utilization"],
            "active": True,
        }
        for c in centers
    ]


def _map_inventory(inv: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _build_product_index()
    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(inv, start=1):
        sku = item["sku"]
        product = _PRODUCT_BY_SKU.get(sku, {})
        rows.append(
            {
                "inventory_id": f"INV-{idx:06d}",
                "sku": sku,
                "product_name": str(product.get("name", "")),
                "fulfillment_center_id": item["center_id"],
                "quantity_on_hand": item["on_hand"],
                "quantity_allocated": item["quantity_reserved"],
                "quantity_available": item["quantity_available"],
                "reorder_point": item["reorder_point"],
                "last_counted_at": item["last_replenishment"],
                "category": str(product.get("category", "")),
            }
        )
    return rows


def _map_stock_movements(inv: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate synthetic stock movements based on inventory rows."""
    movements: list[dict[str, Any]] = []
    seq = 0
    for item in inv:
        seq += 1
        movements.append(
            {
                "movement_id": f"MOV-{seq:07d}",
                "sku": item["sku"],
                "fulfillment_center_id": item["center_id"],
                "movement_type": "replenishment",
                "quantity": item["on_hand"],
                "reference_id": None,
                "timestamp": item["last_replenishment"],
            }
        )
    return movements


def _map_shipments(shipments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "shipment_id": s["shipment_id"],
            "order_id": s["order_id"],
            "carrier": s["carrier"],
            "service_level": s["service_level"],
            "status": s["status"],
            "tracking_number": s["tracking_number"],
            "origin_center_id": s["origin_center_id"],
            "destination_zip": s["destination_zip"],
            "destination_state": s["destination_state"],
            "weight_lbs": round(random.uniform(0.5, 25.0), 1),
            "shipping_cost": round(random.uniform(5.0, 45.0), 2),
            "label_created_at": s["shipped_at"],
            "estimated_delivery": s["estimated_delivery"],
            "actual_delivery": None,
            "sla_target": s["estimated_delivery"],
            "sla_status": s["sla_status"],
        }
        for s in shipments
    ]


def _map_tracking_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "event_id": e["event_id"],
            "shipment_id": e["shipment_id"],
            "timestamp": e["timestamp"],
            "location": e["location"],
            "status": e["event_type"],
            "description": e["details"],
        }
        for e in events
    ]


# ---------------------------------------------------------------------------
# Async DB operations
# ---------------------------------------------------------------------------


async def _create_tables(metadata: sa.MetaData, db_path: Path, *, drop_first: bool = False) -> None:
    engine = create_async_engine(_url(db_path))
    async with engine.begin() as conn:
        if drop_first:
            await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)
    await engine.dispose()


async def _insert_rows(table: sa.Table, rows: list[dict[str, Any]], db_path: Path) -> None:
    if not rows:
        return
    engine = create_async_engine(_url(db_path))
    async with engine.begin() as conn:
        await conn.execute(table.insert(), rows)
    await engine.dispose()


async def _table_empty(table: sa.Table, db_path: Path) -> bool:
    engine = create_async_engine(_url(db_path))
    async with engine.begin() as conn:
        result = await conn.execute(sa.select(sa.func.count()).select_from(table))
        count = result.scalar() or 0
    await engine.dispose()
    return count == 0


# ---------------------------------------------------------------------------
# Main seeding logic
# ---------------------------------------------------------------------------


async def _seed(*, reset: bool = False) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Phase 1: Create (or reset) tables
    for db_path, metadata in DB_CONFIGS:
        label = db_path.stem.upper()
        if reset:
            print(f"  Resetting {label} tables in {db_path.name} ...")
        else:
            print(f"  Ensuring {label} tables exist in {db_path.name} ...")
        await _create_tables(metadata, db_path, drop_first=reset)

    # Phase 2: Check if seeding is needed
    if not reset:
        orders_empty = await _table_empty(orders_table, OMS_DB)
        centers_empty = await _table_empty(fulfillment_centers_table, WMS_DB)
        shipments_empty = await _table_empty(shipments_table, TMS_DB)
        if not (orders_empty and centers_empty and shipments_empty):
            print("  Tables already contain data. Use --reset to re-seed.")
            return

    # Phase 3: Generate data
    print("  Generating seed data ...")
    gen = DataGenerator(seed_value=42)
    data = gen.generate_all()

    # Phase 4: Map and insert
    # --- WMS ---
    centers_rows = _map_centers(data["fulfillment_centers"])
    print(f"  Inserting {len(centers_rows)} fulfillment centers ...")
    await _insert_rows(fulfillment_centers_table, centers_rows, WMS_DB)

    inventory_rows = _map_inventory(data["inventory"])
    print(f"  Inserting {len(inventory_rows)} inventory records ...")
    await _insert_rows(inventory_table, inventory_rows, WMS_DB)

    movements_rows = _map_stock_movements(data["inventory"])
    print(f"  Inserting {len(movements_rows)} stock movements ...")
    await _insert_rows(stock_movements_table, movements_rows, WMS_DB)

    # --- OMS ---
    li_rows = _map_line_items(data["line_items"])
    order_rows = _map_orders(data["orders"], data["line_items"])
    print(f"  Inserting {len(order_rows)} orders ...")
    await _insert_rows(orders_table, order_rows, OMS_DB)

    print(f"  Inserting {len(li_rows)} line items ...")
    await _insert_rows(line_items_table, li_rows, OMS_DB)

    exception_rows = _map_exceptions(data["exceptions"])
    print(f"  Inserting {len(exception_rows)} order exceptions ...")
    await _insert_rows(order_exceptions_table, exception_rows, OMS_DB)

    # --- TMS ---
    shipment_rows = _map_shipments(data["shipments"])
    print(f"  Inserting {len(shipment_rows)} shipments ...")
    await _insert_rows(shipments_table, shipment_rows, TMS_DB)

    event_rows = _map_tracking_events(data["tracking_events"])
    print(f"  Inserting {len(event_rows)} tracking events ...")
    await _insert_rows(tracking_events_table, event_rows, TMS_DB)

    print("  Seeding complete.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed supply-chain databases.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate all tables before seeding.",
    )
    args = parser.parse_args()
    print("seed_db: starting ...")
    asyncio.run(_seed(reset=args.reset))
    print("seed_db: done.")


if __name__ == "__main__":
    main()
