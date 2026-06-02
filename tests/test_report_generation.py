"""Tests for report generation builders (Story 15.7)."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

from agent.report_generator import (
    ReportBuilder,
    _build_carrier_performance_report,
    _build_center_health_report,
    _build_daily_volume_trend_report,
    _build_exception_summary_report,
    _build_sla_compliance_report,
    _enrich_with_llm,
    generate_report,
)
from config.settings import get_settings
from models.oms import DailyStats, ExceptionSummary, OrderException
from models.report import ReportOutput
from models.shared import PaginatedResponse
from models.tms import CarrierStats, Shipment, SLASummary
from models.wms import FulfillmentCenter, InventoryItem

# ---------------------------------------------------------------------------
# Helpers to build mock data
# ---------------------------------------------------------------------------


def _mock_exception_summary():
    return ExceptionSummary(
        by_type={"payment_failed": 3, "address_invalid": 2},
        by_severity={"critical": 2, "high": 1, "low": 2},
        total_open=4,
        total_resolved=1,
    )


def _mock_open_exceptions():
    return PaginatedResponse[OrderException](
        items=[
            OrderException(
                exception_id="EXC-001",
                order_id="ORD-2025-001",
                exception_type="payment_failed",
                severity="critical",
                status="open",
                created_at=datetime(2025, 3, 1, 12, 0, tzinfo=UTC),
                description="Payment failed",
            ),
            OrderException(
                exception_id="EXC-002",
                order_id="ORD-2025-002",
                exception_type="address_invalid",
                severity="high",
                status="open",
                created_at=datetime(2025, 3, 2, 12, 0, tzinfo=UTC),
                description="Address invalid",
            ),
        ],
        total=2,
        offset=0,
        limit=50,
    )


def _mock_daily_stats(count=7, spike=False):
    stats = []
    for i in range(count):
        orders = 100
        if spike and i == count - 1:
            orders = 150  # 50% spike vs previous day
        stats.append(
            DailyStats(
                date=date(2025, 3, 1 + i),
                total_orders=orders,
                total_value=orders * 50.0,
                exception_rate=0.02,
                orders_by_status={"pending": orders // 2, "shipped": orders // 2},
            )
        )
    return stats


def _mock_sla_summary():
    return SLASummary(
        total_shipments=100,
        on_track=40,
        at_risk=10,
        breached=5,
        met=45,
        compliance_rate=0.85,
        by_carrier={
            "FedEx": {"on_track": 20, "met": 25, "breached": 3, "at_risk": 2},
            "UPS": {"on_track": 20, "met": 20, "breached": 2, "at_risk": 8},
        },
    )


def _mock_sla_breaches():
    return PaginatedResponse[Shipment](
        items=[
            Shipment(
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
                label_created_at=datetime(2025, 3, 3, 10, 0, tzinfo=UTC),
                estimated_delivery=datetime(2025, 3, 4, 18, 0, tzinfo=UTC),
                sla_target=datetime(2025, 3, 4, 18, 0, tzinfo=UTC),
                sla_status="breached",
            ),
        ],
        total=1,
        offset=0,
        limit=50,
    )


def _mock_carrier_stats(low_performer=False):
    stats = [
        CarrierStats(
            carrier="FedEx",
            on_time_rate=0.95,
            avg_transit_days=3.2,
            avg_cost=15.00,
            total_shipments=50,
        ),
        CarrierStats(
            carrier="UPS",
            on_time_rate=0.85 if low_performer else 0.92,
            avg_transit_days=4.0,
            avg_cost=12.00,
            total_shipments=50,
        ),
    ]
    return stats


def _mock_centers(high_util=False):
    return [
        FulfillmentCenter(
            center_id="FC-EAST",
            name="East Coast Hub",
            region="us-east-1",
            capacity_units=10000,
            current_utilization=0.95 if high_util else 0.75,
            active=True,
        ),
        FulfillmentCenter(
            center_id="FC-WEST",
            name="West Coast Hub",
            region="us-west-2",
            capacity_units=8000,
            current_utilization=0.60,
            active=True,
        ),
    ]


def _mock_low_stock():
    return PaginatedResponse[InventoryItem](
        items=[
            InventoryItem(
                inventory_id="INV-00000002",
                sku="SKU-B200",
                product_name="Widget B",
                fulfillment_center_id="FC-EAST",
                quantity_on_hand=20,
                quantity_allocated=15,
                quantity_available=5,
                reorder_point=50,
                last_counted_at=datetime(2025, 3, 1, 8, 0, tzinfo=UTC),
                category="widgets",
            ),
        ],
        total=1,
        offset=0,
        limit=50,
    )


def _mock_recent_shipments():
    return PaginatedResponse[Shipment](
        items=[
            Shipment(
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
                label_created_at=datetime(2025, 3, 1, 10, 0, tzinfo=UTC),
                estimated_delivery=datetime(2025, 3, 5, 18, 0, tzinfo=UTC),
                sla_target=datetime(2025, 3, 6, 18, 0, tzinfo=UTC),
                sla_status="on_track",
            ),
        ],
        total=1,
        offset=0,
        limit=50,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExceptionSummaryReport:
    def test_exception_summary_critical_action_item(self):
        data = {
            "summary": _mock_exception_summary(),
            "open_exceptions": _mock_open_exceptions(),
            "daily_stats": _mock_daily_stats(),
        }
        report = _build_exception_summary_report(data)
        assert report.report_type == "exception_summary"
        assert len(report.sections) >= 2
        # Critical exception should generate an action item
        critical_items = [ai for ai in report.action_items if "critical" in ai.lower()]
        assert len(critical_items) >= 1
        assert "EXC-001" in critical_items[0]


class TestSLAComplianceReport:
    def test_sla_compliance_low_performer(self):
        data = {
            "sla_summary": _mock_sla_summary(),
            "sla_breaches": _mock_sla_breaches(),
            "carrier_performance": _mock_carrier_stats(low_performer=True),
        }
        report = _build_sla_compliance_report(data)
        assert report.report_type == "sla_compliance"
        # UPS at 85% should be flagged (below 90%)
        low_perf_items = [ai for ai in report.action_items if "UPS" in ai and "below 90%" in ai]
        assert len(low_perf_items) >= 1


class TestCenterHealthReport:
    def test_center_health_high_utilization(self):
        data = {
            "centers": _mock_centers(high_util=True),
            "utilization": _mock_centers(high_util=True),
            "low_stock": _mock_low_stock(),
        }
        report = _build_center_health_report(data)
        assert report.report_type == "center_health"
        # FC-EAST at 95% should be flagged
        high_util_items = [
            ai for ai in report.action_items if "FC-EAST" in ai and "utilization" in ai.lower()
        ]
        assert len(high_util_items) >= 1


class TestDailyVolumeTrendReport:
    def test_daily_volume_spike(self):
        data = {"daily_stats": _mock_daily_stats(count=3, spike=True)}
        report = _build_daily_volume_trend_report(data)
        assert report.report_type == "daily_volume_trend"
        # 150 vs 100 = 50% spike, should trigger action item
        spike_items = [ai for ai in report.action_items if "spike" in ai.lower()]
        assert len(spike_items) >= 1


class TestCarrierPerformanceReport:
    def test_carrier_performance_best_worst(self):
        data = {
            "carrier_stats": _mock_carrier_stats(low_performer=True),
            "recent_shipments": _mock_recent_shipments(),
        }
        report = _build_carrier_performance_report(data)
        assert report.report_type == "carrier_performance"
        # Best = FedEx (0.95), Worst = UPS (0.85) should be compared
        comparison_items = [ai for ai in report.action_items if "FedEx" in ai and "UPS" in ai]
        assert len(comparison_items) >= 1


class TestGenerateReport:
    async def test_generate_report_dispatch(self):
        """Correct builder is called based on detected report type."""
        client = AsyncMock()
        client.get_exception_summary = AsyncMock(return_value=_mock_exception_summary())
        client.list_exceptions = AsyncMock(return_value=_mock_open_exceptions())
        client.get_daily_stats = AsyncMock(return_value=_mock_daily_stats())

        report = await generate_report(client, "show me exception summary report")
        assert isinstance(report, ReportOutput)
        assert report.report_type == "exception_summary"
        assert len(report.sections) >= 1

    async def test_generate_report_unknown_type(self):
        """Unknown report type falls back to exception_summary."""
        client = AsyncMock()
        client.get_exception_summary = AsyncMock(return_value=_mock_exception_summary())
        client.list_exceptions = AsyncMock(return_value=_mock_open_exceptions())
        client.get_daily_stats = AsyncMock(return_value=_mock_daily_stats())

        report = await generate_report(client, "give me a random thing")
        assert isinstance(report, ReportOutput)
        assert report.report_type == "exception_summary"


class TestEnrichReportLLM:
    """#7: report enrichment must route through agent.llm.structured_call,
    never a hand-rolled AsyncAnthropic client that leaks its httpx pool.
    """

    def _base_report(self):
        builder = ReportBuilder("exception_summary", "Exception Summary")
        builder.add_section("Overview", "rule-based content")
        return builder.build()

    async def test_routes_through_structured_call(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")

        llm_dict = {
            "report_type": "exception_summary",
            "title": "Exception Summary",
            "generated_at": "2026-06-02T00:00:00Z",
            "sections": [{"title": "Overview", "content": "LLM narrative"}],
            "action_items": ["LLM action item"],
        }
        call = AsyncMock(return_value=(llm_dict, {"input_tokens": 1, "output_tokens": 1}))
        with (
            patch("agent.report_generator.structured_call", call),
            patch("anthropic.AsyncAnthropic") as raw_client,
        ):
            out = await _enrich_with_llm(self._base_report(), "exception report", {})

        call.assert_awaited_once()
        raw_client.assert_not_called()
        assert out.sections[0].content == "LLM narrative"
        assert "LLM action item" in out.action_items

    async def test_falls_back_to_rule_report_on_error(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")

        call = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("agent.report_generator.structured_call", call):
            out = await _enrich_with_llm(self._base_report(), "exception report", {})

        # Unchanged rule-based content on failure.
        assert out.sections[0].content == "rule-based content"


class TestReportBuilder:
    def test_report_builder_class(self):
        builder = ReportBuilder("test_type", "Test Title")
        builder.add_section("Section 1", "Content here", highlight="Important")
        builder.add_action_item("Do something")
        builder.add_action_item("Do another thing")
        report = builder.build()

        assert report.report_type == "test_type"
        assert report.title == "Test Title"
        assert len(report.sections) == 1
        assert report.sections[0].title == "Section 1"
        assert report.sections[0].highlight == "Important"
        assert len(report.action_items) == 2
        assert report.generated_at is not None
