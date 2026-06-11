"""Integration tests for OMS API endpoints (Story 15.2)."""


class TestListOrders:
    async def test_list_orders_no_filter(self, oms_client):
        resp = await oms_client.get("/orders")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 6
        assert len(data["items"]) == 6

    async def test_list_orders_status_filter(self, oms_client):
        resp = await oms_client.get("/orders", params={"status": "pending"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        for item in data["items"]:
            assert item["status"] == "pending"

    async def test_list_orders_combined_filter(self, oms_client):
        resp = await oms_client.get("/orders", params={"status": "pending", "channel": "dtc_web"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        for item in data["items"]:
            assert item["status"] == "pending"
            assert item["channel"] == "dtc_web"

    async def test_list_orders_pagination(self, oms_client):
        resp = await oms_client.get("/orders", params={"offset": 0, "limit": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 6
        assert len(data["items"]) == 2
        assert data["offset"] == 0
        assert data["limit"] == 2

        # Second page
        resp2 = await oms_client.get("/orders", params={"offset": 2, "limit": 2})
        data2 = resp2.json()
        assert len(data2["items"]) == 2

        # Third page
        resp3 = await oms_client.get("/orders", params={"offset": 4, "limit": 2})
        data3 = resp3.json()
        assert len(data3["items"]) == 2


class TestGetOrder:
    async def test_get_order_valid(self, oms_client):
        resp = await oms_client.get("/orders/ORD-2025-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["order_id"] == "ORD-2025-001"
        assert data["customer_name"] == "Alice Smith"
        assert "line_items" in data
        assert len(data["line_items"]) == 2

    async def test_get_order_not_found(self, oms_client):
        resp = await oms_client.get("/orders/ORD-NONEXISTENT")
        assert resp.status_code == 404


class TestExceptions:
    async def test_list_exceptions_filter(self, oms_client):
        resp = await oms_client.get(
            "/exceptions", params={"severity": "critical", "status": "open"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["exception_id"] == "EXC-001"
        assert data["items"][0]["severity"] == "critical"
        assert data["items"][0]["status"] == "open"


class TestPatchOrder:
    async def test_patch_order_valid(self, oms_client):
        resp = await oms_client.patch("/orders/ORD-2025-001", json={"status": "processing"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        assert data["order_id"] == "ORD-2025-001"

    async def test_patch_order_not_found(self, oms_client):
        resp = await oms_client.patch("/orders/ORD-NONEXISTENT", json={"status": "processing"})
        assert resp.status_code == 404


class TestPatchException:
    async def test_patch_exception_resolved(self, oms_client):
        resp = await oms_client.patch("/exceptions/EXC-002", json={"status": "resolved"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resolved"
        assert data["resolved_at"] is not None
