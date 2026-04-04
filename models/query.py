"""Query plan, data filter, and query result models."""

from typing import Any

from pydantic import BaseModel, Field

from models.shared import TargetSystem, UserIntent


class DataFilter(BaseModel):
    """Single filter clause for a data query."""

    field: str
    operator: str
    value: Any


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


class QueryResult(BaseModel):
    """Result envelope returned after executing a query plan."""

    data: list[dict[str, Any]]
    total_count: int
    systems_queried: list[TargetSystem]
    partial_failure: bool = False
    error_details: dict[str, str] | None = None
