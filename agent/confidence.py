"""Confidence router with per-intent threshold lookup."""

from enum import StrEnum

from config.settings import get_settings
from models.query import QueryPlan


class RoutingDecision(StrEnum):
    """Routing outcome based on query confidence vs intent threshold."""

    EXECUTE = "execute"
    EXECUTE_AND_FLAG = "execute_and_flag"
    CLARIFY = "clarify"


class ConfidenceRouter:
    """Routes a QueryPlan to an execution strategy based on confidence score.

    Thresholds are per-intent and loaded from application settings:
      - confidence >= auto  -> EXECUTE (proceed without confirmation)
      - confidence >= flag  -> EXECUTE_AND_FLAG (proceed but surface to user)
      - confidence <  flag  -> CLARIFY (ask user for more detail)
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def route(self, plan: QueryPlan) -> RoutingDecision:
        """Determine routing decision for the given query plan."""
        threshold = self.settings.get_threshold(plan.intent.value)

        if plan.confidence >= threshold.auto:
            return RoutingDecision.EXECUTE
        elif plan.confidence >= threshold.flag:
            return RoutingDecision.EXECUTE_AND_FLAG
        else:
            return RoutingDecision.CLARIFY
