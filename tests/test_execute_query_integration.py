"""Integration tests for execute_query over the in-process ASGI apps (TEST-2).

The dispatch/join layer was only ever tested with itself mocked. These drive the
real execute_query against a real OpsClient wired to the test apps, with plans
built inline (no LLM, no interpreter).
"""

import httpx

from agent.copilot import execute_query
from models.query import DataFilter, QueryPlan
from models.shared import TargetSystem, UserIntent


def _plan(system: TargetSystem, entity: str, filters: list[DataFilter], **kwargs) -> QueryPlan:
    return QueryPlan(
        intent=UserIntent.STATUS_CHECK,
        target_systems=[system],
        primary_entity=entity,
        filters=filters,
        confidence=0.9,
        reasoning="integration plan",
        **kwargs,
    )


async def test_at_risk_shortcut(ops_client):
    plan = _plan(
        TargetSystem.OMS, "order", [DataFilter(field="at_risk", operator="eq", value=True)]
    )
    result = await execute_query(ops_client, plan)
    assert result.total_count >= 1
    assert "ORD-2025-006" in {r["order_id"] for r in result.data}


async def test_low_stock_shortcut(ops_client):
    plan = _plan(
        TargetSystem.WMS,
        "inventory",
        [DataFilter(field="below_reorder_point", operator="eq", value=True)],
    )
    result = await execute_query(ops_client, plan)
    skus = {r["sku"] for r in result.data}
    assert {"SKU-B200", "SKU-D400"} == skus  # only the rows below reorder point


async def test_sla_breached_shortcut(ops_client):
    plan = _plan(
        TargetSystem.TMS,
        "shipment",
        [DataFilter(field="sla_status", operator="eq", value="breached")],
    )
    result = await execute_query(ops_client, plan)
    # The endpoint also surfaces at_risk shipments, so assert membership.
    assert "SHP-20250303-00003" in {r["shipment_id"] for r in result.data}


async def test_cross_system_join_emits_prefixed_keys(ops_client):
    plan = QueryPlan(
        intent=UserIntent.CROSS_SYSTEM_QUERY,
        target_systems=[TargetSystem.OMS, TargetSystem.TMS],
        primary_entity="order",
        filters=[],
        confidence=0.9,
        reasoning="orders with shipments",
        requires_join=True,
        join_key="order_id",
    )
    result = await execute_query(ops_client, plan)
    assert result.data
    assert all("order_id" in row for row in result.data)
    joined = [
        row
        for row in result.data
        if any(k.startswith("oms_") for k in row) and any(k.startswith("tms_") for k in row)
    ]
    assert joined, "expected at least one row joined across OMS and TMS"


async def test_partial_failure_when_one_system_unreachable(ops_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("tms down")

    ops_client._tms = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://tms"
    )
    plan = QueryPlan(
        intent=UserIntent.CROSS_SYSTEM_QUERY,
        target_systems=[TargetSystem.OMS, TargetSystem.TMS],
        primary_entity="order",
        filters=[],
        confidence=0.9,
        reasoning="orders with shipments",
        requires_join=True,
        join_key="order_id",
    )
    result = await execute_query(ops_client, plan)
    assert result.partial_failure is True
    assert "tms" in (result.error_details or {})
    assert result.data  # OMS rows still present
