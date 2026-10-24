"""One-off snapshot of candidate stuck-order cases from the seeded stack.

Not imported by any test, not part of ``suite_cmd``, and not runnable in a
fresh clone: ``data/*.db`` is gitignored, so this only works on a machine that
has already run ``make seed``. It drives the three FastAPI apps in-process
over ASGI — the same rig ``tests/conftest.py`` uses — rather than requiring
``make serve``, and it only ever reads the seeded databases.

Every candidate is emitted with ``"label": null``. Nothing here computes,
suggests, or defaults a root-cause label — selection is entirely a function
of ``triage.detection.is_stuck``, which never looks at a label or an
exception's ``exception_type``. Labeling is a separate, human, hands-on step:
see ``evals/triage_dataset.md``.
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from models.oms import Order
from services.client import OpsClient
from services.exceptions import ServiceUnavailableError
from triage.detection import is_stuck
from triage.models import TriageCase
from triage.taxonomy import RootCause

# Mirrors seed/seed_db.py's DataGenerator(seed_value=42) — the only seed-named
# integer literal in this file, so the disclosure's seed_value is checkable
# against it.
SEED_VALUE = 42

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "evals" / "triage_dataset.jsonl"

_PAGE_SIZE = 200

# The seeded data's staleness is relative to capture time, not seed time, so
# how many orders read as stuck grows the longer it's been since `make seed`
# last ran — far more than the plan's "roughly 40" assumed. A flat positional
# cut over the full stuck pool risks dropping a whole taxonomy class by
# accident: on this data, every address_invalid-flagged order happened to
# sort past a 45-candidate case_id cutoff, silently excluding the class.
# Every stuck order carrying at least one exception (presence only — never
# `exception_type`, so this reads no more of the label-adjacent signal than
# the old cut did) is kept in full instead, padded with a case_id-sorted
# slice of exception-free stuck orders for the staleness-only cases.
# MAX_TOTAL_CANDIDATES is a safety ceiling against a pathological future
# re-seed; it is not expected to bind on data shaped like this run's.
NO_EXCEPTION_SAMPLE = 20
MAX_TOTAL_CANDIDATES = 150

# is_stuck never reads this: it exists only to satisfy TriageCase's required
# `label` field while probing whether an order is stuck, before any case is
# assembled or written to disk. Constant regardless of which order it probes,
# so it carries no signal about root cause.
_PROBE_LABEL = RootCause.INVENTORY


async def _build_ops_client(oms_app: Any, wms_app: Any, tms_app: Any) -> OpsClient:
    client = OpsClient()
    await client.aclose()  # drop the real network clients
    # raise_app_exceptions=False: over a direct ASGI transport, Starlette's
    # error middleware re-raises an unhandled exception into the caller
    # instead of returning a 500 response (default behaviour for
    # TestClient/ASGITransport). This script scans hundreds of candidates
    # opportunistically, so a data/service bug should surface the same way it
    # would over real HTTP — a mappable 500 — not crash the sweep.
    client._oms = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=oms_app, raise_app_exceptions=False),
        base_url="http://oms",
    )
    client._wms = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=wms_app, raise_app_exceptions=False),
        base_url="http://wms",
    )
    client._tms = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=tms_app, raise_app_exceptions=False),
        base_url="http://tms",
    )
    return client


async def _list_all_orders(client: OpsClient) -> list[Order]:
    orders: list[Order] = []
    offset = 0
    while True:
        page = await client.list_orders(offset=offset, limit=_PAGE_SIZE)
        orders.extend(page.items)
        offset += len(page.items)
        if not page.items or offset >= page.total:
            break
    return orders


async def _exceptions_by_order(client: OpsClient) -> dict[str, list[Any]]:
    by_order: dict[str, list[Any]] = {}
    offset = 0
    while True:
        page = await client.list_exceptions(offset=offset, limit=_PAGE_SIZE)
        for exception in page.items:
            by_order.setdefault(exception.order_id, []).append(exception)
        offset += len(page.items)
        if not page.items or offset >= page.total:
            break
    return by_order


async def _inventory_for_skus(client: OpsClient, skus: set[str]) -> list[Any]:
    by_id: dict[str, Any] = {}
    for sku in sorted(skus):
        page = await client.list_inventory(sku=sku)
        for item in page.items:
            by_id[item.inventory_id] = item
    return list(by_id.values())


async def _capture() -> list[dict[str, Any]]:
    from services.oms_api import app as oms_app
    from services.tms_api import app as tms_app
    from services.wms_api import app as wms_app

    captured_at = datetime.now(UTC)
    client = await _build_ops_client(oms_app, wms_app, tms_app)
    try:
        orders = await _list_all_orders(client)
        exceptions_by_order = await _exceptions_by_order(client)

        stuck_orders = []
        for order in orders:
            probe = TriageCase(
                case_id=order.order_id,
                as_of=captured_at,
                label=_PROBE_LABEL,
                order=order,
                line_items=[],
                exceptions=exceptions_by_order.get(order.order_id, []),
                shipment=None,
                inventory=[],
            )
            if is_stuck(case=probe, at=captured_at):
                stuck_orders.append(order)

        with_exception = [o for o in stuck_orders if exceptions_by_order.get(o.order_id)]
        without_exception = sorted(
            (o for o in stuck_orders if not exceptions_by_order.get(o.order_id)),
            key=lambda o: o.order_id,
        )
        selected_orders = with_exception + without_exception[:NO_EXCEPTION_SAMPLE]

        records = []
        skipped: list[str] = []
        for order in selected_orders:
            try:
                detail = await client.get_order(order.order_id)
            except ServiceUnavailableError:
                # Pre-existing bug outside this chunk's scope: some seeded line
                # items carry a status (e.g. "picking") that
                # models.oms.LineItemStatus doesn't declare, and GET
                # /orders/{id} 500s building the response. Candidate chunk,
                # not fixed here — see the plan's handoff note.
                skipped.append(f"{order.order_id} (order detail fetch failed)")
                continue

            line_items = detail.line_items
            skus = {li.sku for li in line_items}
            inventory = await _inventory_for_skus(client, skus)

            stocked_skus = {item.sku for item in inventory}
            if not skus <= stocked_skus:
                skipped.append(f"{order.order_id} (sku missing from inventory)")
                continue

            shipments = await client.get_shipments_for_order(order.order_id)
            shipment = shipments[0] if shipments else None

            records.append(
                {
                    "case_id": order.order_id,
                    "as_of": captured_at.isoformat(),
                    "label": None,
                    "order": detail.model_dump(mode="json", exclude={"line_items"}),
                    "line_items": [li.model_dump(mode="json") for li in line_items],
                    "exceptions": [
                        exc.model_dump(mode="json")
                        for exc in exceptions_by_order.get(order.order_id, [])
                    ],
                    "shipment": shipment.model_dump(mode="json") if shipment else None,
                    "inventory": [item.model_dump(mode="json") for item in inventory],
                }
            )
    finally:
        await client.aclose()

    if skipped:
        print(f"skipped {len(skipped)} stuck order(s): {skipped}", file=sys.stderr)

    records.sort(key=lambda r: str(r["case_id"]))
    if len(records) > MAX_TOTAL_CANDIDATES:
        print(
            f"capping {len(records)} candidates to the safety ceiling of "
            f"{MAX_TOTAL_CANDIDATES} by case_id",
            file=sys.stderr,
        )
        records = records[:MAX_TOTAL_CANDIDATES]
    return records


def main() -> None:
    records = asyncio.run(_capture())
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    print(f"captured {len(records)} candidate stuck-order case(s) -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
