"""Unified OpsClient with service-specific async HTTP clients."""

from __future__ import annotations

import asyncio
from typing import Any, TypeVar

import httpx

from config.logging import span_id_var, trace_id_var
from config.settings import Settings, get_settings
from models.oms import (
    DailyStats,
    ExceptionSummary,
    Order,
    OrderException,
    OrderWithLineItems,
)
from models.shared import PaginatedResponse
from models.tms import CarrierStats, Shipment, ShipmentWithTracking, SLASummary
from models.wms import FulfillmentCenter, InventoryItem, StockMovement
from services.exceptions import NotFoundError, ServiceUnavailableError, ValidationError

T = TypeVar("T")


class OpsClient:
    """Async HTTP client that wraps OMS, WMS, and TMS service APIs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        timeout = httpx.Timeout(
            connect=self._settings.http_connect_timeout,
            read=self._settings.http_read_timeout,
            write=5.0,
            pool=5.0,
        )
        self._oms = httpx.AsyncClient(
            base_url=self._settings.oms_api_url, timeout=timeout
        )
        self._wms = httpx.AsyncClient(
            base_url=self._settings.wms_api_url, timeout=timeout
        )
        self._tms = httpx.AsyncClient(
            base_url=self._settings.tms_api_url, timeout=timeout
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> OpsClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close all underlying HTTP clients."""
        await self._oms.aclose()
        await self._wms.aclose()
        await self._tms.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _trace_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "X-API-Key": self._settings.api_secret_key,
        }
        trace_id = trace_id_var.get()
        if trace_id:
            headers["X-Trace-ID"] = trace_id
        span_id = span_id_var.get()
        if span_id:
            headers["X-Span-ID"] = span_id
        return headers

    @staticmethod
    def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
        """Remove None values from query params."""
        return {k: v for k, v in params.items() if v is not None}

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        service: str = "unknown",
        **kwargs: Any,
    ) -> httpx.Response:
        """Make request with retry on 5xx and error mapping."""
        headers = {**self._trace_headers(), **kwargs.pop("headers", {})}
        response: httpx.Response | None = None

        for attempt in range(2):  # 1 retry
            try:
                response = await client.request(
                    method, path, headers=headers, **kwargs
                )
            except httpx.ConnectError:
                raise ServiceUnavailableError(
                    service=service, detail=f"Connection failed for {method} {path}"
                )

            if response.status_code < 500:
                break
            if attempt == 0:
                await asyncio.sleep(1)

        assert response is not None  # always set after the loop

        if response.status_code == 404:
            raise NotFoundError(entity=service, entity_id=path)
        if response.status_code == 422:
            raise ValidationError(detail=response.text)
        if response.status_code >= 500:
            raise ServiceUnavailableError(
                service=service,
                detail=f"Server error {response.status_code} for {method} {path}",
            )

        response.raise_for_status()
        return response

    def _parse_paginated(
        self, data: dict[str, Any], model: type[T]
    ) -> PaginatedResponse[T]:
        """Parse a paginated JSON response into PaginatedResponse[T]."""
        return PaginatedResponse[model](  # type: ignore[valid-type]
            items=[model(**item) for item in data["items"]],
            total=data["total"],
            offset=data["offset"],
            limit=data["limit"],
        )

    # ==================================================================
    # OMS methods
    # ==================================================================

    async def list_orders(
        self,
        *,
        status: str | None = None,
        channel: str | None = None,
        customer_tier: str | None = None,
        fulfillment_center_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> PaginatedResponse[Order]:
        params = self._clean_params(
            {
                "status": status,
                "channel": channel,
                "customer_tier": customer_tier,
                "fulfillment_center_id": fulfillment_center_id,
                "date_from": date_from,
                "date_to": date_to,
                "min_value": min_value,
                "max_value": max_value,
                "offset": offset,
                "limit": limit,
            }
        )
        resp = await self._request(
            self._oms, "GET", "/orders", service="oms", params=params
        )
        return self._parse_paginated(resp.json(), Order)

    async def get_order(self, order_id: str) -> OrderWithLineItems:
        resp = await self._request(
            self._oms, "GET", f"/orders/{order_id}", service="oms"
        )
        return OrderWithLineItems(**resp.json())

    async def get_at_risk_orders(
        self, *, offset: int = 0, limit: int = 50
    ) -> PaginatedResponse[Order]:
        params = {"offset": offset, "limit": limit}
        resp = await self._request(
            self._oms, "GET", "/orders/at-risk", service="oms", params=params
        )
        return self._parse_paginated(resp.json(), Order)

    async def list_exceptions(
        self,
        *,
        exception_type: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> PaginatedResponse[OrderException]:
        params = self._clean_params(
            {
                "exception_type": exception_type,
                "severity": severity,
                "status": status,
                "date_from": date_from,
                "date_to": date_to,
                "offset": offset,
                "limit": limit,
            }
        )
        resp = await self._request(
            self._oms, "GET", "/exceptions", service="oms", params=params
        )
        return self._parse_paginated(resp.json(), OrderException)

    async def get_exception_summary(self) -> ExceptionSummary:
        resp = await self._request(
            self._oms, "GET", "/exceptions/summary", service="oms"
        )
        return ExceptionSummary(**resp.json())

    async def update_order(self, order_id: str, changes: dict[str, Any]) -> Order:
        resp = await self._request(
            self._oms, "PATCH", f"/orders/{order_id}", service="oms", json=changes
        )
        return Order(**resp.json())

    async def update_exception(
        self, exception_id: str, changes: dict[str, Any]
    ) -> OrderException:
        resp = await self._request(
            self._oms,
            "PATCH",
            f"/exceptions/{exception_id}",
            service="oms",
            json=changes,
        )
        return OrderException(**resp.json())

    async def get_daily_stats(self, days: int = 7) -> list[DailyStats]:
        resp = await self._request(
            self._oms, "GET", "/stats/daily", service="oms", params={"days": days}
        )
        return [DailyStats(**item) for item in resp.json()]

    # ==================================================================
    # WMS methods
    # ==================================================================

    async def list_inventory(
        self,
        *,
        sku: str | None = None,
        fulfillment_center_id: str | None = None,
        category: str | None = None,
        below_reorder_point: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> PaginatedResponse[InventoryItem]:
        params = self._clean_params(
            {
                "sku": sku,
                "fulfillment_center_id": fulfillment_center_id,
                "category": category,
                "below_reorder_point": below_reorder_point,
                "offset": offset,
                "limit": limit,
            }
        )
        resp = await self._request(
            self._wms, "GET", "/inventory", service="wms", params=params
        )
        return self._parse_paginated(resp.json(), InventoryItem)

    async def get_low_stock(
        self, *, offset: int = 0, limit: int = 50
    ) -> PaginatedResponse[InventoryItem]:
        params = {"offset": offset, "limit": limit}
        resp = await self._request(
            self._wms, "GET", "/inventory/low-stock", service="wms", params=params
        )
        return self._parse_paginated(resp.json(), InventoryItem)

    async def list_centers(self) -> list[FulfillmentCenter]:
        resp = await self._request(self._wms, "GET", "/centers", service="wms")
        return [FulfillmentCenter(**item) for item in resp.json()]

    async def get_center_inventory(
        self, center_id: str, *, offset: int = 0, limit: int = 50
    ) -> PaginatedResponse[InventoryItem]:
        params = {"offset": offset, "limit": limit}
        resp = await self._request(
            self._wms,
            "GET",
            f"/centers/{center_id}/inventory",
            service="wms",
            params=params,
        )
        return self._parse_paginated(resp.json(), InventoryItem)

    async def list_movements(
        self,
        *,
        sku: str | None = None,
        fulfillment_center_id: str | None = None,
        movement_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> PaginatedResponse[StockMovement]:
        params = self._clean_params(
            {
                "sku": sku,
                "fulfillment_center_id": fulfillment_center_id,
                "movement_type": movement_type,
                "date_from": date_from,
                "date_to": date_to,
                "offset": offset,
                "limit": limit,
            }
        )
        resp = await self._request(
            self._wms, "GET", "/movements", service="wms", params=params
        )
        return self._parse_paginated(resp.json(), StockMovement)

    async def get_utilization(self) -> list[FulfillmentCenter]:
        resp = await self._request(
            self._wms, "GET", "/stats/utilization", service="wms"
        )
        return [FulfillmentCenter(**item) for item in resp.json()]

    # ==================================================================
    # TMS methods
    # ==================================================================

    async def list_shipments(
        self,
        *,
        carrier: str | None = None,
        status: str | None = None,
        sla_status: str | None = None,
        origin_center_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> PaginatedResponse[Shipment]:
        params = self._clean_params(
            {
                "carrier": carrier,
                "status": status,
                "sla_status": sla_status,
                "origin_center_id": origin_center_id,
                "date_from": date_from,
                "date_to": date_to,
                "offset": offset,
                "limit": limit,
            }
        )
        resp = await self._request(
            self._tms, "GET", "/shipments", service="tms", params=params
        )
        return self._parse_paginated(resp.json(), Shipment)

    async def get_shipment(self, shipment_id: str) -> ShipmentWithTracking:
        resp = await self._request(
            self._tms, "GET", f"/shipments/{shipment_id}", service="tms"
        )
        return ShipmentWithTracking(**resp.json())

    async def get_sla_breaches(
        self, *, offset: int = 0, limit: int = 50
    ) -> PaginatedResponse[Shipment]:
        params = {"offset": offset, "limit": limit}
        resp = await self._request(
            self._tms, "GET", "/shipments/sla-breaches", service="tms", params=params
        )
        return self._parse_paginated(resp.json(), Shipment)

    async def get_shipments_for_order(self, order_id: str) -> list[Shipment]:
        resp = await self._request(
            self._tms, "GET", f"/shipments/by-order/{order_id}", service="tms"
        )
        return [Shipment(**item) for item in resp.json()]

    async def get_carrier_performance(self) -> list[CarrierStats]:
        resp = await self._request(
            self._tms, "GET", "/stats/carrier-performance", service="tms"
        )
        return [CarrierStats(**item) for item in resp.json()]

    async def get_sla_summary(self) -> SLASummary:
        resp = await self._request(
            self._tms, "GET", "/stats/sla-summary", service="tms"
        )
        return SLASummary(**resp.json())

    async def update_shipment(
        self, shipment_id: str, changes: dict[str, Any]
    ) -> Shipment:
        resp = await self._request(
            self._tms,
            "PATCH",
            f"/shipments/{shipment_id}",
            service="tms",
            json=changes,
        )
        return Shipment(**resp.json())
