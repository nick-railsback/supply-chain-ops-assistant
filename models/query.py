"""Query plan, data filter, and query result models."""

from typing import Any

from pydantic import BaseModel, Field

from models.shared import TargetSystem, UserIntent


class DataFilter(BaseModel):
    """Single filter clause for a data query."""

    field: str
    operator: str
    value: Any


class ConfidenceSignals(BaseModel):
    """Named signals the interpreter emits to make confidence explainable.

    Confidence is derived deterministically from these booleans (see
    ``agent.query_interpreter._confidence_from_signals``) rather than being a
    magic number, so the eval's reliability table is interpretable.
    """

    all_filter_fields_known: bool = False
    entity_unambiguous: bool = False
    single_clear_intent: bool = False
    time_reference_resolved: bool = True  # true when no time reference is needed


class QueryPlan(BaseModel):
    """Structured query plan produced by the intent classifier."""

    intent: UserIntent
    target_systems: list[TargetSystem]
    primary_entity: str
    filters: list[DataFilter] = []
    aggregation: str | None = None
    sort_by: str | None = None
    limit: int | None = None
    requires_join: bool = False
    join_key: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str

    # How this plan was produced — observable so a fallback is never silent.
    # One of: "llm" | "llm_repaired" | "rule_based" | "fallback".
    interpretation_source: str = "rule_based"
    confidence_signals: ConfidenceSignals | None = None
    model_confidence: float | None = None  # the model's own self-report, for comparison

    # Observability — populated on the LLM path, None on the rule fallback.
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None


class QueryResult(BaseModel):
    """Result envelope returned after executing a query plan."""

    data: list[dict[str, Any]]
    total_count: int
    systems_queried: list[TargetSystem]
    partial_failure: bool = False
    error_details: dict[str, str] | None = None
