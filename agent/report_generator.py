"""Report generation reasoner for multi-section operational reports."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from models.report import ReportOutput, ReportSection
from services.client import OpsClient

# ---------------------------------------------------------------------------
# Report type detection
# ---------------------------------------------------------------------------

_REPORT_KEYWORDS: dict[str, list[str]] = {
    "exception_summary": [
        "exception",
        "error",
        "issue",
        "problem",
        "fault",
    ],
    "sla_compliance": [
        "sla",
        "compliance",
        "on-time",
        "on time",
        "delivery rate",
        "breach",
    ],
    "center_health": [
        "center",
        "warehouse",
        "fulfillment",
        "utilization",
        "capacity",
        "inventory health",
    ],
    "daily_volume_trend": [
        "volume",
        "trend",
        "daily",
        "orders over time",
        "revenue trend",
    ],
    "carrier_performance": [
        "carrier",
        "shipping performance",
        "transit",
        "delivery performance",
        "cost per shipment",
    ],
}


def _detect_report_type(request: str) -> str:
    """Map a natural-language request to a canonical report type via keywords."""
    lower = request.lower()
    best_type = "exception_summary"
    best_count = 0
    for report_type, keywords in _REPORT_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in lower)
        if count > best_count:
            best_count = count
            best_type = report_type
    return best_type


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


async def collect_report_data(client: OpsClient, report_type: str) -> dict[str, Any]:
    """Collect data from APIs based on the requested report type.

    Returns a dict with the relevant data payloads for report building.
    """
    if report_type == "exception_summary":
        summary, open_exceptions, daily_stats = await asyncio.gather(
            client.get_exception_summary(),
            client.list_exceptions(status="open"),
            client.get_daily_stats(days=7),
        )
        return {
            "summary": summary,
            "open_exceptions": open_exceptions,
            "daily_stats": daily_stats,
        }

    if report_type == "sla_compliance":
        sla_summary, sla_breaches, carrier_perf = await asyncio.gather(
            client.get_sla_summary(),
            client.get_sla_breaches(),
            client.get_carrier_performance(),
        )
        return {
            "sla_summary": sla_summary,
            "sla_breaches": sla_breaches,
            "carrier_performance": carrier_perf,
        }

    if report_type == "center_health":
        centers, utilization, low_stock = await asyncio.gather(
            client.list_centers(),
            client.get_utilization(),
            client.get_low_stock(),
        )
        return {
            "centers": centers,
            "utilization": utilization,
            "low_stock": low_stock,
        }

    if report_type == "daily_volume_trend":
        daily_stats = await client.get_daily_stats(days=14)
        return {"daily_stats": daily_stats}

    if report_type == "carrier_performance":
        carrier_stats, recent_shipments = await asyncio.gather(
            client.get_carrier_performance(),
            client.list_shipments(limit=50),
        )
        return {
            "carrier_stats": carrier_stats,
            "recent_shipments": recent_shipments,
        }

    # Fallback: treat unknown types as exception_summary
    return await collect_report_data(client, "exception_summary")


# ---------------------------------------------------------------------------
# ReportBuilder helper
# ---------------------------------------------------------------------------


class ReportBuilder:
    """Fluent builder for ReportOutput, reducing boilerplate in report functions."""

    def __init__(self, report_type: str, title: str) -> None:
        self._report_type = report_type
        self._title = title
        self._sections: list[ReportSection] = []
        self._action_items: list[str] = []

    def add_section(
        self,
        title: str,
        content: str,
        data_table: list[dict[str, Any]] | None = None,
        highlight: str | None = None,
    ) -> "ReportBuilder":
        self._sections.append(
            ReportSection(title=title, content=content, data_table=data_table, highlight=highlight)
        )
        return self

    def add_action_item(self, item: str) -> "ReportBuilder":
        self._action_items.append(item)
        return self

    def build(self) -> ReportOutput:
        return ReportOutput(
            report_type=self._report_type,
            title=self._title,
            generated_at=datetime.now(tz=UTC),
            sections=self._sections,
            action_items=self._action_items,
        )


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------


def _build_exception_summary_report(data: dict[str, Any]) -> ReportOutput:
    """Build an exception summary report from collected data."""
    summary = data["summary"]
    open_items = data["open_exceptions"].items
    daily_stats = data["daily_stats"]

    critical_count = summary.by_severity.get("critical", 0)
    builder = ReportBuilder("exception_summary", "Exception Summary Report")

    builder.add_section(
        "Exception Overview",
        f"There are {summary.total_open} open exceptions and {summary.total_resolved} resolved exceptions.",
        data_table=[{"type": k, "count": v} for k, v in summary.by_type.items()],
        highlight=f"{summary.total_open} open exceptions require attention",
    )
    builder.add_section(
        "Severity Breakdown",
        "Distribution of exceptions across severity levels.",
        data_table=[{"severity": k, "count": v} for k, v in summary.by_severity.items()],
        highlight=f"{critical_count} critical exceptions" if critical_count > 0 else None,
    )
    builder.add_section(
        "Open Exceptions",
        f"{len(open_items)} open exceptions listed below.",
        data_table=[
            {"exception_id": ex.exception_id, "order_id": ex.order_id, "type": ex.exception_type, "severity": ex.severity, "created_at": ex.created_at.isoformat()}
            for ex in open_items
        ],
    )

    critical_exceptions = [ex for ex in open_items if ex.severity == "critical"]
    for ex in critical_exceptions[:5]:
        builder.add_action_item(f"Investigate critical exception {ex.exception_id} (order {ex.order_id}, type: {ex.exception_type})")
    if not critical_exceptions:
        builder.add_action_item("No critical exceptions at this time.")
    if daily_stats:
        avg_rate = sum(d.exception_rate for d in daily_stats) / len(daily_stats)
        builder.add_action_item(f"Average exception rate over last {len(daily_stats)} days: {avg_rate:.1%} — monitor for upward trends.")

    return builder.build()


def _build_sla_compliance_report(data: dict[str, Any]) -> ReportOutput:
    """Build an SLA compliance report from collected data."""
    sla = data["sla_summary"]
    breach_items = data["sla_breaches"].items
    carrier_perf = data["carrier_performance"]

    builder = ReportBuilder("sla_compliance", "SLA Compliance Report")

    builder.add_section(
        "SLA Overview",
        f"Overall SLA compliance rate: {sla.compliance_rate:.1%}. Of {sla.total_shipments} shipments, {sla.met} met SLA, {sla.at_risk} are at risk, and {sla.breached} have breached.",
        data_table=[
            {"metric": "Total Shipments", "value": sla.total_shipments},
            {"metric": "On Track", "value": sla.on_track},
            {"metric": "At Risk", "value": sla.at_risk},
            {"metric": "Breached", "value": sla.breached},
            {"metric": "Met", "value": sla.met},
            {"metric": "Compliance Rate", "value": f"{sla.compliance_rate:.1%}"},
        ],
        highlight=f"Compliance rate: {sla.compliance_rate:.1%}" if sla.compliance_rate < 0.95 else None,
    )
    builder.add_section(
        "At-Risk Shipments",
        f"{len(breach_items)} shipments with SLA breaches.",
        data_table=[{"shipment_id": s.shipment_id, "order_id": s.order_id, "carrier": s.carrier, "sla_status": s.sla_status, "estimated_delivery": s.estimated_delivery.isoformat()} for s in breach_items],
        highlight=f"{len(breach_items)} SLA breaches detected" if breach_items else None,
    )
    builder.add_section(
        "Carrier SLA Performance",
        "Carrier-level SLA performance comparison.",
        data_table=[{"carrier": cs.carrier, "on_time_rate": f"{cs.on_time_rate:.1%}", "avg_transit_days": f"{cs.avg_transit_days:.1f}", "total_shipments": cs.total_shipments} for cs in carrier_perf],
    )

    for cs in carrier_perf:
        if cs.on_time_rate < 0.90:
            builder.add_action_item(f"Investigate carrier {cs.carrier} — on-time rate {cs.on_time_rate:.1%} is below 90% threshold.")
    if sla.breached > 0:
        builder.add_action_item(f"Review {sla.breached} breached shipments for root cause analysis.")
    if not builder._action_items:
        builder.add_action_item("All carriers meeting SLA targets.")

    return builder.build()


def _build_center_health_report(data: dict[str, Any]) -> ReportOutput:
    """Build a center health report from collected data."""
    centers = data["utilization"]
    low_items = data["low_stock"].items
    high_util = [c for c in centers if c.current_utilization > 0.90]

    builder = ReportBuilder("center_health", "Center Health Report")

    builder.add_section(
        "Center Utilization",
        f"{len(centers)} fulfillment centers tracked. {len(high_util)} operating above 90% capacity.",
        data_table=[{"center_id": c.center_id, "name": c.name, "region": c.region, "capacity": c.capacity_units, "utilization": f"{c.current_utilization:.1%}", "active": c.active} for c in centers],
        highlight=f"{len(high_util)} centers above 90% utilization" if high_util else None,
    )
    builder.add_section(
        "Low Stock Alert",
        f"{len(low_items)} items below their reorder point.",
        data_table=[{"sku": item.sku, "product_name": item.product_name, "center_id": item.fulfillment_center_id, "on_hand": item.quantity_on_hand, "available": item.quantity_available, "reorder_point": item.reorder_point} for item in low_items],
        highlight=f"{len(low_items)} items need reordering" if low_items else None,
    )

    for c in high_util:
        builder.add_action_item(f"Center {c.center_id} ({c.name}) at {c.current_utilization:.1%} utilization — consider load balancing.")
    for item in low_items[:5]:
        builder.add_action_item(f"Reorder {item.sku} at {item.fulfillment_center_id} — {item.quantity_available} available vs {item.reorder_point} reorder point.")
    if not builder._action_items:
        builder.add_action_item("All centers and inventory levels within normal range.")

    return builder.build()


def _build_daily_volume_trend_report(data: dict[str, Any]) -> ReportOutput:
    """Build a daily volume trend report from collected data."""
    daily_stats = data["daily_stats"]
    total_orders = sum(d.total_orders for d in daily_stats)
    total_revenue = sum(d.total_value for d in daily_stats)

    builder = ReportBuilder("daily_volume_trend", "Daily Volume Trend Report")

    builder.add_section(
        "Volume Trend",
        f"Order volume over the last {len(daily_stats)} days. Total: {total_orders} orders.",
        data_table=[{"date": str(d.date), "total_orders": d.total_orders, "exception_rate": f"{d.exception_rate:.1%}"} for d in daily_stats],
    )
    builder.add_section(
        "Revenue Trend",
        f"Revenue over the last {len(daily_stats)} days. Total: ${total_revenue:,.2f}.",
        data_table=[{"date": str(d.date), "total_value": f"${d.total_value:,.2f}"} for d in daily_stats],
    )

    if len(daily_stats) >= 2:
        recent, previous = daily_stats[-1], daily_stats[-2]
        if previous.total_orders > 0:
            if recent.total_orders > previous.total_orders * 1.2:
                builder.add_action_item(f"Order volume spike on {recent.date}: {recent.total_orders} orders (+{((recent.total_orders / previous.total_orders) - 1):.0%} vs prior day).")
            if recent.total_orders < previous.total_orders * 0.8:
                builder.add_action_item(f"Order volume drop on {recent.date}: {recent.total_orders} orders ({((recent.total_orders / previous.total_orders) - 1):.0%} vs prior day).")
    high_exception_days = [d for d in daily_stats if d.exception_rate > 0.05]
    if high_exception_days:
        builder.add_action_item(f"{len(high_exception_days)} day(s) with exception rate above 5% — investigate operational issues.")
    if not builder._action_items:
        builder.add_action_item("Volume and revenue trends within normal range.")

    return builder.build()


def _build_carrier_performance_report(data: dict[str, Any]) -> ReportOutput:
    """Build a carrier performance report from collected data."""
    carrier_stats = data["carrier_stats"]
    recent_shipments = data["recent_shipments"]

    builder = ReportBuilder("carrier_performance", "Carrier Performance Report")

    builder.add_section(
        "On-Time Performance",
        f"Performance summary for {len(carrier_stats)} carriers.",
        data_table=[{"carrier": cs.carrier, "on_time_rate": f"{cs.on_time_rate:.1%}", "avg_transit_days": f"{cs.avg_transit_days:.1f}", "total_shipments": cs.total_shipments} for cs in carrier_stats],
    )
    builder.add_section(
        "Cost Analysis",
        "Average shipping cost comparison across carriers.",
        data_table=[{"carrier": cs.carrier, "avg_cost": f"${cs.avg_cost:.2f}", "total_shipments": cs.total_shipments} for cs in carrier_stats],
    )

    if carrier_stats:
        best = max(carrier_stats, key=lambda cs: cs.on_time_rate)
        worst = min(carrier_stats, key=lambda cs: cs.on_time_rate)
        if best.carrier != worst.carrier:
            builder.add_action_item(f"Best on-time: {best.carrier} ({best.on_time_rate:.1%}). Worst: {worst.carrier} ({worst.on_time_rate:.1%}). Consider shifting volume from {worst.carrier} to {best.carrier}.")
        cheapest = min(carrier_stats, key=lambda cs: cs.avg_cost)
        priciest = max(carrier_stats, key=lambda cs: cs.avg_cost)
        if cheapest.carrier != priciest.carrier:
            builder.add_action_item(f"Cost range: ${cheapest.avg_cost:.2f} ({cheapest.carrier}) to ${priciest.avg_cost:.2f} ({priciest.carrier}). Evaluate cost-performance trade-offs.")
    exception_shipments = [s for s in recent_shipments.items if s.status == "exception"]
    if exception_shipments:
        builder.add_action_item(f"{len(exception_shipments)} recent shipments in exception status — review for carrier issues.")
    if not builder._action_items:
        builder.add_action_item("Carrier performance metrics within expected range.")

    return builder.build()


# ---------------------------------------------------------------------------
# Report builder dispatch
# ---------------------------------------------------------------------------

_REPORT_BUILDERS: dict[str, Any] = {
    "exception_summary": _build_exception_summary_report,
    "sla_compliance": _build_sla_compliance_report,
    "center_health": _build_center_health_report,
    "daily_volume_trend": _build_daily_volume_trend_report,
    "carrier_performance": _build_carrier_performance_report,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_report(
    client: OpsClient, report_request: str
) -> ReportOutput:
    """Generate a structured operational report from a natural-language request.

    1. Determines report_type from the request string.
    2. Collects the appropriate data from backend APIs.
    3. Builds a ReportOutput with typed sections and action items.

    TODO: Integrate LLM for richer narrative generation using
    GENERATE_REPORT_SYSTEM / GENERATE_REPORT_USER prompt templates.
    """
    report_type = _detect_report_type(report_request)
    data = await collect_report_data(client, report_type)
    builder = _REPORT_BUILDERS[report_type]
    return builder(data)
