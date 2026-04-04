"""Shared pytest fixtures for test databases and mock clients."""

from datetime import UTC, datetime

import pytest

from models.action import ActionProposal, ActionType
from models.query import QueryPlan
from models.report import ReportOutput, ReportSection
from models.shared import RiskLevel, TargetSystem, UserIntent


@pytest.fixture
def sample_query_plan():
    """Factory for QueryPlan objects."""
    def _make(
        intent=UserIntent.STATUS_CHECK,
        target_systems=None,
        confidence=0.85,
        **kwargs,
    ):
        filters = kwargs.pop("filters", [])
        return QueryPlan(
            intent=intent,
            target_systems=target_systems or [TargetSystem.OMS],
            primary_entity="orders",
            filters=filters,
            confidence=confidence,
            reasoning="Test query plan",
            **kwargs,
        )
    return _make


@pytest.fixture
def sample_action_proposal():
    """Factory for ActionProposal objects."""
    def _make(
        action_type=ActionType.UPDATE_EXCEPTION,
        target_ids=None,
        risk_level=RiskLevel.LOW,
        **kwargs,
    ):
        return ActionProposal(
            action_type=action_type,
            target_ids=target_ids or ["EXC-0001"],
            changes={"status": "resolved"},
            reasoning="Test action",
            impact_summary="Test impact",
            risk_level=risk_level,
            **kwargs,
        )
    return _make


@pytest.fixture
def sample_report_output():
    """Factory for ReportOutput objects."""
    def _make(**kwargs):
        return ReportOutput(
            report_type="exception_summary",
            title="Test Report",
            generated_at=datetime.now(UTC),
            sections=[
                ReportSection(
                    title="Test Section",
                    content="Test content",
                )
            ],
            action_items=["Review open exceptions"],
            **kwargs,
        )
    return _make
