"""Shared triage definitions: the root-cause taxonomy, the case record, and the stuck predicate."""

from triage.detection import is_stuck
from triage.models import TriageCase
from triage.taxonomy import RootCause

__all__ = ["RootCause", "TriageCase", "is_stuck"]
