"""Supply Chain Ops Assistant copilot orchestrator.

Provides the ``Copilot`` class that orchestrates query interpretation,
confidence routing, validation, and execution.  Also contains the
module-level ``execute_query`` function that dispatches a ``QueryPlan``
to the appropriate ``OpsClient`` methods.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent.confidence import ConfidenceRouter, RoutingDecision
from agent.query_interpreter import _suggest_alternatives, _summarize_plan, interpret_query
from agent.validators import validate_query_plan
from config.prompts import (
    CLARIFICATION_RESPONSE,
    EXECUTE_AND_FLAG_RESPONSE,
)
from config.settings import get_settings
from models.action import ActionProposal, ActionResult
from models.query import DataFilter, QueryPlan, QueryResult
from models.report import ReportOutput
from models.shared import TargetSystem, UserIntent
from services.client import OpsClient

logger = logging.getLogger(__name__)

# Max conversation turns retained
_MAX_HISTORY = 5


# ===================================================================
# Copilot class  (Story 6.1)
# ===================================================================


class Copilot:
    """Orchestrates the full query-to-result lifecycle.

    Usage::

        async with Copilot() as copilot:
            result = await copilot.process_query("show pending orders")
    """

    def __init__(self, client: OpsClient | None = None) -> None:
        self._owns_client = client is None
        self.client = client or OpsClient()
        self.conversation_history: list[dict[str, str]] = []
        self._router = ConfidenceRouter()
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Copilot:
        if self._owns_client:
            await self.client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if self._owns_client:
            await self.client.__aexit__(exc_type, exc_val, exc_tb)

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------

    def _update_history(self, role: str, content: str) -> None:
        """Append an exchange and trim to the last *_MAX_HISTORY* entries."""
        self.conversation_history.append({"role": role, "content": content})
        if len(self.conversation_history) > _MAX_HISTORY:
            self.conversation_history = self.conversation_history[-_MAX_HISTORY:]

    # ------------------------------------------------------------------
    # Main orchestration
    # ------------------------------------------------------------------

    async def process_query(self, user_query: str) -> dict[str, Any]:
        """Full pipeline: interpret -> route -> validate -> execute.

        Returns a dict with keys:
          - ``status``: one of "success", "partial", "report",
            "action_proposed", "clarify", "flagged", "error"
          - ``data``: the query result payload (when executed)
          - ``report``: a ReportOutput when status is "report", else None
          - ``proposal``: an ActionProposal when status is "action_proposed",
            else None
          - ``plan``: the interpreted QueryPlan
          - ``routing``: the RoutingDecision value
          - ``message``: human-readable response string
          - ``errors``: validation error list (if any)
        """
        self._update_history("user", user_query)

        # 1. Interpret
        plan = await interpret_query(user_query, self.conversation_history)

        # 2. Route
        decision = self._router.route(plan)

        # 3. Handle clarification
        if decision == RoutingDecision.CLARIFY:
            suggestions = _suggest_alternatives(user_query)
            options_text = "\n".join(f"  - {s}" for s in suggestions)
            message = CLARIFICATION_RESPONSE.format(options=options_text)
            self._update_history("assistant", message)
            return {
                "status": "clarify",
                "plan": plan,
                "routing": decision.value,
                "message": message,
                "data": None,
                "report": None,
                "proposal": None,
                "errors": [],
            }

        # 4. Validate
        errors = await validate_query_plan(plan)
        if errors:
            msg = "Validation failed: " + "; ".join(errors)
            self._update_history("assistant", msg)
            return {
                "status": "error",
                "plan": plan,
                "routing": decision.value,
                "message": msg,
                "data": None,
                "report": None,
                "proposal": None,
                "errors": errors,
            }

        # 5. Intent dispatch
        if plan.intent is UserIntent.REPORT:
            from agent.report_generator import generate_report

            report = await generate_report(self.client, user_query)
            self._update_history("assistant", f"generated report: {report.title}")
            return {
                "status": "report",
                "plan": plan,
                "routing": decision.value,
                "message": f"Report generated: {report.title}",
                "data": None,
                "report": report,
                "proposal": None,
                "errors": [],
            }

        if plan.intent is UserIntent.ACTION_REQUEST:
            from agent.action_handler import propose_action

            context = await execute_query(self.client, plan)  # rows the action targets
            try:
                proposal = await propose_action(self.client, user_query, context.data)
            except ValueError as exc:
                msg = str(exc)
                self._update_history("assistant", msg)
                return {
                    "status": "error",
                    "plan": plan,
                    "routing": decision.value,
                    "message": msg,
                    "data": context.model_dump(),
                    "report": None,
                    "proposal": None,
                    "errors": [msg],
                }
            self._update_history("assistant", _summarize_plan(plan))
            return {
                "status": "action_proposed",
                "plan": plan,
                "routing": decision.value,
                "message": proposal.impact_summary,
                "data": context.model_dump(),
                "report": None,
                "proposal": proposal,
                "errors": [],
            }

        result = await execute_query(self.client, plan)

        # 6. Build response
        if decision == RoutingDecision.EXECUTE_AND_FLAG:
            message = EXECUTE_AND_FLAG_RESPONSE.format(interpretation=plan.reasoning)
            status = "flagged"
        elif result.partial_failure:
            failed = ", ".join(sorted((result.error_details or {}).keys()))
            ok = len(result.systems_queried) - len(result.error_details or {})
            message = (
                f"Partial results: {result.total_count} result(s) from {ok} of "
                f"{len(result.systems_queried)} system(s); {failed} did not respond."
            )
            status = "partial"
        else:
            message = f"Query executed successfully. {result.total_count} result(s) returned."
            status = "success"

        # Record the interpretation (not the user-facing message) so the next
        # turn can resolve references like "those" / "the same ones".
        self._update_history("assistant", _summarize_plan(plan))
        return {
            "status": status,
            "plan": plan,
            "routing": decision.value,
            "message": message,
            "data": result.model_dump(),
            "report": None,
            "proposal": None,
            "errors": [],
        }

    async def execute_confirmed_action(
        self, proposal: ActionProposal, *, confirmed: bool
    ) -> ActionResult:
        """Execute a proposal whose confirmation decision was made by the caller.

        Never prompts and never defaults to yes — ``execute_action``'s gate
        raises ``ActionNotConfirmedError`` if an unconfirmed proposal slips in.
        """
        from agent.action_handler import execute_action

        return await execute_action(self.client, proposal, confirmed=confirmed)

    # ------------------------------------------------------------------
    # Action processing
    # ------------------------------------------------------------------

    async def process_action(
        self, user_query: str, relevant_data: dict[str, Any]
    ) -> ActionProposal:
        """Produce an ActionProposal from a user request and context data.

        Delegates to ``propose_action`` which tries LLM first, then falls
        back to keyword-based detection.
        """
        from agent.action_handler import propose_action

        # Convert dict to list of rows for propose_action
        rows = relevant_data.get("items", [relevant_data])
        return await propose_action(self.client, user_query, rows)

    # ------------------------------------------------------------------
    # Report generation
    # ------------------------------------------------------------------

    async def generate_report(self, report_request: str, data: dict[str, Any]) -> ReportOutput:
        """Generate a structured report from a request and data payload.

        Delegates to ``report_generator.generate_report`` which produces
        rule-based reports with optional LLM narrative enrichment.
        """
        from agent.report_generator import generate_report

        return await generate_report(self.client, report_request)


# ===================================================================
# Query execution  (Story 6.5)
# ===================================================================


def _extract_filters(filters: list[DataFilter], target_field: str) -> Any | None:
    """Return the value of the first filter matching *target_field*."""
    for f in filters:
        if f.field == target_field:
            return f.value
    return None


async def _dispatch_single_system(
    client: OpsClient,
    system: TargetSystem,
    entity: str,
    filters: list[DataFilter],
    limit: int | None,
) -> tuple[list[dict[str, Any]], int]:
    """Dispatch a query to a single backend system.

    Returns (items_as_dicts, total_count).
    """
    effective_limit = limit or 50

    if system == TargetSystem.OMS:
        # Check for special at_risk filter
        if _extract_filters(filters, "at_risk"):
            oms_risk = await client.get_at_risk_orders(limit=effective_limit)
            return [item.model_dump() for item in oms_risk.items], oms_risk.total

        if entity == "exception":
            oms_exc = await client.list_exceptions(
                exception_type=_extract_filters(filters, "exception_type"),
                severity=_extract_filters(filters, "severity"),
                status=_extract_filters(filters, "status"),
                date_from=_extract_filters(filters, "date_from"),
                date_to=_extract_filters(filters, "date_to"),
                limit=effective_limit,
            )
            return [item.model_dump() for item in oms_exc.items], oms_exc.total

        # Default: list orders
        oms_orders = await client.list_orders(
            status=_extract_filters(filters, "status"),
            channel=_extract_filters(filters, "channel"),
            customer_tier=_extract_filters(filters, "customer_tier"),
            date_from=_extract_filters(filters, "date_range_start"),
            date_to=_extract_filters(filters, "date_range_end"),
            min_value=_extract_filters(filters, "order_value"),
            limit=effective_limit,
        )
        return [item.model_dump() for item in oms_orders.items], oms_orders.total

    elif system == TargetSystem.WMS:
        # Check for low-stock shortcut
        if _extract_filters(filters, "below_reorder_point"):
            wms_low = await client.get_low_stock(limit=effective_limit)
            return [item.model_dump() for item in wms_low.items], wms_low.total

        wms_inv = await client.list_inventory(
            sku=_extract_filters(filters, "sku"),
            fulfillment_center_id=_extract_filters(filters, "fulfillment_center"),
            category=_extract_filters(filters, "category"),
            limit=effective_limit,
        )
        return [item.model_dump() for item in wms_inv.items], wms_inv.total

    elif system == TargetSystem.TMS:
        # Check for SLA breach shortcut
        sla = _extract_filters(filters, "sla_status")
        if sla == "breached":
            tms_sla = await client.get_sla_breaches(limit=effective_limit)
            return [item.model_dump() for item in tms_sla.items], tms_sla.total

        tms_ship = await client.list_shipments(
            carrier=_extract_filters(filters, "carrier"),
            status=_extract_filters(filters, "shipment_status"),
            sla_status=_extract_filters(filters, "sla_status"),
            date_from=_extract_filters(filters, "date_range_start"),
            date_to=_extract_filters(filters, "date_range_end"),
            limit=effective_limit,
        )
        return [item.model_dump() for item in tms_ship.items], tms_ship.total

    return [], 0


def _correlate_cross_system(
    datasets: dict[str, list[dict[str, Any]]],
    join_key: str,
) -> list[dict[str, Any]]:
    """Join datasets from multiple systems on a shared key.

    Each output row merges fields from all systems that share the same
    join_key value.  System-specific fields are prefixed with the system
    name to avoid collisions (e.g. ``oms_status``, ``tms_carrier``).
    """
    # Index every system's rows by join_key
    indexed: dict[str, dict[str, Any]] = {}

    for system_name, rows in datasets.items():
        for row in rows:
            key_value = row.get(join_key)
            if key_value is None:
                continue
            if key_value not in indexed:
                indexed[key_value] = {join_key: key_value}
            # Prefix fields with system name
            for field, value in row.items():
                if field == join_key:
                    continue
                indexed[key_value][f"{system_name}_{field}"] = value

    return list(indexed.values())


async def execute_query(client: OpsClient, plan: QueryPlan) -> QueryResult:
    """Map a QueryPlan to OpsClient calls and return a QueryResult.

    For single-system queries, calls the appropriate method directly.
    For cross-system queries, dispatches concurrently via asyncio.gather
    and correlates results when ``plan.requires_join`` is True.
    """
    if not plan.target_systems:
        return QueryResult(
            data=[],
            total_count=0,
            systems_queried=[],
        )

    # Single-system fast path
    if len(plan.target_systems) == 1:
        system = plan.target_systems[0]
        try:
            items, total = await _dispatch_single_system(
                client, system, plan.primary_entity, plan.filters, plan.limit
            )
        except Exception as exc:
            logger.error("Query dispatch failed for %s: %s", system.value, exc)
            return QueryResult(
                data=[],
                total_count=0,
                systems_queried=[system],
                partial_failure=True,
                error_details={system.value: str(exc)},
            )

        return QueryResult(
            data=items,
            total_count=total,
            systems_queried=[system],
        )

    # Multi-system concurrent dispatch
    tasks = {
        system: _dispatch_single_system(
            client, system, plan.primary_entity, plan.filters, plan.limit
        )
        for system in plan.target_systems
    }

    results_raw = await asyncio.gather(*tasks.values(), return_exceptions=True)

    all_data: dict[str, list[dict[str, Any]]] = {}
    total = 0
    error_details: dict[str, str] = {}
    partial = False

    for system, raw in zip(tasks.keys(), results_raw):
        if isinstance(raw, BaseException):
            logger.error("Partial failure for %s: %s", system.value, raw)
            error_details[system.value] = str(raw)
            partial = True
        else:
            items, count = raw
            all_data[system.value] = items
            total += count

    # Correlate if join requested
    if plan.requires_join and plan.join_key and len(all_data) > 1:
        merged = _correlate_cross_system(all_data, plan.join_key)
        return QueryResult(
            data=merged,
            total_count=len(merged),
            systems_queried=list(tasks.keys()),
            partial_failure=partial,
            error_details=error_details or None,
        )

    # Otherwise concatenate
    combined: list[dict[str, Any]] = []
    for items in all_data.values():
        combined.extend(items)

    return QueryResult(
        data=combined,
        total_count=total,
        systems_queried=list(tasks.keys()),
        partial_failure=partial,
        error_details=error_details or None,
    )
