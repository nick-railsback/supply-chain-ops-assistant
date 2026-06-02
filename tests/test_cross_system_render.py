"""Regression tests for B3: cross-system results must render populated columns.

Correlated cross-system rows carry system-prefixed keys (``oms_status``,
``tms_carrier``) produced by ``copilot._correlate_cross_system``. Before the
fix the CLI misrouted them to the single-system orders formatter, which reads
unprefixed keys and so rendered blank columns and dropped the joined system
entirely.
"""

from rich.console import Console

from cli.interactive import format_query_result


def _render_to_text(renderable: object) -> str:
    """Render a Rich renderable (or plain string) to text for assertions."""
    console = Console(width=240)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def test_cross_system_result_renders_both_systems():
    """A joined order+shipment row shows fields from OMS and TMS, not just the ID."""
    result = {
        "data": [
            {
                "order_id": "ORD-2025-001",
                "oms_status": "shipped",
                "oms_total_value": 150.0,
                "tms_carrier": "FedEx",
                "tms_shipment_status": "in_transit",
            }
        ],
        "total_count": 1,
    }

    text = _render_to_text(format_query_result(result))

    assert "ORD-2025-001" in text  # join key
    assert "shipped" in text  # OMS-prefixed field
    assert "FedEx" in text  # TMS-prefixed field
