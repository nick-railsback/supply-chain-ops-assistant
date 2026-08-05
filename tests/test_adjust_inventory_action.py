"""Adjusting an inventory record through the copilot's action pipeline.

An operator can restate a stock count or move a reorder point through the same
propose -> confirm -> execute path the other entities already use. These tests
pin that path from the outside: the action type that carries an adjustment, the
change fields a proposal may name, the risk floor that keeps every adjustment
behind a human gate, how inventory ids in a query and in a mixed context become
targets, what the warehouse record looks like afterwards, and what the operator
reads before saying yes.

Everything runs offline against the in-process warehouse service. Nothing here
consults a live model: the proposal path is pinned to its deterministic
rule-based branch for every test in this module.
"""

import io
import re
from unittest.mock import AsyncMock

import pytest
from rich.console import Console

from agent.action_handler import (
    PROPOSE_ACTION_SYSTEM_PROMPT,
    ActionNotConfirmedError,
    execute_action,
    format_proposal_summary,
    propose_action,
)
from agent.validators import _PATCHABLE_FIELDS, ID_PREFIX_ROUTING, validate_action_proposal
from cli.interactive import display_action_proposal
from config.settings import get_settings
from models.action import ActionProposal, ActionType
from models.shared import RiskLevel
from models.wms import InventoryItem, InventoryPatch
from services.client import OpsClient

# Inventory records the warehouse service under test starts with. INV-00000001
# holds 500 on hand / 100 allocated / 400 available, reorder point 50.
STORED_RECORD = "INV-00000001"
SECOND_STORED_RECORD = "INV-00000002"
UNTOUCHED_RECORD = "INV-00000003"

# The id spelling the seed data emits, used wherever a query names a record.
SEEDED_ID = "INV-000001"

# One id of every entity the pipeline can act on, so an action type can be
# exercised without knowing which entity it belongs to.
CANDIDATE_TARGETS = ("ORD-2025-0001", "EXC-0001", "SHP-20250301-00001", SEEDED_ID)

# A phrasing that asks, in plain words, for a stock count to be adjusted.
ADJUST_QUERY = "adjust inventory count for SKU-A100 to 450"

# The same ask with nothing singled out -- no SKU, no center, no id.
BROAD_ADJUST_QUERY = "adjust inventory counts"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Pin every test in this module to the offline, rule-based proposal path."""
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_enabled", False)
    monkeypatch.setattr(settings, "anthropic_api_key", "not-set")
    assert not settings.is_llm_available


def _adjust_inventory() -> ActionType:
    """The action type an inventory adjustment travels under."""
    try:
        return ActionType("adjust_inventory")
    except ValueError:
        pytest.fail(
            "no action type carries an inventory adjustment; "
            f"the pipeline knows only {[t.value for t in ActionType]}"
        )


def _proposal(
    action_type,
    target_ids,
    changes,
    *,
    risk_level=RiskLevel.MEDIUM,
    requires_confirmation=True,
) -> ActionProposal:
    """A proposal built by hand, i.e. outside the proposal reasoner."""
    return ActionProposal(
        action_type=action_type,
        target_ids=list(target_ids),
        changes=dict(changes),
        reasoning="test proposal",
        impact_summary="test impact",
        risk_level=risk_level,
        requires_confirmation=requires_confirmation,
    )


def _inventory_rows(count, changes=None):
    """Context rows as an inventory query returns them, in ascending id order.

    Order is load-bearing: the rule path reads the requested change off the
    first row, so ``rows[0]`` is INV-000001.
    """
    rows = [
        {
            "inventory_id": f"INV-{i:06d}",
            "sku": f"SKU-{i:04d}",
            "quantity_on_hand": 100 + i,
            "reorder_point": 20,
        }
        for i in range(1, count + 1)
    ]
    if changes is not None:
        # The rule path reads the requested change off the first context row.
        rows[0]["changes"] = changes
    return rows


# Context rows shaped like the warehouse's own: the same SKU stocked at two
# centers, so naming one without the other is a real narrowing.
_WAREHOUSE_ROWS = [
    {
        "inventory_id": "INV-000001",
        "sku": "SKU-A100",
        "fulfillment_center_id": "FC-EAST",
        # The rule path takes its change off the first context row.
        "changes": {"quantity_on_hand": 450},
    },
    {"inventory_id": "INV-000002", "sku": "SKU-B200", "fulfillment_center_id": "FC-EAST"},
    {"inventory_id": "INV-000003", "sku": "SKU-C300", "fulfillment_center_id": "FC-WEST"},
    {"inventory_id": "INV-000004", "sku": "SKU-D400", "fulfillment_center_id": "FC-WEST"},
    {"inventory_id": "INV-000005", "sku": "SKU-A100", "fulfillment_center_id": "FC-WEST"},
]


def _render(renderable) -> str:
    """The text a console would actually show for a Rich renderable."""
    console = Console(file=io.StringIO(), width=140)
    console.print(renderable)
    return console.file.getvalue()


async def _stored(ops_client):
    """Every inventory record the service holds, keyed by id."""
    listing = await ops_client.list_inventory(limit=200)
    return {item.inventory_id: item.model_dump(mode="json") for item in listing.items}


def _collapse(text):
    """Whitespace-insensitive view of hand-wrapped prose."""
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Routing: an inventory adjustment is a first-class action, and no action type
# is a dead letter -- every one of them reaches a backend call rather than
# falling off the end of the dispatcher.
# ---------------------------------------------------------------------------


class TestActionTypeRouting:
    def test_an_inventory_adjustment_has_an_action_type(self):
        assert "adjust_inventory" in {t.value for t in ActionType}

    async def test_every_action_type_reaches_a_backend_call(self):
        # Iterated over the enum rather than a hand-written list, so a type
        # added later cannot be unroutable.
        _adjust_inventory()

        for action_type in ActionType:
            reached = False
            for target in CANDIDATE_TARGETS:
                client = AsyncMock()
                # The dispatcher routes; it does not judge field names. Any
                # change will do, so long as there is one -- a changeless
                # request is refused before it reaches a backend at all.
                result = await execute_action(
                    client, _proposal(action_type, [target], {"a_field": "a value"}), confirmed=True
                )
                unsupported = [
                    failure
                    for failure in result.failed
                    if "unsupported action type" in failure["error"].lower()
                ]
                assert not unsupported, f"{action_type.value} is not dispatchable: {unsupported}"
                if not result.failed and client.mock_calls:
                    reached = True
            assert reached, f"{action_type.value} never reached a backend call"


# ---------------------------------------------------------------------------
# Patch-contract derivation: the change fields an adjustment may name are
# exactly the fields the inventory PATCH contract accepts -- read off the
# models, never hand-listed, so the contract and the validator cannot drift.
# Anything else is refused while the proposal is still a proposal.
# ---------------------------------------------------------------------------


PATCHABLE = sorted(InventoryPatch.model_fields)
NOT_PATCHABLE = sorted(set(InventoryItem.model_fields) - set(InventoryPatch.model_fields))


class TestChangeFieldsFollowThePatchContract:
    @pytest.mark.parametrize("field", PATCHABLE)
    async def test_a_field_the_contract_accepts_validates_clean(self, field):
        proposal = _proposal(_adjust_inventory(), [SEEDED_ID], {field: 1})
        assert await validate_action_proposal(proposal) == []

    async def test_the_whole_contract_at_once_validates_clean(self):
        changes = dict.fromkeys(PATCHABLE, 1)
        proposal = _proposal(_adjust_inventory(), [SEEDED_ID], changes)
        assert await validate_action_proposal(proposal) == []

    @pytest.mark.parametrize("field", NOT_PATCHABLE)
    async def test_a_record_field_outside_the_contract_is_named_and_refused(self, field):
        proposal = _proposal(_adjust_inventory(), [SEEDED_ID], {field: 1})
        errors = await validate_action_proposal(proposal)
        assert any(field in error for error in errors), (
            f"'{field}' is not part of the inventory PATCH contract but was "
            f"accepted on an adjustment proposal; errors: {errors}"
        )

    async def test_a_field_no_record_has_is_refused_too(self):
        proposal = _proposal(_adjust_inventory(), [SEEDED_ID], {"bogus_field": 1})
        errors = await validate_action_proposal(proposal)
        assert any("bogus_field" in error for error in errors)

    async def test_a_legal_change_beside_an_illegal_one_does_not_rescue_it(self):
        changes = dict.fromkeys(PATCHABLE, 1) | {"quantity_allocated": 5}
        proposal = _proposal(_adjust_inventory(), [SEEDED_ID], changes)
        errors = await validate_action_proposal(proposal)
        assert any("quantity_allocated" in error for error in errors)

    async def test_the_accepted_and_refused_sets_are_read_off_the_models(self):
        # Guards the two parametrised tests above against becoming vacuous: a
        # contract that accepted nothing, or a record with no unpatchable
        # field, would silently generate no cases at all.
        adjust = _adjust_inventory()
        assert PATCHABLE, "the inventory PATCH contract accepts no field at all"
        assert NOT_PATCHABLE, "every inventory record field is patchable"

        accepted = {
            field
            for field in InventoryItem.model_fields
            if not await validate_action_proposal(_proposal(adjust, [SEEDED_ID], {field: 1}))
        }
        assert accepted == set(PATCHABLE)

    async def test_a_refused_change_never_reaches_the_warehouse(self, ops_client):
        before = await _stored(ops_client)

        rows = _inventory_rows(1, changes={"quantity_allocated": 5})
        with pytest.raises(ValueError, match="quantity_allocated"):
            await propose_action(ops_client, ADJUST_QUERY, rows)

        assert await _stored(ops_client) == before


# ---------------------------------------------------------------------------
# Risk floor: restating a physical count is never routine. Every adjustment is
# graded at least medium and always requires a human to approve it, however few
# records it touches and whichever field it moves.
# ---------------------------------------------------------------------------


class TestRiskFloor:
    async def test_a_single_count_change_is_medium_and_gated(self):
        rows = _inventory_rows(1, changes={"quantity_on_hand": 450})
        proposal = await propose_action(None, ADJUST_QUERY, rows)

        assert proposal.risk_level == RiskLevel.MEDIUM
        assert proposal.requires_confirmation is True

    async def test_a_reorder_point_change_alone_is_medium_and_gated(self):
        rows = _inventory_rows(1, changes={"reorder_point": 25})
        proposal = await propose_action(None, ADJUST_QUERY, rows)

        assert proposal.risk_level == RiskLevel.MEDIUM
        assert proposal.requires_confirmation is True

    async def test_more_than_ten_records_is_high(self):
        rows = _inventory_rows(11, changes={"quantity_on_hand": 450})
        proposal = await propose_action(None, ADJUST_QUERY, rows)

        assert len(proposal.target_ids) == 11
        assert proposal.risk_level == RiskLevel.HIGH
        assert proposal.requires_confirmation is True

    @pytest.mark.parametrize("record_count", [1, 2, 5, 6, 11])
    @pytest.mark.parametrize(
        "changes",
        [{"quantity_on_hand": 450}, {"reorder_point": 25}],
        ids=["on-hand", "reorder-point"],
    )
    async def test_no_adjustment_is_ever_graded_low(self, record_count, changes):
        rows = _inventory_rows(record_count, changes=changes)
        proposal = await propose_action(None, ADJUST_QUERY, rows)

        assert proposal.risk_level != RiskLevel.LOW
        assert proposal.requires_confirmation is True


# ---------------------------------------------------------------------------
# An adjustment that names no change is a no-op wearing a success message. The
# operator reads "adjusted" and the count on the shelf never moved, so the
# pipeline refuses it -- while proposing, and again at the write itself, since
# a proposal can be built anywhere.
# ---------------------------------------------------------------------------


class TestAnAdjustmentAlwaysCarriesAChange:
    async def test_warehouse_rows_as_the_copilot_fetches_them_propose_no_no_op(self, ops_client):
        # The rows a query really puts in front of the reasoner: inventory
        # records dumped straight off the service, carrying no requested change.
        listing = await ops_client.list_inventory(limit=200)
        rows = [item.model_dump(mode="json") for item in listing.items]
        assert rows, "the warehouse under test holds no inventory to adjust"

        with pytest.raises(ValueError) as raised:
            await propose_action(ops_client, ADJUST_QUERY, rows)

        # The operator has to learn what was missing, not just that it failed.
        assert "change" in str(raised.value).lower()

    async def test_an_adjustment_naming_no_change_is_refused_while_still_a_proposal(self):
        proposal = _proposal(_adjust_inventory(), [SEEDED_ID], {})

        errors = await validate_action_proposal(proposal)

        assert errors, "an adjustment that changes nothing was accepted as a proposal"

    async def test_a_changeless_adjustment_is_never_reported_as_a_success(self, ops_client):
        proposal = _proposal(_adjust_inventory(), [STORED_RECORD], {})
        before = await _stored(ops_client)

        result = await execute_action(ops_client, proposal, confirmed=True)

        assert await _stored(ops_client) == before
        assert result.successful == [], (
            "the operator was told an adjustment landed on "
            f"{result.successful} while the record never moved"
        )


# ---------------------------------------------------------------------------
# Confirmation gate: the floor is recomputed at the mutation boundary, so a
# proposal that arrives claiming to need no approval is refused anyway -- and
# refused before anything is written, not halfway through.
# ---------------------------------------------------------------------------


class TestConfirmationGate:
    async def test_an_unconfirmed_adjustment_is_refused_and_writes_nothing(self, ops_client):
        targets = [STORED_RECORD, SECOND_STORED_RECORD]
        proposal = _proposal(_adjust_inventory(), targets, {"quantity_on_hand": 450})
        before = await _stored(ops_client)

        with pytest.raises(ActionNotConfirmedError):
            await execute_action(ops_client, proposal)

        assert await _stored(ops_client) == before

    async def test_a_proposal_built_with_a_lowered_gate_is_refused_anyway(self, ops_client):
        targets = [STORED_RECORD, SECOND_STORED_RECORD]
        proposal = _proposal(
            _adjust_inventory(),
            targets,
            {"quantity_on_hand": 450},
            risk_level=RiskLevel.LOW,
            requires_confirmation=False,
        )
        before = await _stored(ops_client)

        with pytest.raises(ActionNotConfirmedError):
            await execute_action(ops_client, proposal)

        assert await _stored(ops_client) == before

    async def test_a_gate_lowered_after_construction_is_refused_anyway(self, ops_client):
        proposal = _proposal(_adjust_inventory(), [STORED_RECORD], {"quantity_on_hand": 450})
        proposal.risk_level = RiskLevel.LOW
        proposal.requires_confirmation = False
        before = await _stored(ops_client)

        with pytest.raises(ActionNotConfirmedError):
            await execute_action(ops_client, proposal)

        assert await _stored(ops_client) == before


# ---------------------------------------------------------------------------
# Execution: a confirmed adjustment lands on the record itself. Observed by
# re-reading the warehouse service, so the guarantees the write path owes --
# availability derived from what is really there, a count timestamp that means
# a count -- are watched through this path rather than assumed.
# ---------------------------------------------------------------------------


class TestConfirmedExecutionReachesTheRecord:
    async def test_every_target_is_patched_and_reported(self, ops_client):
        targets = [STORED_RECORD, SECOND_STORED_RECORD]
        proposal = _proposal(_adjust_inventory(), targets, {"quantity_on_hand": 450})
        before = await _stored(ops_client)

        result = await execute_action(ops_client, proposal, confirmed=True)

        assert result.failed == []
        assert result.successful == targets
        assert result.total_targets == len(targets)

        after = await _stored(ops_client)
        for target in targets:
            assert after[target]["quantity_on_hand"] == 450
            # availability follows the counts, it is not a number of its own
            assert (
                after[target]["quantity_available"]
                == after[target]["quantity_on_hand"] - after[target]["quantity_allocated"]
            )
            # a restated on-hand count is a count: the record says when
            assert after[target]["last_counted_at"] != before[target]["last_counted_at"]

    async def test_records_outside_the_proposal_are_left_alone(self, ops_client):
        proposal = _proposal(_adjust_inventory(), [STORED_RECORD], {"quantity_on_hand": 450})
        before = await _stored(ops_client)

        await execute_action(ops_client, proposal, confirmed=True)

        after = await _stored(ops_client)
        assert after[UNTOUCHED_RECORD] == before[UNTOUCHED_RECORD]

    async def test_a_reorder_point_move_is_not_recorded_as_a_count(self, ops_client):
        proposal = _proposal(_adjust_inventory(), [STORED_RECORD], {"reorder_point": 75})
        before = await _stored(ops_client)

        result = await execute_action(ops_client, proposal, confirmed=True)

        assert result.failed == []
        after = await _stored(ops_client)
        assert after[STORED_RECORD]["reorder_point"] == 75
        assert after[STORED_RECORD]["last_counted_at"] == before[STORED_RECORD]["last_counted_at"]


# ---------------------------------------------------------------------------
# Targeting: a record named in the request is the record acted on, and only if
# it was actually fetched. A request never fans out across everything that came
# back with it, and never crosses into another entity's rows.
# ---------------------------------------------------------------------------


class TestTargeting:
    async def test_an_id_in_the_request_is_intersected_with_the_context(self):
        rows = _inventory_rows(3, changes={"quantity_on_hand": 450})

        named = await propose_action(None, f"adjust inventory count for {SEEDED_ID} to 450", rows)
        assert named.target_ids == [SEEDED_ID]

        # an id that was never fetched is no target at all, not a licence to
        # act on everything that was
        with pytest.raises(ValueError, match="at least one target_id"):
            await propose_action(None, "adjust inventory count for INV-000099 to 450", rows)

    async def test_only_inventory_rows_of_a_mixed_context_become_targets(self):
        rows = [
            {
                "order_id": "ORD-2025-0001",
                "status": "pending",
                # The rule path takes its change off the first context row.
                "changes": {"quantity_on_hand": 450},
            },
            {"inventory_id": "INV-000001", "sku": "SKU-A100"},
            {"exception_id": "EXC-0001", "status": "open"},
            {"inventory_id": "INV-000002", "sku": "SKU-B200"},
            {"shipment_id": "SHP-20250301-00001", "status": "in_transit"},
        ]

        proposal = await propose_action(None, BROAD_ADJUST_QUERY, rows)

        assert proposal.target_ids == ["INV-000001", "INV-000002"]

    async def test_the_sku_and_center_in_the_request_narrow_it(self):
        # No surface ever shows an operator an INV id, so a stock count is
        # named by the SKU and the center on the inventory table. Those have
        # to narrow it, or every row the plan returned becomes a target.
        proposal = await propose_action(None, "recount SKU-A100 at FC-WEST", _WAREHOUSE_ROWS)

        assert proposal.target_ids == ["INV-000005"]

    async def test_naming_only_a_sku_keeps_every_center_holding_it(self):
        proposal = await propose_action(None, "recount SKU-A100", _WAREHOUSE_ROWS)

        assert proposal.target_ids == ["INV-000001", "INV-000005"]

    async def test_naming_only_a_center_keeps_everything_it_holds(self):
        proposal = await propose_action(None, "recount everything at FC-WEST", _WAREHOUSE_ROWS)

        assert proposal.target_ids == ["INV-000003", "INV-000004", "INV-000005"]

    async def test_a_request_naming_neither_still_covers_the_context(self):
        # Narrowing is an escape hatch, not a new requirement: a request that
        # singles nothing out still means everything that was fetched.
        proposal = await propose_action(None, BROAD_ADJUST_QUERY, _WAREHOUSE_ROWS)

        assert proposal.target_ids == [row["inventory_id"] for row in _WAREHOUSE_ROWS]

    async def test_a_named_sku_narrows_a_full_page_of_records_to_one(self):
        # The shape of the reported failure: a plan that fetched a page of
        # inventory must not turn a request naming one SKU into a 50-record
        # mutation the operator cannot check.
        rows = [
            {
                "inventory_id": f"INV-{i:06d}",
                "sku": f"SKU-{i:04d}",
                "fulfillment_center_id": "FC-WEST",
            }
            for i in range(1, 51)
        ]
        rows[0]["changes"] = {"quantity_on_hand": 450}

        proposal = await propose_action(None, "recount SKU-0037 at FC-WEST", rows)

        assert proposal.target_ids == ["INV-000037"]


# ---------------------------------------------------------------------------
# Recognition: asking in plain words for a stock count to be adjusted is read
# as an inventory adjustment -- not as the catch-all bulk change, and not
# swallowed by the greediest keyword list in the set.
# ---------------------------------------------------------------------------


class TestRequestRecognition:
    @pytest.mark.parametrize(
        "query",
        [
            "adjust inventory count for SKU-A100 to 450",
            "update the inventory count for SKU-A100 to 450",
        ],
    )
    async def test_a_count_adjustment_request_is_read_as_one(self, query):
        rows = _inventory_rows(1, changes={"quantity_on_hand": 450})

        proposal = await propose_action(None, query, rows)

        assert proposal.action_type == _adjust_inventory()
        assert proposal.action_type != ActionType.BULK_UPDATE
        assert proposal.action_type != ActionType.ESCALATE_ORDER

    @pytest.mark.parametrize(
        "query",
        [
            "urgent: adjust inventory count for SKU-A100 to 450",
            "recount SKU-A100, it's a priority",
            "urgent inventory recount at FC-EAST",
        ],
    )
    async def test_saying_it_is_urgent_does_not_make_it_an_escalation(self, query):
        # "urgent" and "priority" say how soon, not what to do. An operator in
        # a hurry still gets the adjustment they asked for -- not an order
        # escalation, and not a validation error for naming no order.
        rows = _inventory_rows(1, changes={"quantity_on_hand": 450})

        proposal = await propose_action(None, query, rows)

        assert proposal.action_type == _adjust_inventory()


# ---------------------------------------------------------------------------
# Bulk routing: a bulk change either handles inventory targets on both sides --
# its changes checked against the inventory contract and its targets dispatched
# to the inventory record -- or on neither. Checking nothing and then failing to
# route is the one combination ruled out, because the failure lands after the
# operator has already approved it.
# ---------------------------------------------------------------------------


class TestBulkInventoryTargets:
    async def test_every_prefix_the_validator_routes_by_is_one_the_dispatcher_can_write(self):
        # Iterated over the routing map rather than a hand-written list, so an
        # entity registered later cannot validate against a contract and then
        # fail to route -- the failure the operator only sees after approving.
        assert ID_PREFIX_ROUTING, "no id prefix routes anywhere at all"

        for prefix, (entity, method) in ID_PREFIX_ROUTING.items():
            # Against the real class, not the mock below: a mock answers to any
            # method name, so only this catches one that does not exist.
            assert hasattr(OpsClient, method), (
                f"{prefix} routes to OpsClient.{method}, which does not exist"
            )
            assert entity in _PATCHABLE_FIELDS, (
                f"{prefix} routes to entity '{entity}', which has no PATCH contract"
            )

            client = AsyncMock()
            result = await execute_action(
                client,
                _proposal(ActionType.BULK_UPDATE, [f"{prefix}-0001"], {"a_field": "a value"}),
                confirmed=True,
            )

            assert result.failed == [], (
                f"the validator routes {prefix} to {entity}, but the dispatcher "
                f"cannot write it: {result.failed}"
            )
            assert getattr(client, method).await_count == 1, (
                f"{prefix} was routed somewhere other than OpsClient.{method}"
            )

    async def test_a_bulk_inventory_change_is_checked_against_the_contract(self):
        proposal = _proposal(ActionType.BULK_UPDATE, [STORED_RECORD], {"quantity_allocated": 5})

        errors = await validate_action_proposal(proposal)

        assert errors, (
            "a bulk change naming an inventory target had its changes checked "
            "against nothing at all"
        )
        # Either resolution is legible: the change is named as one inventory
        # cannot accept, or the target itself is named as one bulk won't carry.
        assert any("quantity_allocated" in e or "INV" in e for e in errors)

    async def test_a_bulk_change_reaching_one_inventory_record_is_still_gated(self):
        # The same mutation under a different label. Relabelling an adjustment
        # as a bulk change must not buy it a lower gate.
        rows = _inventory_rows(1, changes={"quantity_on_hand": 0})

        proposal = await propose_action(None, "bulk update stock levels", rows)

        assert proposal.action_type == ActionType.BULK_UPDATE
        assert proposal.risk_level == RiskLevel.MEDIUM
        assert proposal.requires_confirmation is True

    async def test_an_unconfirmed_bulk_change_to_inventory_writes_nothing(self, ops_client):
        # A change the warehouse would accept, so what stops it is the gate.
        proposal = _proposal(
            ActionType.BULK_UPDATE,
            [STORED_RECORD],
            {"quantity_on_hand": 450},
            risk_level=RiskLevel.LOW,
            requires_confirmation=False,
        )
        before = await _stored(ops_client)

        with pytest.raises(ActionNotConfirmedError):
            await execute_action(ops_client, proposal)

        assert await _stored(ops_client) == before

    async def test_what_the_validator_admits_is_what_the_dispatcher_routes(self, ops_client):
        proposal = _proposal(ActionType.BULK_UPDATE, [STORED_RECORD], {"quantity_on_hand": 450})

        admitted = await validate_action_proposal(proposal) == []

        before = await _stored(ops_client)
        result = await execute_action(ops_client, proposal, confirmed=True)
        after = await _stored(ops_client)
        routed = not result.failed and after[STORED_RECORD] != before[STORED_RECORD]

        assert admitted == routed, (
            "a bulk change with an inventory target is admitted by the change "
            f"validator ({admitted}) but reaches the record ({routed}); the "
            "operator confirms a change that then cannot be applied"
        )


# ---------------------------------------------------------------------------
# What the model is told: every action the pipeline can take is named to the
# model by the value it must emit, and the risk floor the prompt states is the
# floor the server actually applies -- including the one that puts an inventory
# adjustment behind a human gate no matter how small it is.
# ---------------------------------------------------------------------------


class TestModelFacingPrompt:
    def test_every_action_type_is_named_to_the_model(self):
        # Iterated over the enum, so a type added later cannot stay invisible.
        _adjust_inventory()
        prompt = _collapse(PROPOSE_ACTION_SYSTEM_PROMPT)

        missing = [t.value for t in ActionType if t.value not in prompt]
        assert not missing, f"action types the model is never shown: {missing}"

    def test_the_model_is_told_an_on_hand_value_replaces_the_count(self):
        # "adjust", "recount" and "adjust stock" all sound like a delta, and
        # the service applies quantity_on_hand as an absolute set. A model that
        # reads "add 50 units" and emits 50 turns a replenishment into a
        # write-off the operator cannot distinguish from an intended count.
        prompt = _collapse(PROPOSE_ACTION_SYSTEM_PROMPT)

        assert "quantity_on_hand" in prompt, (
            "the model is never told the name of the field it sets on an inventory record"
        )
        assert re.search(
            r"quantity_on_hand\b[^.]*\b(absolute|replaces|resulting|new total|not a delta)\b",
            prompt,
            re.IGNORECASE,
        ), f"the model is not told quantity_on_hand is absolute rather than a delta: {prompt}"

    def test_the_stated_floor_names_the_inventory_case(self):
        heading = re.search(r"#\s*Risk\b", PROPOSE_ACTION_SYSTEM_PROMPT)
        assert heading, "the proposal prompt no longer states a risk floor"

        # Collapsed first: the floor is hand-wrapped prose, and a sentence that
        # rewraps across lines has not changed meaning.
        floor = _collapse(PROPOSE_ACTION_SYSTEM_PROMPT[heading.end() :])
        medium = re.search(r"MEDIUM\b(.*?)(?=HIGH\b|$)", floor)
        assert medium, f"the stated floor has no medium band: {floor}"

        assert re.search(r"inventory", medium.group(1), re.IGNORECASE), (
            "the medium band of the stated risk floor does not name the "
            f"inventory adjustment it enforces: {medium.group(1)!r}"
        )


# ---------------------------------------------------------------------------
# What the operator reads: the summary shown before confirming names what is
# about to change in the operator's own words, not a generic placeholder.
# ---------------------------------------------------------------------------


class TestConfirmationSummary:
    def test_a_single_record_is_named_as_one(self):
        proposal = _proposal(_adjust_inventory(), [SEEDED_ID], {"quantity_on_hand": 450})

        summary = format_proposal_summary(proposal)

        assert "Targets: 1 inventory record" in summary
        assert "entity" not in summary

    def test_several_records_are_named_as_records(self):
        targets = ["INV-000001", "INV-000002", "INV-000003"]
        proposal = _proposal(_adjust_inventory(), targets, {"quantity_on_hand": 450})

        summary = format_proposal_summary(proposal)

        assert "Targets: 3 inventory records" in summary
        assert "entities" not in summary

    async def test_the_panel_says_which_records_in_words_the_operator_knows(self):
        # An INV id identifies nothing to the person approving the change --
        # they have never seen one. The panel has to say which SKU at which
        # center, or the gate is a wall of opaque ids nobody can check.
        proposal = await propose_action(None, "recount everything at FC-WEST", _WAREHOUSE_ROWS)

        panel = _render(display_action_proposal(proposal))

        for row in _WAREHOUSE_ROWS:
            if row["fulfillment_center_id"] != "FC-WEST":
                continue
            assert row["inventory_id"] in panel
            assert row["sku"] in panel, f"{row['inventory_id']} is shown with no SKU: {panel}"
        assert "FC-WEST" in panel

    async def test_a_record_the_context_cannot_label_is_still_listed(self):
        # A target with no row behind it must not vanish from the panel.
        proposal = _proposal(_adjust_inventory(), [SEEDED_ID], {"quantity_on_hand": 450})

        panel = _render(display_action_proposal(proposal))

        assert SEEDED_ID in panel
