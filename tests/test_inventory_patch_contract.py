"""Contract tests for mutating an inventory record over HTTP.

An inventory row is writable through ``PATCH /inventory/{inventory_id}`` on the
warehouse service. These tests pin that write path from the outside: which
fields a patch body may name, which bodies are refused, that a refused patch
leaves the stored row byte-for-byte as it was, and the invariants the stored
record must still satisfy after an accepted write. They also pin the unified
ops client's reach to the same endpoint.

Everything here is asserted through HTTP status codes, response bodies, and
re-reads of the record through the public list views -- nothing inspects how
the service is built.
"""

import httpx
import pytest

from config.logging import new_span, new_trace
from models.wms import InventoryItem

# The seeded row these tests mutate: on hand 500, allocated 100, available 400,
# reorder point 50, last counted in March 2025.
TARGET = "INV-00000001"


async def _read(client, inventory_id):
    """Return the stored record as the service reports it, or None if absent."""
    resp = await client.get("/inventory", params={"limit": 200})
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        if item["inventory_id"] == inventory_id:
            return item
    return None


async def _low_stock_ids(client):
    """Return the ids the low-stock view currently reports."""
    resp = await client.get("/inventory/low-stock", params={"limit": 200})
    assert resp.status_code == 200
    return {item["inventory_id"] for item in resp.json()["items"]}


# ---------------------------------------------------------------------------
# A patch body may name the on-hand count and the reorder point, and nothing
# else. An unsupported field is rejected, never quietly dropped -- a mutation
# that reports success while ignoring half of what it was asked to change is
# the failure this contract exists to prevent.
# ---------------------------------------------------------------------------


class TestPatchableFields:
    async def test_on_hand_only_body_is_accepted(self, wms_client):
        resp = await wms_client.patch(f"/inventory/{TARGET}", json={"quantity_on_hand": 450})
        assert resp.status_code == 200

        stored = await _read(wms_client, TARGET)
        assert stored["quantity_on_hand"] == 450

    async def test_reorder_point_only_body_is_accepted(self, wms_client):
        resp = await wms_client.patch(f"/inventory/{TARGET}", json={"reorder_point": 75})
        assert resp.status_code == 200

        stored = await _read(wms_client, TARGET)
        assert stored["reorder_point"] == 75

    async def test_both_fields_together_are_accepted(self, wms_client):
        resp = await wms_client.patch(
            f"/inventory/{TARGET}",
            json={"quantity_on_hand": 450, "reorder_point": 75},
        )
        assert resp.status_code == 200

        stored = await _read(wms_client, TARGET)
        assert stored["quantity_on_hand"] == 450
        assert stored["reorder_point"] == 75

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            # fields that really exist on the record but are not the caller's to set
            ("quantity_allocated", 5),
            ("sku", "SKU-Z999"),
            ("last_counted_at", "2030-01-01T00:00:00"),
            ("quantity_available", 999),
            ("product_name", "Renamed Widget"),
            # a field that exists nowhere -- a typo must not pass silently either
            ("bogus_field", 1),
        ],
    )
    async def test_unsupported_field_is_rejected_and_stores_nothing(self, wms_client, field, value):
        before = await _read(wms_client, TARGET)

        resp = await wms_client.patch(f"/inventory/{TARGET}", json={field: value})
        assert resp.status_code == 422

        assert await _read(wms_client, TARGET) == before

    async def test_unsupported_field_poisons_the_whole_body(self, wms_client):
        # A body that mixes a legal change with an illegal one is refused
        # outright; the legal half must not land on its own.
        before = await _read(wms_client, TARGET)

        resp = await wms_client.patch(
            f"/inventory/{TARGET}",
            json={"quantity_on_hand": 450, "sku": "SKU-Z999"},
        )
        assert resp.status_code == 422

        assert await _read(wms_client, TARGET) == before


# ---------------------------------------------------------------------------
# Availability is derived, never independent: it is always on hand minus
# allocated. Any accepted write has to leave that identity true, and no write
# may drive it below zero.
# ---------------------------------------------------------------------------


class TestDerivedAvailability:
    @pytest.mark.parametrize(
        "body",
        [
            {"quantity_on_hand": 450},
            {"quantity_on_hand": 620},
            {"reorder_point": 75},
            {"quantity_on_hand": 300, "reorder_point": 10},
            {},
        ],
        ids=["lower-on-hand", "raise-on-hand", "reorder-only", "both", "empty"],
    )
    async def test_availability_is_recomputed_after_every_accepted_patch(self, wms_client, body):
        resp = await wms_client.patch(f"/inventory/{TARGET}", json=body)
        assert resp.status_code == 200

        stored = await _read(wms_client, TARGET)
        on_hand, allocated = stored["quantity_on_hand"], stored["quantity_allocated"]
        assert stored["quantity_available"] == on_hand - allocated

    async def test_on_hand_below_allocated_is_rejected_and_stores_nothing(self, wms_client):
        # Allocated stock is already promised elsewhere, so an on-hand count
        # underneath it would leave negative availability.
        before = await _read(wms_client, TARGET)
        below_allocated = before["quantity_allocated"] - 1

        resp = await wms_client.patch(
            f"/inventory/{TARGET}", json={"quantity_on_hand": below_allocated}
        )
        assert resp.status_code == 422

        assert await _read(wms_client, TARGET) == before

    async def test_on_hand_exactly_at_allocated_is_accepted(self, wms_client):
        # Zero availability is a legal state; only negative availability is not.
        before = await _read(wms_client, TARGET)

        resp = await wms_client.patch(
            f"/inventory/{TARGET}",
            json={"quantity_on_hand": before["quantity_allocated"]},
        )
        assert resp.status_code == 200

        stored = await _read(wms_client, TARGET)
        assert stored["quantity_on_hand"] == before["quantity_allocated"]
        assert stored["quantity_available"] == 0

    @pytest.mark.parametrize(
        "body",
        [{"quantity_on_hand": -1}, {"reorder_point": -1}],
        ids=["negative-on-hand", "negative-reorder-point"],
    )
    async def test_negative_quantities_are_rejected_and_store_nothing(self, wms_client, body):
        before = await _read(wms_client, TARGET)

        resp = await wms_client.patch(f"/inventory/{TARGET}", json=body)
        assert resp.status_code == 422

        assert await _read(wms_client, TARGET) == before


# ---------------------------------------------------------------------------
# The id in the path selects the record. An id no record has is an error, not
# an invitation to create one.
# ---------------------------------------------------------------------------


class TestRecordAddressing:
    async def test_unknown_id_is_a_404_and_creates_nothing(self, wms_client):
        known = await wms_client.patch(f"/inventory/{TARGET}", json={"reorder_point": 42})
        assert known.status_code == 200

        missing = await wms_client.patch("/inventory/INV-99999999", json={"reorder_point": 42})
        assert missing.status_code == 404

        assert await _read(wms_client, "INV-99999999") is None


# ---------------------------------------------------------------------------
# `last_counted_at` records when stock was physically counted, not when the row
# was last touched. Only a patch that carries an on-hand count is a count, and
# the caller never supplies the timestamp -- the server stamps it.
# ---------------------------------------------------------------------------


class TestCountTimestamp:
    async def test_on_hand_patch_is_stamped_as_a_count(self, wms_client):
        before = await _read(wms_client, TARGET)

        resp = await wms_client.patch(f"/inventory/{TARGET}", json={"quantity_on_hand": 450})
        assert resp.status_code == 200

        stored = await _read(wms_client, TARGET)
        assert stored["last_counted_at"] != before["last_counted_at"]

    async def test_restating_the_same_on_hand_is_still_a_count(self, wms_client):
        # A recount that confirms the number already on file is a count too.
        before = await _read(wms_client, TARGET)

        resp = await wms_client.patch(
            f"/inventory/{TARGET}",
            json={"quantity_on_hand": before["quantity_on_hand"]},
        )
        assert resp.status_code == 200

        stored = await _read(wms_client, TARGET)
        assert stored["quantity_on_hand"] == before["quantity_on_hand"]
        assert stored["last_counted_at"] != before["last_counted_at"]

    async def test_reorder_point_change_is_not_a_count(self, wms_client):
        # Moving a reorder point is a policy decision; no stock was counted.
        before = await _read(wms_client, TARGET)

        resp = await wms_client.patch(f"/inventory/{TARGET}", json={"reorder_point": 75})
        assert resp.status_code == 200

        stored = await _read(wms_client, TARGET)
        assert stored["reorder_point"] == 75
        assert stored["last_counted_at"] == before["last_counted_at"]

    async def test_empty_body_changes_nothing_at_all(self, wms_client):
        # A patch naming no field is well formed and asks for nothing; it is
        # not a count either.
        before = await _read(wms_client, TARGET)

        resp = await wms_client.patch(f"/inventory/{TARGET}", json={})
        assert resp.status_code == 200

        assert await _read(wms_client, TARGET) == before


# ---------------------------------------------------------------------------
# The low-stock view reads the derived availability column, so a write that
# changes availability has to change what the view reports -- in both
# directions, and exactly at the reorder-point boundary.
# ---------------------------------------------------------------------------


class TestLowStockView:
    async def test_low_stock_membership_follows_patched_availability(self, wms_client):
        start = await _read(wms_client, TARGET)
        allocated = start["quantity_allocated"]
        reorder_point = start["reorder_point"]

        # availability starts comfortably above the reorder point
        assert TARGET not in await _low_stock_ids(wms_client)

        # one unit under the reorder point: the view must pick it up
        resp = await wms_client.patch(
            f"/inventory/{TARGET}",
            json={"quantity_on_hand": allocated + reorder_point - 1},
        )
        assert resp.status_code == 200
        assert TARGET in await _low_stock_ids(wms_client)

        # exactly at the reorder point counts as stocked, so it drops out again
        resp = await wms_client.patch(
            f"/inventory/{TARGET}",
            json={"quantity_on_hand": allocated + reorder_point},
        )
        assert resp.status_code == 200
        assert TARGET not in await _low_stock_ids(wms_client)


# ---------------------------------------------------------------------------
# The unified ops client can reach the endpoint, and reaches it the same way
# its sibling update methods reach theirs -- same warehouse service, same
# correlation headers, so a write is traceable exactly like a read.
# ---------------------------------------------------------------------------


class TestOpsClientReach:
    async def test_update_inventory_returns_the_updated_record(self, ops_client):
        listing = await ops_client.list_inventory()
        target = next(item for item in listing.items if item.inventory_id == TARGET)
        new_on_hand = target.quantity_on_hand - 50

        updated = await ops_client.update_inventory(TARGET, {"quantity_on_hand": new_on_hand})

        assert isinstance(updated, InventoryItem)
        assert updated.inventory_id == TARGET
        assert updated.quantity_on_hand == new_on_hand
        assert updated.quantity_available == new_on_hand - updated.quantity_allocated

        # the change is in the store, not just in the reply
        reread = await ops_client.list_inventory()
        stored = next(item for item in reread.items if item.inventory_id == TARGET)
        assert stored.quantity_on_hand == new_on_hand

    async def test_update_inventory_matches_its_siblings_on_the_wire(self, ops_client):
        inventory_payload = (await ops_client.list_inventory()).items[0].model_dump(mode="json")
        shipment_payload = (await ops_client.list_shipments()).items[0].model_dump(mode="json")

        calls: list[tuple[str, httpx.Request]] = []

        def recorder(service, payload):
            def handler(request: httpx.Request) -> httpx.Response:
                calls.append((service, request))
                return httpx.Response(200, json=payload)

            return handler

        new_trace()
        new_span()

        ops_client._tms = httpx.AsyncClient(
            transport=httpx.MockTransport(recorder("tms", shipment_payload)),
            base_url="http://tms",
        )
        ops_client._wms = httpx.AsyncClient(
            transport=httpx.MockTransport(recorder("wms", inventory_payload)),
            base_url="http://wms",
        )

        # a sibling update method sets the reference for what a mutation sends
        await ops_client.update_shipment(shipment_payload["shipment_id"], {"status": "delivered"})
        await ops_client.update_inventory(
            inventory_payload["inventory_id"], {"quantity_on_hand": 1}
        )

        sibling_calls = [request for service, request in calls if service == "tms"]
        assert len(sibling_calls) == 1

        inventory_calls = [(service, request) for service, request in calls if service == "wms"]
        assert len(inventory_calls) == 1
        service, request = inventory_calls[0]

        # it went to the warehouse service, as a PATCH, at the record's own path
        assert service == "wms"
        assert request.method == "PATCH"
        assert request.url.path == f"/inventory/{inventory_payload['inventory_id']}"

        # every correlation header the sibling sends is sent here too, unchanged
        reference = {
            name: value for name, value in sibling_calls[0].headers.items() if name.startswith("x-")
        }
        assert reference
        assert {name: request.headers.get(name) for name in reference} == reference
