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
from models.action import ActionProposal
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


def _detect_data_type(items: list[dict[str, Any]]) -> str:
    """Heuristically detect the entity type from the first item's keys."""
    if not items:
        return "unknown"
    first = items[0]
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
            renderables.append(
                Text(f"  \u26a0 {section.highlight}", style="bold yellow")
            )

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
    renderables.append(
        Text(f"  Targets ({len(proposal.target_ids)}):", style="bold")
    )
    for tid in proposal.target_ids[:20]:
        renderables.append(Text(f"    {tid}"))
    if len(proposal.target_ids) > 20:
        renderables.append(
            Text(f"    ... and {len(proposal.target_ids) - 20} more", style="dim")
        )

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
  /help     Show this help message
  /status   Re-check API health status
  /history  Show recent queries from this session
  /exit     Exit the assistant
"""


class InteractiveCLI:
    """Rich interactive CLI for the Supply Chain Ops Assistant."""

    def __init__(self) -> None:
        self.console = Console()
        self.copilot: Copilot | None = None
        self.history: list[str] = []

    async def _check_health(self) -> dict[str, bool]:
        """Ping each API and return a service-name -> healthy mapping."""
        results: dict[str, bool] = {}
        client = OpsClient()
        try:
            checks = {
                "OMS": client.list_orders(limit=1),
                "WMS": client.list_inventory(limit=1),
                "TMS": client.list_shipments(limit=1),
            }
            outcomes = await asyncio.gather(
                *checks.values(), return_exceptions=True
            )
            for name, outcome in zip(checks.keys(), outcomes):
                results[name] = not isinstance(outcome, BaseException)
        finally:
            await client.aclose()
        return results

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

        if status == "clarify":
            self.console.print(f"[yellow]{message}[/yellow]")
            return

        if status == "error":
            self.console.print(f"[red]{message}[/red]")
            return

        if status == "flagged":
            self.console.print(f"[yellow]\u26a0 {message}[/yellow]")

        # Format and display the data
        data = result.get("data")
        if data:
            formatted = format_query_result(data)
            if isinstance(formatted, str):
                self.console.print(formatted)
            else:
                self.console.print(formatted)
        else:
            self.console.print(message)


# ===================================================================
# Entry point
# ===================================================================


def main() -> None:
    """Launch the interactive CLI."""
    cli = InteractiveCLI()
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
