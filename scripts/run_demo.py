"""Scripted demo walking through key scenarios.

Usage:
    python scripts/run_demo.py
    make demo
"""

from __future__ import annotations

import asyncio
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent.copilot import Copilot
from services.client import OpsClient

console = Console()


async def check_services() -> bool:
    """Verify all three backend services are running."""
    console.print("\n[bold]Checking service health...[/bold]\n")
    client = OpsClient()
    try:
        results = await asyncio.gather(
            client.check_health("oms"),
            client.check_health("wms"),
            client.check_health("tms"),
        )
        names = ["OMS", "WMS", "TMS"]
        all_healthy = True
        for name, healthy in zip(names, results):
            if healthy:
                console.print(f"  [green]\u2713[/green] {name} — operational")
            else:
                console.print(f"  [red]\u2717[/red] {name} — not responding")
                all_healthy = False

        if not all_healthy:
            down = [n for n, h in zip(names, results) if not h]
            console.print(
                f"\n[red]Error:[/red] {', '.join(down)} not responding. "
                "Start services with: make serve"
            )
        return all_healthy
    finally:
        await client.aclose()


async def run_scenario(
    copilot: Copilot, title: str, query: str, explanation: str
) -> None:
    """Run a single demo scenario and display results."""
    console.print(f"\n{'=' * 60}")
    console.print(f"[bold cyan]{title}[/bold cyan]")
    console.print(f"{'=' * 60}")
    console.print(f"\n[dim]Query:[/dim] [yellow]{query}[/yellow]\n")

    result = await copilot.process_query(query)

    status = result["status"]
    if status == "success":
        data = result.get("data", {})
        items = data.get("data", [])
        total = data.get("total_count", len(items))

        console.print(f"[green]Status:[/green] {status} ({total} result(s))")

        if items:
            table = Table(show_header=True, header_style="bold")
            # Use keys from first item as columns (limit to 6)
            cols = list(items[0].keys())[:6]
            for col in cols:
                table.add_column(col)
            for item in items[:5]:
                table.add_row(*[str(item.get(c, ""))[:30] for c in cols])
            if len(items) > 5:
                table.add_row(*["..." for _ in cols])
            console.print(table)
    elif status == "clarify":
        console.print("[yellow]Status:[/yellow] clarification needed")
        console.print(result.get("message", ""))
    else:
        console.print(f"[bold]{status}[/bold]: {result.get('message', '')}")

    console.print(f"\n[dim]{explanation}[/dim]")


async def main() -> None:
    """Run the full demo walkthrough."""
    console.print(
        Panel(
            "[bold]Supply Chain Ops Assistant — Demo Walkthrough[/bold]\n\n"
            "This demo showcases the copilot's key capabilities:\n"
            "natural language queries, cross-system data, and contextual suggestions.",
            title="Demo",
            border_style="cyan",
        )
    )

    if not await check_services():
        sys.exit(1)

    console.print("\n[bold green]All services operational. Starting demo...[/bold green]")

    async with Copilot() as copilot:
        # Scenario 1: Simple order lookup
        await run_scenario(
            copilot,
            "Scenario 1: Order Status Check",
            "what orders are pending",
            "The copilot matched the 'pending orders' regex pattern and queried OMS "
            "with a status=pending filter. (Note: a generic 'show me ... orders' "
            "phrasing matches the broader pattern first and would NOT apply the "
            "filter — the kind of gap the LLM interpreter closes; see evals/.)",
        )

        # Scenario 2: Exception tracking
        await run_scenario(
            copilot,
            "Scenario 2: Exception Tracking",
            "list all exceptions",
            "Matched the 'exceptions' pattern and queried OMS exception endpoints.",
        )

        # Scenario 3: Inventory check
        await run_scenario(
            copilot,
            "Scenario 3: Low Stock Alert",
            "show low-stock items",
            "Matched 'low-stock' pattern, queried WMS for items below reorder point.",
        )

        # Scenario 4: Cross-system query
        await run_scenario(
            copilot,
            "Scenario 4: Cross-System Query",
            "correlate orders with shipments",
            "Matched the cross-system pattern (a 'show ... orders' phrasing would "
            "match the single-system pattern first), queried both OMS and TMS "
            "concurrently, and joined results on order_id.",
        )

        # Scenario 5: Ambiguous query (triggers clarification)
        await run_scenario(
            copilot,
            "Scenario 5: Contextual Clarification",
            "what happened today?",
            "No pattern matched. The copilot provides contextual suggestions "
            "based on its supported capabilities.",
        )

    console.print(
        Panel(
            "[bold green]Demo complete![/bold green]\n\n"
            "The copilot demonstrated:\n"
            "  1. Rule-based query understanding (keyword/regex)\n"
            "  2. Cross-system data joining\n"
            "  3. Contextual clarification suggestions\n\n"
            "These ran offline on the rule-based interpreter. A Claude interpreter "
            "(being hardened to tool-use) is attempted when ANTHROPIC_API_KEY is set "
            "— see evals/ for the measured rule-vs-LLM accuracy gap.",
            title="Summary",
            border_style="green",
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
