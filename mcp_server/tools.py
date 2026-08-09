"""Tool logic: plain async functions against a shared OpsClient.

No MCP-specific imports here -- mcp_server/server.py is the only module that
knows about the protocol layer. A tool function that raises lets the
exception propagate; the server layer's registration turns any exception
into a tool-level error, so nothing here needs to catch OpsClient's
NotFoundError / ServiceUnavailableError itself.
"""

from datetime import datetime

from mcp_server.models import TriageContext
from models.oms import Order, OrderException
from models.tms import CarrierStats
from models.wms import InventoryItem
from services.client import OpsClient
from triage.detection import is_stuck
from triage.models import TriageCase
from triage.taxonomy import RootCause

_PAGE_SIZE = 200

# is_stuck never reads this: it exists only to satisfy TriageCase's required
# `label` field while probing whether an order is stuck. Constant regardless
# of which order it probes, so it carries no signal about root cause.
_PROBE_LABEL = RootCause.INVENTORY

# A fixed ceiling on how many stuck-order ids one call returns, independent
# of how many orders are actually stuck live. Protects both the 30-second
# per-call budget and the calling agent's context window.
MAX_STUCK_ORDERS = 100


def _naive(value: datetime | None) -> datetime | None:
    """Strip tzinfo so mixed naive/aware seed timestamps compare cleanly.

    is_stuck (triage/detection.py, out of this chunk's scope) does bare `<`
    and subtraction on datetimes with no tz normalization of its own. Seeded
    order/exception rows are not consistently naive or aware, so comparing
    an aware `at` against a naive field (or vice versa) raises TypeError.
    Normalizing every timestamp to naive before building a probe case
    sidesteps that without touching is_stuck itself.
    """
    if value is None or value.tzinfo is None:
        return value
    return value.replace(tzinfo=None)


def _naive_order(order: Order) -> Order:
    return order.model_copy(
        update={
            "created_at": _naive(order.created_at),
            "updated_at": _naive(order.updated_at),
            "promised_delivery_date": _naive(order.promised_delivery_date),
        }
    )


def _naive_exception(exception: OrderException) -> OrderException:
    return exception.model_copy(
        update={
            "created_at": _naive(exception.created_at),
            "resolved_at": _naive(exception.resolved_at),
        }
    )


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


async def _exceptions_by_order(client: OpsClient) -> dict[str, list[OrderException]]:
    by_order: dict[str, list[OrderException]] = {}
    offset = 0
    while True:
        page = await client.list_exceptions(offset=offset, limit=_PAGE_SIZE)
        for exception in page.items:
            by_order.setdefault(exception.order_id, []).append(exception)
        offset += len(page.items)
        if not page.items or offset >= page.total:
            break
    return by_order


async def _exceptions_for_order(client: OpsClient, order_id: str) -> list[OrderException]:
    # OpsClient.list_exceptions has no per-order filter, so this re-scans the
    # whole exceptions table per call -- O(all exceptions), not O(this
    # order's exceptions). Acceptable at this dataset's size (a few hundred
    # rows at most) and inside the 30-second per-call budget.
    matches: list[OrderException] = []
    offset = 0
    while True:
        page = await client.list_exceptions(offset=offset, limit=_PAGE_SIZE)
        matches.extend(exception for exception in page.items if exception.order_id == order_id)
        offset += len(page.items)
        if not page.items or offset >= page.total:
            break
    return matches


async def _inventory_for_skus(client: OpsClient, skus: set[str]) -> list[InventoryItem]:
    by_id: dict[str, InventoryItem] = {}
    for sku in sorted(skus):
        page = await client.list_inventory(sku=sku)
        for item in page.items:
            by_id[item.inventory_id] = item
    return list(by_id.values())


async def get_order_triage_context(client: OpsClient, order_id: str) -> TriageContext:
    detail = await client.get_order(order_id)
    order_data = Order(**detail.model_dump(exclude={"line_items"}))
    line_items = detail.line_items

    exceptions = await _exceptions_for_order(client, order_id)

    shipments = await client.get_shipments_for_order(order_id)
    shipment = shipments[0] if shipments else None

    skus = {line_item.sku for line_item in line_items}
    inventory = await _inventory_for_skus(client, skus)

    return TriageContext(
        order=order_data,
        line_items=line_items,
        exceptions=exceptions,
        shipment=shipment,
        inventory=inventory,
    )


async def list_stuck_orders(client: OpsClient) -> list[str]:
    orders = await _list_all_orders(client)
    exceptions_by_order = await _exceptions_by_order(client)

    at = datetime.now()  # naive, to match the normalization below
    stuck_ids: list[str] = []
    for order in orders:
        probe = TriageCase(
            case_id=order.order_id,
            as_of=at,
            label=_PROBE_LABEL,
            order=_naive_order(order),
            line_items=[],
            exceptions=[_naive_exception(e) for e in exceptions_by_order.get(order.order_id, [])],
            shipment=None,
            inventory=[],
        )
        if is_stuck(case=probe, at=at):
            stuck_ids.append(order.order_id)

    return stuck_ids[:MAX_STUCK_ORDERS]


async def get_carrier_stats(client: OpsClient) -> list[CarrierStats]:
    return await client.get_carrier_performance()
