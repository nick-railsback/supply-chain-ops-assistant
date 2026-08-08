"""The stuck predicate: whether a case counts as stuck at a given instant."""

from datetime import datetime, timedelta

from models.oms import ExceptionStatus, OrderStatus
from triage.models import TriageCase

STALE_AFTER = timedelta(hours=48)

UNRESOLVED_EXCEPTION_STATUSES = frozenset(
    {ExceptionStatus.OPEN, ExceptionStatus.INVESTIGATING, ExceptionStatus.ESCALATED}
)
TERMINAL_ORDER_STATUSES = frozenset({OrderStatus.DELIVERED, OrderStatus.CANCELLED})


def is_stuck(case: TriageCase, at: datetime) -> bool:
    order = case.order
    if order.status in TERMINAL_ORDER_STATUSES:
        return False

    if any(
        exception.status in UNRESOLVED_EXCEPTION_STATUSES
        and (at - exception.created_at) >= STALE_AFTER
        for exception in case.exceptions
    ):
        return True

    if order.promised_delivery_date is not None and order.promised_delivery_date < at:
        return True

    last_touched = order.updated_at or order.created_at
    return (at - last_touched) >= STALE_AFTER
