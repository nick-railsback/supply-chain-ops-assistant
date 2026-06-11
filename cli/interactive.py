"""Rich interactive CLI with prompt loop and formatted output."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from agent.copilot import Copilot
from config.prompts import EXECUTE_AND_FLAG_RESPONSE
from models.action import ActionProposal
from models.query import ConfidenceSignals, QueryPlan
from models.report import ReportOutput
from models.shared import RiskLevel
from services.client import OpsClient

logger = logging.getLogger(__name__)

# ===================================================================
# Status color mapping  (Story 9.2)
# ===================================================================

STATUS_COLORS: dict[str, str] = {
    # Green — good / complete states
    "delivered": "green",
    "resolved": "green",
    "met": "green",
    "on_track": "green",
    "active": "green",
    "shipped": "green",
    # Yellow — in-progress / warning states
    "processing": "yellow",
    "investigating": "yellow",
    "at_risk": "yellow",
    "pending": "yellow",
    "in_transit": "yellow",
    "label_created": "yellow",
    "picked_up": "yellow",
    "out_for_delivery": "yellow",
    "allocated": "yellow",
    "picked": "yellow",
    "packed": "yellow",
    # Red — error / critical states
    "exception": "red",
    "escalated": "red",
    "breached": "red",
    "critical": "red",
    "cancelled": "red",
    "backordered": "red",
    "returned": "red",
    "open": "red",
    "high": "red",
}

_RISK_COLORS: dict[str, str] = {
    "low": "green",
    "medium": "yellow",
    "high": "red",
}


def _colorize(value: str) -> Text:
    """Return a Rich Text with color based on STATUS_COLORS lookup."""
    color = STATUS_COLORS.get(value.lower(), "white") if value else "white"
    return Text(str(value), style=color)


def _fmt_currency(value: Any) -> str:
    """Format a numeric value as USD currency."""
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


# ===================================================================
# Table formatters  (Story 9.2)
# ===================================================================


def format_orders_table(orders: list[dict[str, Any]]) -> Table:
    """Build a Rich table from a list of order dicts."""
    table = Table(title="Orders", show_lines=False, expand=True)
    table.add_column("Order ID", style="cyan", no_wrap=True)
    table.add_column("Status")
    table.add_column("Customer Tier")
    table.add_column("Total Value", justify="right")
    table.add_column("Channel")
    table.add_column("Center", no_wrap=True)

    for o in orders:
        table.add_row(
            str(o.get("order_id", "")),
            _colorize(str(o.get("status", ""))),
            str(o.get("customer_tier", "")),
            _fmt_currency(o.get("total_value", 0)),
            str(o.get("channel", "")),
            str(o.get("fulfillment_center_id", "")),
        )
    return table


def format_exceptions_table(exceptions: list[dict[str, Any]]) -> Table:
    """Build a Rich table from a list of exception dicts."""
    table = Table(title="Exceptions", show_lines=False, expand=True)
    table.add_column("Exception ID", style="cyan", no_wrap=True)
    table.add_column("Order ID", no_wrap=True)
    table.add_column("Type")
    table.add_column("Severity")
    table.add_column("Status")
    table.add_column("Assigned To")

    for e in exceptions:
        table.add_row(
            str(e.get("exception_id", "")),
            str(e.get("order_id", "")),
            str(e.get("exception_type", "")),
            _colorize(str(e.get("severity", ""))),
            _colorize(str(e.get("status", ""))),
            str(e.get("assigned_to", "") or "unassigned"),
        )
    return table


def format_inventory_table(items: list[dict[str, Any]]) -> Table:
    """Build a Rich table from a list of inventory item dicts."""
    table = Table(title="Inventory", show_lines=False, expand=True)
    table.add_column("SKU", style="cyan", no_wrap=True)
    table.add_column("Product")
    table.add_column("Center", no_wrap=True)
    table.add_column("Available", justify="right")
    table.add_column("Reorder Pt", justify="right")
    table.add_column("On Hand", justify="right")

    for item in items:
        available = item.get("quantity_available", 0)
        reorder = item.get("reorder_point", 0)
        avail_style = "red" if available < reorder else "white"
        table.add_row(
            str(item.get("sku", "")),
            str(item.get("product_name", "")),
            str(item.get("fulfillment_center_id", "")),
            Text(str(available), style=avail_style),
            str(reorder),
            str(item.get("quantity_on_hand", "")),
        )
    return table


def format_shipments_table(shipments: list[dict[str, Any]]) -> Table:
    """Build a Rich table from a list of shipment dicts."""
    table = Table(title="Shipments", show_lines=False, expand=True)
    table.add_column("Shipment ID", style="cyan", no_wrap=True)
    table.add_column("Order ID", no_wrap=True)
    table.add_column("Carrier")
    table.add_column("Status")
    table.add_column("SLA Status")
    table.add_column("Tracking #", no_wrap=True)

    for s in shipments:
        table.add_row(
            str(s.get("shipment_id", "")),
            str(s.get("order_id", "")),
            str(s.get("carrier", "")),
            _colorize(str(s.get("status", ""))),
            _colorize(str(s.get("sla_status", ""))),
            str(s.get("tracking_number", "")),
        )
    return table


def format_carrier_stats_table(stats: list[dict[str, Any]]) -> Table:
    """Build a Rich table from a list of carrier stats dicts."""
    table = Table(title="Carrier Performance", show_lines=False, expand=True)
    table.add_column("Carrier")
    table.add_column("On-Time Rate", justify="right")
    table.add_column("Avg Transit (days)", justify="right")
    table.add_column("Avg Cost", justify="right")
    table.add_column("Total Shipments", justify="right")

    for cs in stats:
        rate = cs.get("on_time_rate", 0)
        try:
            rate_float = float(rate)
            rate_str = f"{rate_float:.1%}"
            if rate_float >= 0.95:
                rate_color = "green"
            elif rate_float >= 0.90:
                rate_color = "yellow"
            else:
                rate_color = "red"
        except (TypeError, ValueError):
            rate_str = str(rate)
            rate_color = "white"

        table.add_row(
            str(cs.get("carrier", "")),
            Text(rate_str, style=rate_color),
            str(cs.get("avg_transit_days", "")),
            _fmt_currency(cs.get("avg_cost", 0)),
            str(cs.get("total_shipments", "")),
        )
    return table


_SYSTEM_PREFIX_LABELS: dict[str, str] = {"oms_": "OMS", "wms_": "WMS", "tms_": "TMS"}


def _humanize_cross_system_key(key: str) -> str:
    """Turn a prefixed join field (``oms_status``) into a header (``OMS Status``)."""
    for prefix, label in _SYSTEM_PREFIX_LABELS.items():
        if key.startswith(prefix):
            field = key[len(prefix) :].replace("_", " ").title()
            return f"{label} {field}"
    return key.replace("_", " ").title()


def format_cross_system_table(rows: list[dict[str, Any]]) -> Table:
    """Build a Rich table from correlated cross-system rows.

    Correlated rows carry system-prefixed keys (``oms_status``, ``tms_carrier``)
    produced by ``copilot._correlate_cross_system``. Columns are derived
    dynamically from whichever systems and fields are present, so both sides of
    the join render instead of being dropped by a single-system formatter.
    """
    table = Table(title="Cross-System Results", show_lines=False, expand=True)

    # Preserve first-seen key order across all rows for stable columns.
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)

    for key in columns:
        table.add_column(_humanize_cross_system_key(key))

    for row in rows:
        cells: list[Any] = []
        for key in columns:
            value = row.get(key, "")
            if key.endswith("status"):
                cells.append(_colorize(str(value)))
            else:
                cells.append(str(value))
        table.add_row(*cells)

    return table


def _detect_data_type(items: list[dict[str, Any]]) -> str:
    """Heuristically detect the entity type from the first item's keys."""
    if not items:
        return "unknown"
    first = items[0]
    # Correlated cross-system rows carry system-prefixed keys (oms_/wms_/tms_);
    # detect them first so they don't fall through to a single-system formatter.
    if any(k.startswith(("oms_", "wms_", "tms_")) for k in first):
        return "cross_system"
    if "order_id" in first and "exception_type" in first:
        return "exceptions"
    if "order_id" in first and "total_value" in first:
        return "orders"
    if "sku" in first and "quantity_on_hand" in first:
        return "inventory"
    if "shipment_id" in first and "carrier" in first:
        return "shipments"
    if "on_time_rate" in first and "carrier" in first:
        return "carrier_stats"
    if "order_id" in first:
        return "orders"
    if "shipment_id" in first:
        return "shipments"
    if "exception_id" in first:
        return "exceptions"
    if "sku" in first:
        return "inventory"
    return "unknown"


def format_query_result(result: dict[str, Any]) -> Panel | Table | str:
    """Dispatch to the correct formatter based on data content."""
    items: list[dict[str, Any]] = result.get("data", [])
    if not items:
        return "No results found for that query."

    total = result.get("total_count", len(items))
    data_type = _detect_data_type(items)

    formatter_map: dict[str, Any] = {
        "orders": format_orders_table,
        "exceptions": format_exceptions_table,
        "inventory": format_inventory_table,
        "shipments": format_shipments_table,
        "carrier_stats": format_carrier_stats_table,
        "cross_system": format_cross_system_table,
    }

    formatter = formatter_map.get(data_type)
    if formatter is None:
        # Fall back to a generic key-value table
        table = Table(title="Results", expand=True)
        if items:
            for key in items[0]:
                table.add_column(str(key))
            for row in items:
                table.add_row(*(str(row.get(k, "")) for k in items[0]))
        return table

    table = formatter(items)
    summary = Text(f"Found {total} result(s), showing {len(items)}.", style="dim")
    return Panel(Group(summary, table), border_style="blue")


# ===================================================================
# Report rendering  (Story 9.3)
# ===================================================================


def _build_section_table(data_table: list[dict[str, Any]]) -> Table:
    """Build a simple Rich Table from a list of dicts."""
    table = Table(show_lines=False, expand=True, padding=(0, 1))
    if not data_table:
        return table
    for key in data_table[0]:
        table.add_column(str(key))
    for row in data_table:
        table.add_row(*(str(row.get(k, "")) for k in data_table[0]))
    return table


def render_report(report: ReportOutput) -> Panel:
    """Render a ReportOutput as a Rich Panel with sections and action items."""
    renderables: list[Any] = []

    timestamp = report.generated_at.strftime("%B %d, %Y %H:%M UTC")
    renderables.append(Text(f"Generated: {timestamp}", style="dim italic"))
    renderables.append(Text(""))

    for section in report.sections:
        # Section header
        renderables.append(Text(f"  {section.title}", style="bold underline"))
        renderables.append(Text(f"  {section.content}"))

        # Highlight callout
        if section.highlight:
            renderables.append(Text(f"  \u26a0 {section.highlight}", style="bold yellow"))

        # Data table
        if section.data_table:
            renderables.append(_build_section_table(section.data_table))

        renderables.append(Text(""))

    # Action items checklist
    if report.action_items:
        renderables.append(Text("  Action Items", style="bold underline"))
        for item in report.action_items:
            renderables.append(Text(f"  \u2610 {item}"))

    return Panel(
        Group(*renderables),
        title=f"[bold]{report.title}[/bold]",
        border_style="green",
        expand=True,
    )


# ===================================================================
# Reasoning panel  (C1 — surface the interpret/route/validate pipeline)
# ===================================================================

# Color per interpretation source so the LLM-vs-fallback choice is visible live.
_SOURCE_COLORS: dict[str, str] = {
    "llm": "green",
    "llm_repaired": "cyan",
    "rule_based": "yellow",
    "fallback": "red",
}


def _signal_items(signals: ConfidenceSignals) -> list[tuple[str, bool]]:
    """Flatten ConfidenceSignals into (label, value) pairs for display."""
    return [
        ("all filter fields known", signals.all_filter_fields_known),
        ("entity unambiguous", signals.entity_unambiguous),
        ("single clear intent", signals.single_clear_intent),
        ("time reference resolved", signals.time_reference_resolved),
    ]


def render_reasoning_panel(plan: QueryPlan, routing: str, errors: list[str]) -> Panel:
    """Render the interpret -> route -> validate pipeline for a single turn.

    Surfaces the work ``copilot.process_query`` does but the result view drops:
    the intent, how it was interpreted (LLM vs rule fallback), the confidence
    and the signals behind it, the routing decision, and the validation outcome.
    """
    source = plan.interpretation_source
    source_color = _SOURCE_COLORS.get(source, "white")

    conf_color = (
        "green" if plan.confidence >= 0.75 else "yellow" if plan.confidence >= 0.45 else "red"
    )

    rows: list[Any] = [
        Text.assemble(("Intent:      ", "bold"), plan.intent.value),
        Text.assemble(("Source:      ", "bold"), (source, f"bold {source_color}")),
        Text.assemble(("Confidence:  ", "bold"), (f"{plan.confidence:.0%}", conf_color)),
    ]
    if plan.model_confidence is not None:
        rows.append(
            Text.assemble(
                ("Self-report: ", "bold"),
                (f"{plan.model_confidence:.0%}", "dim"),
            )
        )

    if plan.confidence_signals is not None:
        rows.append(Text("Signals:", style="bold"))
        for label, value in _signal_items(plan.confidence_signals):
            mark = "✓" if value else "✗"
            mark_color = "green" if value else "red"
            rows.append(Text.assemble("  ", (f"{mark} ", mark_color), label))

    systems = ", ".join(s.value for s in plan.target_systems) or "(none)"
    rows.append(Text.assemble(("Systems:     ", "bold"), systems))
    rows.append(Text.assemble(("Routing:     ", "bold"), routing or "(n/a)"))

    # Token usage + latency (LLM path only; rule fallback leaves these unset).
    if plan.input_tokens is not None or plan.latency_ms is not None:
        parts = []
        if plan.input_tokens is not None:
            parts.append(f"{plan.input_tokens} in / {plan.output_tokens} out")
        if plan.latency_ms is not None:
            parts.append(f"{plan.latency_ms:.0f}ms")
        rows.append(Text.assemble(("Tokens:      ", "bold"), (" · ".join(parts), "dim")))

    if errors:
        rows.append(Text.assemble(("Validation:  ", "bold"), ("failed", "red")))
        rows.extend(Text(f"  - {err}", style="red") for err in errors)
    else:
        rows.append(Text.assemble(("Validation:  ", "bold"), ("passed", "green")))

    rows.append(Text(""))
    rows.append(Text(f"Reasoning: {plan.reasoning}", style="dim italic"))

    return Panel(
        Group(*rows),
        title="[bold]Reasoning[/bold]",
        border_style=source_color,
        expand=True,
    )


# ===================================================================
# Action confirmation UI  (Story 9.4)
# ===================================================================


def display_action_proposal(proposal: ActionProposal) -> Panel:
    """Render an ActionProposal as a Rich Panel with risk-colored border."""
    risk_color = _RISK_COLORS.get(proposal.risk_level.value, "white")
    risk_style = f"bold {risk_color}" if proposal.risk_level == RiskLevel.HIGH else risk_color

    renderables: list[Any] = []

    # Impact summary
    renderables.append(Text(f"  {proposal.impact_summary}", style="bold"))
    renderables.append(
        Text(f"  Risk: \u25a0 {proposal.risk_level.value.upper()}", style=risk_style)
    )
    renderables.append(Text(""))

    # Reasoning
    renderables.append(Text(f"  Reasoning: {proposal.reasoning}", style="dim"))
    renderables.append(Text(""))

    # Changes
    if proposal.changes:
        renderables.append(Text("  Changes:", style="bold"))
        for key, value in proposal.changes.items():
            renderables.append(Text(f"    {key} \u2192 {value!r}"))
        renderables.append(Text(""))

    # Target IDs
    renderables.append(Text(f"  Targets ({len(proposal.target_ids)}):", style="bold"))
    for tid in proposal.target_ids[:20]:
        renderables.append(Text(f"    {tid}"))
    if len(proposal.target_ids) > 20:
        renderables.append(Text(f"    ... and {len(proposal.target_ids) - 20} more", style="dim"))

    return Panel(
        Group(*renderables),
        title="[bold]Proposed Action[/bold]",
        border_style=risk_color,
        expand=True,
    )


async def prompt_confirmation(proposal: ActionProposal) -> bool:
    """Display proposal and prompt for confirmation using Rich Confirm."""
    console = Console()
    console.print(display_action_proposal(proposal))
    return Confirm.ask("Proceed with this action?", default=False)


# ===================================================================
# Main CLI class  (Story 9.1)
# ===================================================================

_HELP_TEXT = """\
[bold cyan]Supply Chain Ops Assistant[/bold cyan] - Example queries:

[bold]Ops Lead[/bold]
  "Show me all critical exceptions"
  "What orders are at risk of SLA breach?"
  "Give me a morning ops standup report"

[bold]Customer Experience[/bold]
  "Look up order ORD-2026-001234"
  "Show pending orders for enterprise customers"
  "Which shipments are in exception status?"

[bold]Finance / Logistics[/bold]
  "Show carrier performance comparison"
  "What's the SLA compliance rate?"
  "Show low stock inventory items"

[bold]Commands[/bold]
  /help       Show this help message
  /status     Re-check API health status
  /history    Show recent queries from this session
  /reasoning  Toggle the per-turn reasoning panel
  /exit       Exit the assistant
"""


class InteractiveCLI:
    """Rich interactive CLI for the Supply Chain Ops Assistant."""

    def __init__(self) -> None:
        self.console = Console()
        self.copilot: Copilot | None = None
        self.history: list[str] = []
        self.show_reasoning: bool = True

    async def _check_health(self) -> dict[str, bool]:
        """Ping each API /health endpoint and return a service-name -> healthy mapping."""
        client = OpsClient()
        try:
            oms, wms, tms = await asyncio.gather(
                client.check_health("oms"),
                client.check_health("wms"),
                client.check_health("tms"),
            )
            return {"OMS": oms, "WMS": wms, "TMS": tms}
        finally:
            await client.aclose()

    def _display_health(self, health: dict[str, bool]) -> None:
        """Print health status for each service."""
        for service, healthy in health.items():
            if healthy:
                self.console.print(f"  [green]\u2713[/green] {service} — operational")
            else:
                self.console.print(f"  [red]\u2717[/red] {service} — not responding")

        if all(health.values()):
            self.console.print(
                "\n[green]All systems operational.[/green] "
                "Type your question or [bold]/help[/bold] for examples."
            )
        else:
            down = [s for s, h in health.items() if not h]
            self.console.print(
                f"\n[yellow]Warning: {', '.join(down)} not responding. "
                "Some queries may be limited.[/yellow]"
            )

    async def startup(self) -> None:
        """Print banner and run health check."""
        self.console.print(
            Panel(
                "[bold]Supply Chain Ops Assistant[/bold]",
                style="bold blue",
                expand=False,
            )
        )
        self.console.print("[dim]Checking system health...[/dim]")
        health = await self._check_health()
        self._display_health(health)
        self.console.print()

    async def run(self) -> None:
        """Main prompt loop."""
        async with Copilot() as copilot:
            self.copilot = copilot
            await self.startup()
            while True:
                try:
                    query = self.console.input("[bold cyan]ops-copilot > [/]")
                    if not query.strip():
                        continue
                    self.history.append(query.strip())
                    await self.handle_input(query.strip())
                except KeyboardInterrupt:
                    self.console.print("\nGoodbye!")
                    break
                except EOFError:
                    self.console.print("\nGoodbye!")
                    break

    async def handle_input(self, query: str) -> None:
        """Route input to command handler or query handler."""
        if query.startswith("/"):
            await self.handle_command(query)
        else:
            await self.handle_query(query)

    async def handle_command(self, cmd: str) -> None:
        """Handle slash commands: /help, /status, /history, /exit."""
        command = cmd.strip().lower()

        if command == "/help":
            self.console.print(_HELP_TEXT)

        elif command == "/status":
            self.console.print("[dim]Checking system health...[/dim]")
            health = await self._check_health()
            self._display_health(health)

        elif command == "/history":
            if not self.history:
                self.console.print("[dim]No queries in this session yet.[/dim]")
            else:
                recent = self.history[-10:]
                self.console.print("[bold]Recent queries:[/bold]")
                for i, q in enumerate(recent, 1):
                    self.console.print(f"  {i}. {q}")

        elif command == "/reasoning":
            self.show_reasoning = not self.show_reasoning
            state = "on" if self.show_reasoning else "off"
            self.console.print(f"[dim]Reasoning panel {state}.[/dim]")

        elif command == "/exit":
            self.console.print("Goodbye!")
            raise SystemExit(0)

        else:
            self.console.print(
                f"[yellow]Unknown command: {cmd}[/yellow]. "
                "Type [bold]/help[/bold] for available commands."
            )

    async def handle_query(self, query: str) -> None:
        """Process a natural-language query through the copilot."""
        if self.copilot is None:
            self.console.print("[red]Copilot not initialized.[/red]")
            return

        with self.console.status("[bold cyan]Thinking...[/bold cyan]"):
            try:
                result = await self.copilot.process_query(query)
            except Exception as exc:
                logger.exception("Query processing failed")
                self.console.print(f"[red]Error: {exc}[/red]")
                return

        status = result.get("status", "error")
        message = result.get("message", "")

        # Surface the interpret -> route -> validate pipeline for the turn.
        plan = result.get("plan")
        if plan is not None and self.show_reasoning:
            self.console.print(
                render_reasoning_panel(plan, result.get("routing", ""), result.get("errors", []))
            )

        if status == "clarify":
            self.console.print(f"[yellow]{message}[/yellow]")
            return

        if status == "error":
            self.console.print(f"[red]{message}[/red]")
            return

        if status == "flagged":
            self.console.print(f"[yellow]\u26a0 {message}[/yellow]")
        elif result.get("flagged"):
            # Flag-band interpretation behind a report or proposal: warn
            # before anything renders \u2014 and before any confirmation prompt \u2014
            # so the operator knows to double-check the interpretation.
            caveat = EXECUTE_AND_FLAG_RESPONSE.format(
                interpretation=plan.reasoning if plan is not None else message
            )
            self.console.print(f"[yellow]\u26a0 {caveat}[/yellow]")

        if status == "report" and result.get("report") is not None:
            self.console.print(render_report(result["report"]))
            return

        if status == "action_proposed" and result.get("proposal") is not None:
            proposal = result["proposal"]
            if proposal.requires_confirmation:
                confirmed = await prompt_confirmation(proposal)
                if not confirmed:
                    self.console.print(
                        "[yellow]Action cancelled \u2014 nothing was changed.[/yellow]"
                    )
                    return
            else:
                self.console.print(display_action_proposal(proposal))
                self.console.print("[dim]Low risk \u2014 proceeding without confirmation.[/dim]")
            action_result = await self.copilot.execute_confirmed_action(proposal, confirmed=True)
            self.console.print(
                f"[green]\u2713 {len(action_result.successful)}/{action_result.total_targets} "
                f"succeeded[/green] ({action_result.execution_time_ms:.0f}ms)"
            )
            for failure in action_result.failed:
                self.console.print(f"[red]\u2717 {failure['id']}: {failure['error']}[/red]")
            return

        # Format and display the data
        data = result.get("data")
        if data and data.get("partial_failure"):
            for system, err in (data.get("error_details") or {}).items():
                self.console.print(f"[red]✗ {system.upper()} unreachable: {err}[/red]")
        if data and data.get("data"):
            self.console.print(format_query_result(data))
        elif data and data.get("partial_failure"):
            self.console.print(
                "[yellow]No rows returned — results may be incomplete because some "
                "systems did not respond.[/yellow]"
            )
        elif data is not None:
            self.console.print("No results found for that query.")
        else:
            self.console.print(message)


# ===================================================================
# Entry point
# ===================================================================


def main() -> None:
    """Launch the interactive CLI."""
    from config.logging import setup_logging
    from config.settings import get_settings

    setup_logging(get_settings().log_level)
    cli = InteractiveCLI()
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
