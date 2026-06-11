"""Shared pytest fixtures for test databases and mock clients."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.action import ActionProposal, ActionType
from models.query import QueryPlan
from models.report import ReportOutput, ReportSection
from models.shared import RiskLevel, TargetSystem, UserIntent


@pytest.fixture
def sample_query_plan():
    """Factory for QueryPlan objects."""

    def _make(
        intent=UserIntent.STATUS_CHECK,
        target_systems=None,
        confidence=0.85,
        **kwargs,
    ):
        filters = kwargs.pop("filters", [])
        primary_entity = kwargs.pop("primary_entity", "orders")
        return QueryPlan(
            intent=intent,
            target_systems=target_systems or [TargetSystem.OMS],
            primary_entity=primary_entity,
            filters=filters,
            confidence=confidence,
            reasoning="Test query plan",
            **kwargs,
        )

    return _make


@pytest.fixture
def sample_action_proposal():
    """Factory for ActionProposal objects."""

    def _make(
        action_type=ActionType.UPDATE_EXCEPTION,
        target_ids=None,
        risk_level=RiskLevel.LOW,
        **kwargs,
    ):
        return ActionProposal(
            action_type=action_type,
            target_ids=target_ids or ["EXC-0001"],
            changes={"status": "resolved"},
            reasoning="Test action",
            impact_summary="Test impact",
            risk_level=risk_level,
            **kwargs,
        )

    return _make


@pytest.fixture
def sample_report_output():
    """Factory for ReportOutput objects."""

    def _make(**kwargs):
        return ReportOutput(
            report_type="exception_summary",
            title="Test Report",
            generated_at=datetime.now(UTC),
            sections=[
                ReportSection(
                    title="Test Section",
                    content="Test content",
                )
            ],
            action_items=["Review open exceptions"],
            **kwargs,
        )

    return _make


# ---------------------------------------------------------------------------
# OMS integration fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def oms_app():
    """Create OMS FastAPI app backed by in-memory SQLite."""
    from services.oms_api import (
        Base as OMSBase,
        LineItemORM,
        OrderExceptionORM,
        OrderORM,
        app as _oms_app,
        get_session as oms_get_session,
    )

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(OMSBase.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        # Seed 5 orders
        orders = [
            OrderORM(
                order_id="ORD-2025-001",
                customer_id="CUST-001",
                customer_name="Alice Smith",
                customer_email="alice@example.com",
                customer_tier="premium",
                status="pending",
                channel="dtc_web",
                created_at="2025-03-01T10:00:00",
                updated_at="2025-03-01T10:00:00",
                promised_delivery_date="2025-03-10T10:00:00",
                fulfillment_center_id="FC-EAST",
                total_value=150.00,
                currency="USD",
                line_item_count=2,
                notes=None,
            ),
            OrderORM(
                order_id="ORD-2025-002",
                customer_id="CUST-002",
                customer_name="Bob Jones",
                customer_email="bob@example.com",
                customer_tier="standard",
                status="pending",
                channel="dtc_web",
                created_at="2025-03-02T10:00:00",
                updated_at="2025-03-02T10:00:00",
                promised_delivery_date="2025-03-12T10:00:00",
                fulfillment_center_id="FC-WEST",
                total_value=200.00,
                currency="USD",
                line_item_count=1,
                notes=None,
            ),
            OrderORM(
                order_id="ORD-2025-003",
                customer_id="CUST-003",
                customer_name="Carol White",
                customer_email="carol@example.com",
                customer_tier="enterprise",
                status="processing",
                channel="wholesale_b2b",
                created_at="2025-03-03T10:00:00",
                updated_at="2025-03-03T10:00:00",
                promised_delivery_date="2025-03-15T10:00:00",
                fulfillment_center_id="FC-EAST",
                total_value=500.00,
                currency="USD",
                line_item_count=3,
                notes=None,
            ),
            OrderORM(
                order_id="ORD-2025-004",
                customer_id="CUST-004",
                customer_name="Dave Brown",
                customer_email="dave@example.com",
                customer_tier="premium",
                status="shipped",
                channel="dtc_web",
                created_at="2025-03-04T10:00:00",
                updated_at="2025-03-04T10:00:00",
                promised_delivery_date="2025-03-14T10:00:00",
                fulfillment_center_id="FC-WEST",
                total_value=300.00,
                currency="USD",
                line_item_count=2,
                notes=None,
            ),
            OrderORM(
                order_id="ORD-2025-005",
                customer_id="CUST-005",
                customer_name="Eve Davis",
                customer_email="eve@example.com",
                customer_tier="standard",
                status="delivered",
                channel="wholesale_b2b",
                created_at="2025-03-05T10:00:00",
                updated_at="2025-03-05T10:00:00",
                promised_delivery_date="2025-03-13T10:00:00",
                fulfillment_center_id="FC-EAST",
                total_value=100.00,
                currency="USD",
                line_item_count=1,
                notes=None,
            ),
            # Active order promised inside the at-risk window [now, now+2d]; the
            # other rows carry fixed March-2025 dates, so this is the only row
            # the /orders/at-risk endpoint can return.
            OrderORM(
                order_id="ORD-2025-006",
                customer_id="CUST-006",
                customer_name="Frank Miller",
                customer_email="frank@example.com",
                customer_tier="premium",
                status="processing",
                channel="dtc_web",
                created_at=datetime.now(UTC).isoformat(),
                updated_at=datetime.now(UTC).isoformat(),
                promised_delivery_date=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
                fulfillment_center_id="FC-EAST",
                total_value=250.00,
                currency="USD",
                line_item_count=1,
                notes=None,
            ),
        ]
        session.add_all(orders)

        # Seed line items
        line_items = [
            LineItemORM(
                line_item_id="LI-00000001",
                order_id="ORD-2025-001",
                sku="SKU-A100",
                product_name="Widget A",
                quantity=2,
                unit_price=50.00,
                status="pending",
            ),
            LineItemORM(
                line_item_id="LI-00000002",
                order_id="ORD-2025-001",
                sku="SKU-B200",
                product_name="Widget B",
                quantity=1,
                unit_price=50.00,
                status="pending",
            ),
            LineItemORM(
                line_item_id="LI-00000003",
                order_id="ORD-2025-002",
                sku="SKU-A100",
                product_name="Widget A",
                quantity=1,
                unit_price=200.00,
                status="pending",
            ),
            LineItemORM(
                line_item_id="LI-00000004",
                order_id="ORD-2025-003",
                sku="SKU-C300",
                product_name="Widget C",
                quantity=3,
                unit_price=100.00,
                status="allocated",
            ),
            LineItemORM(
                line_item_id="LI-00000005",
                order_id="ORD-2025-003",
                sku="SKU-A100",
                product_name="Widget A",
                quantity=1,
                unit_price=100.00,
                status="allocated",
            ),
            LineItemORM(
                line_item_id="LI-00000006",
                order_id="ORD-2025-003",
                sku="SKU-B200",
                product_name="Widget B",
                quantity=1,
                unit_price=100.00,
                status="picked",
            ),
            LineItemORM(
                line_item_id="LI-00000007",
                order_id="ORD-2025-004",
                sku="SKU-A100",
                product_name="Widget A",
                quantity=2,
                unit_price=100.00,
                status="shipped",
            ),
            LineItemORM(
                line_item_id="LI-00000008",
                order_id="ORD-2025-004",
                sku="SKU-D400",
                product_name="Widget D",
                quantity=1,
                unit_price=100.00,
                status="shipped",
            ),
            LineItemORM(
                line_item_id="LI-00000009",
                order_id="ORD-2025-005",
                sku="SKU-B200",
                product_name="Widget B",
                quantity=1,
                unit_price=100.00,
                status="delivered",
            ),
        ]
        session.add_all(line_items)

        # Seed 3 exceptions
        exceptions = [
            OrderExceptionORM(
                exception_id="EXC-001",
                order_id="ORD-2025-001",
                exception_type="payment_failed",
                severity="critical",
                status="open",
                created_at="2025-03-01T12:00:00",
                resolved_at=None,
                description="Payment processing failed for order ORD-2025-001",
                assigned_to=None,
            ),
            OrderExceptionORM(
                exception_id="EXC-002",
                order_id="ORD-2025-002",
                exception_type="address_invalid",
                severity="high",
                status="open",
                created_at="2025-03-02T14:00:00",
                resolved_at=None,
                description="Invalid shipping address for order ORD-2025-002",
                assigned_to=None,
            ),
            OrderExceptionORM(
                exception_id="EXC-003",
                order_id="ORD-2025-003",
                exception_type="item_backordered",
                severity="low",
                status="resolved",
                created_at="2025-03-03T09:00:00",
                resolved_at="2025-03-04T09:00:00",
                description="Item backordered for order ORD-2025-003",
                assigned_to="ops-team",
            ),
        ]
        session.add_all(exceptions)
        await session.commit()

    async def _override_get_session():
        async with session_factory() as session:
            yield session

    _oms_app.dependency_overrides[oms_get_session] = _override_get_session

    yield _oms_app

    _oms_app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
async def oms_client(oms_app):
    """httpx.AsyncClient bound to the OMS test app."""
    transport = httpx.ASGITransport(app=oms_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "dev-secret-key-change-me"},
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# WMS integration fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def wms_app():
    """Create WMS FastAPI app backed by in-memory SQLite."""
    from services.wms_api import (
        Base as WMSBase,
        FulfillmentCenterORM,
        InventoryORM,
        app as _wms_app,
        get_session as wms_get_session,
    )

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(WMSBase.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        # Seed 2 fulfillment centers
        centers = [
            FulfillmentCenterORM(
                center_id="FC-EAST",
                name="East Coast Hub",
                region="us-east-1",
                capacity_units=10000,
                current_utilization=0.75,
                active=True,
            ),
            FulfillmentCenterORM(
                center_id="FC-WEST",
                name="West Coast Hub",
                region="us-west-2",
                capacity_units=8000,
                current_utilization=0.92,
                active=True,
            ),
        ]
        session.add_all(centers)

        # Seed 5 inventory items (2 below reorder_point = low stock)
        inventory = [
            InventoryORM(
                inventory_id="INV-00000001",
                sku="SKU-A100",
                product_name="Widget A",
                fulfillment_center_id="FC-EAST",
                quantity_on_hand=500,
                quantity_allocated=100,
                quantity_available=400,
                reorder_point=50,
                last_counted_at="2025-03-01T08:00:00",
                category="widgets",
            ),
            InventoryORM(
                inventory_id="INV-00000002",
                sku="SKU-B200",
                product_name="Widget B",
                fulfillment_center_id="FC-EAST",
                quantity_on_hand=20,
                quantity_allocated=15,
                quantity_available=5,
                reorder_point=50,
                last_counted_at="2025-03-01T08:00:00",
                category="widgets",
            ),
            InventoryORM(
                inventory_id="INV-00000003",
                sku="SKU-C300",
                product_name="Gadget C",
                fulfillment_center_id="FC-WEST",
                quantity_on_hand=200,
                quantity_allocated=50,
                quantity_available=150,
                reorder_point=30,
                last_counted_at="2025-03-02T08:00:00",
                category="gadgets",
            ),
            InventoryORM(
                inventory_id="INV-00000004",
                sku="SKU-D400",
                product_name="Gadget D",
                fulfillment_center_id="FC-WEST",
                quantity_on_hand=10,
                quantity_allocated=8,
                quantity_available=2,
                reorder_point=25,
                last_counted_at="2025-03-02T08:00:00",
                category="gadgets",
            ),
            InventoryORM(
                inventory_id="INV-00000005",
                sku="SKU-A100",
                product_name="Widget A",
                fulfillment_center_id="FC-WEST",
                quantity_on_hand=300,
                quantity_allocated=50,
                quantity_available=250,
                reorder_point=50,
                last_counted_at="2025-03-02T08:00:00",
                category="widgets",
            ),
        ]
        session.add_all(inventory)
        await session.commit()

    async def _override_get_session():
        async with session_factory() as session:
            yield session

    _wms_app.dependency_overrides[wms_get_session] = _override_get_session

    yield _wms_app

    _wms_app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
async def wms_client(wms_app):
    """httpx.AsyncClient bound to the WMS test app."""
    transport = httpx.ASGITransport(app=wms_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "dev-secret-key-change-me"},
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# TMS integration fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def tms_app():
    """Create TMS FastAPI app backed by in-memory SQLite."""
    from services.tms_api import (
        Base as TMSBase,
        ShipmentORM,
        TrackingEventORM,
        app as _tms_app,
        get_session as tms_get_session,
    )

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(TMSBase.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        # Seed 5 shipments
        shipments = [
            ShipmentORM(
                shipment_id="SHP-20250301-00001",
                order_id="ORD-2025-001",
                carrier="FedEx",
                service_level="ground",
                status="in_transit",
                tracking_number="FX1234567890",
                origin_center_id="FC-EAST",
                destination_zip="10001",
                destination_state="NY",
                weight_lbs=5.0,
                shipping_cost=12.50,
                label_created_at="2025-03-01T10:00:00",
                estimated_delivery="2025-03-05T18:00:00",
                actual_delivery=None,
                sla_target="2025-03-06T18:00:00",
                sla_status="on_track",
            ),
            ShipmentORM(
                shipment_id="SHP-20250302-00002",
                order_id="ORD-2025-002",
                carrier="UPS",
                service_level="express",
                status="delivered",
                tracking_number="UPS9876543210",
                origin_center_id="FC-WEST",
                destination_zip="90210",
                destination_state="CA",
                weight_lbs=3.0,
                shipping_cost=18.00,
                label_created_at="2025-03-02T10:00:00",
                estimated_delivery="2025-03-04T18:00:00",
                actual_delivery="2025-03-04T14:00:00",
                sla_target="2025-03-05T18:00:00",
                sla_status="met",
            ),
            ShipmentORM(
                shipment_id="SHP-20250303-00003",
                order_id="ORD-2025-003",
                carrier="FedEx",
                service_level="overnight",
                status="in_transit",
                tracking_number="FX1111111111",
                origin_center_id="FC-EAST",
                destination_zip="60601",
                destination_state="IL",
                weight_lbs=8.0,
                shipping_cost=35.00,
                label_created_at="2025-03-03T10:00:00",
                estimated_delivery="2025-03-04T18:00:00",
                actual_delivery=None,
                sla_target="2025-03-04T18:00:00",
                sla_status="breached",
            ),
            ShipmentORM(
                shipment_id="SHP-20250304-00004",
                order_id="ORD-2025-004",
                carrier="USPS",
                service_level="priority",
                status="out_for_delivery",
                tracking_number="USPS5555555555",
                origin_center_id="FC-WEST",
                destination_zip="33101",
                destination_state="FL",
                weight_lbs=2.0,
                shipping_cost=8.00,
                label_created_at="2025-03-04T10:00:00",
                estimated_delivery="2025-03-07T18:00:00",
                actual_delivery=None,
                sla_target="2025-03-08T18:00:00",
                sla_status="on_track",
            ),
            ShipmentORM(
                shipment_id="SHP-20250305-00005",
                order_id="ORD-2025-005",
                carrier="UPS",
                service_level="ground",
                status="delivered",
                tracking_number="UPS2222222222",
                origin_center_id="FC-EAST",
                destination_zip="02101",
                destination_state="MA",
                weight_lbs=4.5,
                shipping_cost=10.00,
                label_created_at="2025-03-05T10:00:00",
                estimated_delivery="2025-03-10T18:00:00",
                actual_delivery="2025-03-09T12:00:00",
                sla_target="2025-03-10T18:00:00",
                sla_status="met",
            ),
        ]
        session.add_all(shipments)

        # Seed tracking events (2-3 per shipment)
        events = [
            # Shipment 1
            TrackingEventORM(
                event_id="EVT-001",
                shipment_id="SHP-20250301-00001",
                timestamp="2025-03-01T10:00:00",
                location="New York, NY",
                status="label_created",
                description="Shipping label created",
            ),
            TrackingEventORM(
                event_id="EVT-002",
                shipment_id="SHP-20250301-00001",
                timestamp="2025-03-02T08:00:00",
                location="Newark, NJ",
                status="in_transit",
                description="Package picked up",
            ),
            TrackingEventORM(
                event_id="EVT-003",
                shipment_id="SHP-20250301-00001",
                timestamp="2025-03-03T14:00:00",
                location="Philadelphia, PA",
                status="in_transit",
                description="In transit to destination",
            ),
            # Shipment 2
            TrackingEventORM(
                event_id="EVT-004",
                shipment_id="SHP-20250302-00002",
                timestamp="2025-03-02T10:00:00",
                location="Los Angeles, CA",
                status="label_created",
                description="Shipping label created",
            ),
            TrackingEventORM(
                event_id="EVT-005",
                shipment_id="SHP-20250302-00002",
                timestamp="2025-03-03T12:00:00",
                location="Los Angeles, CA",
                status="in_transit",
                description="Package in transit",
            ),
            TrackingEventORM(
                event_id="EVT-006",
                shipment_id="SHP-20250302-00002",
                timestamp="2025-03-04T14:00:00",
                location="Beverly Hills, CA",
                status="delivered",
                description="Package delivered",
            ),
            # Shipment 3
            TrackingEventORM(
                event_id="EVT-007",
                shipment_id="SHP-20250303-00003",
                timestamp="2025-03-03T10:00:00",
                location="New York, NY",
                status="label_created",
                description="Shipping label created",
            ),
            TrackingEventORM(
                event_id="EVT-008",
                shipment_id="SHP-20250303-00003",
                timestamp="2025-03-04T06:00:00",
                location="Cleveland, OH",
                status="in_transit",
                description="In transit",
            ),
            # Shipment 4
            TrackingEventORM(
                event_id="EVT-009",
                shipment_id="SHP-20250304-00004",
                timestamp="2025-03-04T10:00:00",
                location="San Francisco, CA",
                status="label_created",
                description="Shipping label created",
            ),
            TrackingEventORM(
                event_id="EVT-010",
                shipment_id="SHP-20250304-00004",
                timestamp="2025-03-05T08:00:00",
                location="Phoenix, AZ",
                status="in_transit",
                description="In transit",
            ),
            TrackingEventORM(
                event_id="EVT-011",
                shipment_id="SHP-20250304-00004",
                timestamp="2025-03-06T10:00:00",
                location="Miami, FL",
                status="out_for_delivery",
                description="Out for delivery",
            ),
            # Shipment 5
            TrackingEventORM(
                event_id="EVT-012",
                shipment_id="SHP-20250305-00005",
                timestamp="2025-03-05T10:00:00",
                location="New York, NY",
                status="label_created",
                description="Shipping label created",
            ),
            TrackingEventORM(
                event_id="EVT-013",
                shipment_id="SHP-20250305-00005",
                timestamp="2025-03-07T14:00:00",
                location="Hartford, CT",
                status="in_transit",
                description="In transit",
            ),
            TrackingEventORM(
                event_id="EVT-014",
                shipment_id="SHP-20250305-00005",
                timestamp="2025-03-09T12:00:00",
                location="Boston, MA",
                status="delivered",
                description="Delivered",
            ),
        ]
        session.add_all(events)
        await session.commit()

    async def _override_get_session():
        async with session_factory() as session:
            yield session

    _tms_app.dependency_overrides[tms_get_session] = _override_get_session

    yield _tms_app

    _tms_app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
async def tms_client(tms_app):
    """httpx.AsyncClient bound to the TMS test app."""
    transport = httpx.ASGITransport(app=tms_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "dev-secret-key-change-me"},
    ) as client:
        yield client


@pytest.fixture
async def ops_client(oms_app, wms_app, tms_app):
    """Real OpsClient wired to the in-process ASGI apps.

    OpsClient builds its own httpx clients in __init__; we drop those and swap in
    ASGITransport-backed clients so the unified client exercises the real error
    mapping, retry, and header plumbing against the test apps.
    """
    from services.client import OpsClient

    client = OpsClient()
    await client.aclose()  # drop the real network clients
    client._oms = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=oms_app), base_url="http://oms"
    )
    client._wms = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=wms_app), base_url="http://wms"
    )
    client._tms = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=tms_app), base_url="http://tms"
    )
    yield client
    await client.aclose()
