"""Integration tests for OpsClient over the in-process ASGI apps (TEST-1).

Every prior consumer mocked OpsClient, so its retry, 404/422/5xx mapping, and
header injection had no real executions. These run the real client against the
test apps (and a couple of MockTransport handlers for the network-error paths).
"""

from unittest.mock import AsyncMock

import httpx
import pytest

from config.logging import new_trace
from services.exceptions import NotFoundError, ServiceUnavailableError, ValidationError


async def test_404_maps_to_not_found_error(ops_client):
    with pytest.raises(NotFoundError):
        await ops_client.get_order("ORD-NOPE")


async def test_422_maps_to_validation_error(ops_client):
    # extra="forbid" on OrderPatch turns an unknown field into a 422.
    with pytest.raises(ValidationError):
        await ops_client.update_order("ORD-2025-001", {"bogus": 1})


async def test_5xx_retries_once_then_maps(ops_client, monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="boom")

    monkeypatch.setattr("services.client.asyncio.sleep", AsyncMock())
    ops_client._oms = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://oms"
    )
    with pytest.raises(ServiceUnavailableError):
        await ops_client.list_orders()
    assert calls["n"] == 2  # one initial attempt + one retry


async def test_connect_error_maps(ops_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    ops_client._oms = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://oms"
    )
    with pytest.raises(ServiceUnavailableError):
        await ops_client.list_orders()


async def test_timeout_maps(ops_client):
    # ConnectTimeout/ReadTimeout are not ConnectError subclasses; the client must
    # still map them (Task 2b widened the except clause).
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    ops_client._oms = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://oms"
    )
    with pytest.raises(ServiceUnavailableError):
        await ops_client.list_orders()


async def test_api_key_and_trace_headers_arrive_server_side(ops_client):
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.headers))
        return httpx.Response(200, json={"items": [], "total": 0, "offset": 0, "limit": 50})

    tid = new_trace()
    ops_client._oms = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://oms"
    )
    await ops_client.list_orders()

    assert captured["x-api-key"] == "dev-secret-key-change-me"
    assert captured["x-trace-id"] == tid
