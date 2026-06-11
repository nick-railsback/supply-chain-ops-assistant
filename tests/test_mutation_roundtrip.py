"""Mutation round-trips for escalate/flag (REL-1, SEC-3).

escalate_order PATCHes {"priority": "urgent"} and flag_shipments PATCHes
{"flagged": true}. Before this change the patch models lacked those fields,
Pydantic's default extra="ignore" dropped them, the PATCH returned 200, and the
target was reported as a success having changed nothing. These tests pin that
the columns exist end to end and that unknown/invalid fields 422 instead of
vanishing.
"""


class TestMutationRoundTrip:
    async def test_escalate_priority_roundtrip(self, oms_client):
        resp = await oms_client.patch("/orders/ORD-2025-001", json={"priority": "urgent"})
        assert resp.status_code == 200
        assert resp.json()["priority"] == "urgent"
        reread = await oms_client.get("/orders/ORD-2025-001")
        assert reread.json()["priority"] == "urgent"

    async def test_flag_shipment_roundtrip(self, tms_client):
        resp = await tms_client.patch("/shipments/SHP-20250301-00001", json={"flagged": True})
        assert resp.status_code == 200
        reread = await tms_client.get("/shipments/SHP-20250301-00001")
        assert reread.json()["flagged"] is True

    async def test_unknown_patch_field_is_422(self, oms_client):
        resp = await oms_client.patch("/orders/ORD-2025-001", json={"bogus_field": 1})
        assert resp.status_code == 422

    async def test_invalid_status_value_is_422(self, oms_client):
        resp = await oms_client.patch("/orders/ORD-2025-001", json={"status": "warp_speed"})
        assert resp.status_code == 422

    async def test_exception_patch_rejects_severity(self, oms_client):
        resp = await oms_client.patch("/exceptions/EXC-001", json={"severity": "low"})
        assert resp.status_code == 422
