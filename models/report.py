"""Report output and report section models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ReportSection(BaseModel):
    """Single section within a generated report."""

    title: str
    content: str
    data_table: list[dict[str, Any]] | None = None
    highlight: str | None = None


class ReportOutput(BaseModel):
    """Complete generated report."""

    report_type: str
    title: str
    generated_at: datetime
    sections: list[ReportSection]
    action_items: list[str] = []
