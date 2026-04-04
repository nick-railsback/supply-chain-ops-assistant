"""Integration tests for WMS and TMS API endpoints (Story 15.3)."""

import pytest


# ---------------------------------------------------------------------------
# WMS Tests
# ---------------------------------------------------------------------------


class TestWMSInventory:
    async def test_list_inventory_no_filter(self, wms_client):
        resp = await wms_client.get("/inventory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 5

    async def test_list_inventory_sku_filter(self, wms_client):
        resp = await wms_client.get("/inventory", params={"sku": "SKU-A100"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        for item in data["items"]:
            assert item["sku"] == "SKU-A100"

    async def test_list_inventory_center_filter(self, wms_client):
        resp = await wms_client.get(
            "/inventory", params={"fulfillment_center_id": "FC-EAST"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        for item in data["items"]:
            assert item["fulfillment_center_id"] == "FC-EAST"

    async def test_list_low_stock(self, wms_client):
        resp = await wms_client.get("/inventory/low-stock")
        assert resp.status_code == 200
        data = resp.json()
        # INV-00000002 (available=5, reorder=50) and INV-00000004 (available=2, reorder=25)
        assert data["total"] == 2
        for item in data["items"]:
            assert item["quantity_available"] < item["reorder_point"]


class TestWMSCenters:
    async def test_list_centers(self, wms_client):
        resp = await wms_client.get("/centers")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        center_ids = {c["center_id"] for c in data}
        assert center_ids == {"FC-EAST", "FC-WEST"}


# ---------------------------------------------------------------------------
# TMS Tests
# ---------------------------------------------------------------------------


class TestTMSShipments:
    async def test_list_shipments_carrier_filter(self, tms_client):
        resp = await tms_client.get("/shipments", params={"carrier": "FedEx"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        for item in data["items"]:
            assert item["carrier"] == "FedEx"

    async def test_list_shipments_sla_status_filter(self, tms_client):
        resp = await tms_client.get(
            "/shipments", params={"sla_status": "breached"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["sla_status"] == "breached"
        assert data["items"][0]["shipment_id"] == "SHP-20250303-00003"

    async def test_get_shipment_with_tracking(self, tms_client):
        resp = await tms_client.get("/shipments/SHP-20250301-00001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["shipment_id"] == "SHP-20250301-00001"
        assert "tracking_events" in data
        assert len(data["tracking_events"]) == 3

    async def test_get_shipment_not_found(self, tms_client):
        resp = await tms_client.get("/shipments/SHP-NONEXISTENT")
        assert resp.status_code == 404


class TestTMSPatchShipment:
    async def test_patch_shipment_valid(self, tms_client):
        resp = await tms_client.patch(
            "/shipments/SHP-20250301-00001",
            json={"status": "delivered"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "delivered"

    async def test_patch_shipment_invalid_status(self, tms_client):
        resp = await tms_client.patch(
            "/shipments/SHP-20250301-00001",
            json={"status": "not_a_real_status"},
        )
        assert resp.status_code == 422
