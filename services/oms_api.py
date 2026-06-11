"""OMS API service with SQLAlchemy models and endpoints."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Float, ForeignKey, Integer, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from models.oms import (
    DailyStats,
    ExceptionSummary,
    LineItem,
    Order,
    OrderException,
    OrderWithLineItems,
)
from models.shared import PaginatedResponse
from services.common import apply_filters, build_paginated_response, create_app

# ---------------------------------------------------------------------------
# Database path
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_URL = f"sqlite+aiosqlite:///{DATA_DIR / 'oms.db'}"

# ---------------------------------------------------------------------------
# SQLAlchemy ORM models
# Schema also defined in: models/oms.py (Pydantic). The seeder derives its
# tables from this ORM (Base.metadata), so there is no third copy.
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class OrderORM(Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String, nullable=True)
    customer_tier: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str | None] = mapped_column(String, nullable=True)
    promised_delivery_date: Mapped[str | None] = mapped_column(String, nullable=True)
    fulfillment_center_id: Mapped[str | None] = mapped_column(String, nullable=True)
    total_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String, nullable=True)
    line_item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    line_items: Mapped[list[LineItemORM]] = relationship(
        "LineItemORM", back_populates="order", lazy="selectin"
    )


class LineItemORM(Base):
    __tablename__ = "line_items"

    line_item_id: Mapped[str] = mapped_column(String, primary_key=True)
    order_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("orders.order_id"), nullable=True
    )
    sku: Mapped[str] = mapped_column(String, nullable=False)
    product_name: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)

    order: Mapped[OrderORM | None] = relationship("OrderORM", back_populates="line_items")


class OrderExceptionORM(Base):
    __tablename__ = "order_exceptions"

    exception_id: Mapped[str] = mapped_column(String, primary_key=True)
    order_id: Mapped[str | None] = mapped_column(String, nullable=True)
    exception_type: Mapped[str | None] = mapped_column(String, nullable=True)
    severity: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# Async engine & session
# ---------------------------------------------------------------------------
engine = create_async_engine(DB_URL, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Patch request models
# ---------------------------------------------------------------------------


class OrderPatch(BaseModel):
    status: str | None = None
    notes: str | None = None


class ExceptionPatch(BaseModel):
    status: str | None = None
    assigned_to: str | None = None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = create_app("oms")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/orders", response_model=PaginatedResponse[Order])
async def list_orders(
    status: str | None = None,
    channel: str | None = None,
    customer_tier: str | None = None,
    fulfillment_center_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[Order]:
    query = select(OrderORM)
    count_query = select(func.count()).select_from(OrderORM)

    filters = []
    if status is not None:
        filters.append(OrderORM.status == status)
    if channel is not None:
        filters.append(OrderORM.channel == channel)
    if customer_tier is not None:
        filters.append(OrderORM.customer_tier == customer_tier)
    if fulfillment_center_id is not None:
        filters.append(OrderORM.fulfillment_center_id == fulfillment_center_id)
    if date_from is not None:
        filters.append(OrderORM.created_at >= date_from)
    if date_to is not None:
        filters.append(OrderORM.created_at <= date_to)
    if min_value is not None:
        filters.append(OrderORM.total_value >= min_value)
    if max_value is not None:
        filters.append(OrderORM.total_value <= max_value)

    query, count_query = apply_filters(query, count_query, filters)
    return await build_paginated_response(session, query, count_query, Order, offset, limit)


@app.get("/orders/at-risk", response_model=PaginatedResponse[Order])
async def orders_at_risk(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[Order]:
    now = datetime.now(UTC)
    cutoff = (now + timedelta(days=2)).isoformat()
    now_str = now.isoformat()

    excluded = ("shipped", "delivered", "cancelled")

    filters = [
        OrderORM.promised_delivery_date.isnot(None),
        OrderORM.promised_delivery_date <= cutoff,
        OrderORM.promised_delivery_date >= now_str,
        OrderORM.status.notin_(excluded),
    ]

    count_query = select(func.count()).select_from(OrderORM).where(*filters)
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    query = select(OrderORM).where(*filters).offset(offset).limit(limit)
    result = await session.execute(query)
    rows = result.scalars().all()

    items = [Order.model_validate(row) for row in rows]
    return PaginatedResponse[Order](items=items, total=total, offset=offset, limit=limit)


@app.get("/orders/{order_id}", response_model=OrderWithLineItems)
async def get_order(
    order_id: str,
    session: AsyncSession = Depends(get_session),
) -> OrderWithLineItems:
    result = await session.execute(select(OrderORM).where(OrderORM.order_id == order_id))
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    li_result = await session.execute(select(LineItemORM).where(LineItemORM.order_id == order_id))
    line_items_rows = li_result.scalars().all()

    order_data = Order.model_validate(order)
    line_items_data = [LineItem.model_validate(li) for li in line_items_rows]
    return OrderWithLineItems(**order_data.model_dump(), line_items=line_items_data)


@app.get("/exceptions", response_model=PaginatedResponse[OrderException])
async def list_exceptions(
    exception_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[OrderException]:
    query = select(OrderExceptionORM)
    count_query = select(func.count()).select_from(OrderExceptionORM)

    filters = []
    if exception_type is not None:
        filters.append(OrderExceptionORM.exception_type == exception_type)
    if severity is not None:
        filters.append(OrderExceptionORM.severity == severity)
    if status is not None:
        filters.append(OrderExceptionORM.status == status)
    if date_from is not None:
        filters.append(OrderExceptionORM.created_at >= date_from)
    if date_to is not None:
        filters.append(OrderExceptionORM.created_at <= date_to)

    query, count_query = apply_filters(query, count_query, filters)
    return await build_paginated_response(
        session, query, count_query, OrderException, offset, limit
    )


@app.get("/exceptions/summary", response_model=ExceptionSummary)
async def exception_summary(
    session: AsyncSession = Depends(get_session),
) -> ExceptionSummary:
    # By type
    type_q = select(OrderExceptionORM.exception_type, func.count()).group_by(
        OrderExceptionORM.exception_type
    )
    type_result = await session.execute(type_q)
    by_type: dict[str, int] = {
        str(row[0]): int(row[1]) for row in type_result.all() if row[0] is not None
    }

    # By severity
    sev_q = select(OrderExceptionORM.severity, func.count()).group_by(OrderExceptionORM.severity)
    sev_result = await session.execute(sev_q)
    by_severity: dict[str, int] = {
        str(row[0]): int(row[1]) for row in sev_result.all() if row[0] is not None
    }

    # Open vs resolved
    status_q = select(OrderExceptionORM.status, func.count()).group_by(OrderExceptionORM.status)
    status_result = await session.execute(status_q)
    status_counts: dict[str, int] = {
        str(row[0]): int(row[1]) for row in status_result.all() if row[0] is not None
    }

    total_open = sum(
        v for k, v in status_counts.items() if k in ("open", "investigating", "escalated")
    )
    total_resolved = status_counts.get("resolved", 0)

    return ExceptionSummary(
        by_type=by_type,
        by_severity=by_severity,
        total_open=total_open,
        total_resolved=total_resolved,
    )


@app.patch("/orders/{order_id}", response_model=Order)
async def patch_order(
    order_id: str,
    body: OrderPatch,
    session: AsyncSession = Depends(get_session),
) -> Order:
    result = await session.execute(select(OrderORM).where(OrderORM.order_id == order_id))
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    if body.status is not None:
        order.status = body.status
    if body.notes is not None:
        order.notes = body.notes
    order.updated_at = datetime.now(UTC).isoformat()

    await session.commit()
    await session.refresh(order)
    return Order.model_validate(order)


@app.patch("/exceptions/{exception_id}", response_model=OrderException)
async def patch_exception(
    exception_id: str,
    body: ExceptionPatch,
    session: AsyncSession = Depends(get_session),
) -> OrderException:
    result = await session.execute(
        select(OrderExceptionORM).where(OrderExceptionORM.exception_id == exception_id)
    )
    exc = result.scalar_one_or_none()
    if exc is None:
        raise HTTPException(status_code=404, detail=f"Exception {exception_id} not found")

    if body.status is not None:
        exc.status = body.status
        if body.status == "resolved":
            exc.resolved_at = datetime.now(UTC).isoformat()
    if body.assigned_to is not None:
        exc.assigned_to = body.assigned_to

    await session.commit()
    await session.refresh(exc)
    return OrderException.model_validate(exc)


@app.get("/stats/daily", response_model=list[DailyStats])
async def daily_stats(
    days: int = Query(default=7, ge=1, le=90),
    session: AsyncSession = Depends(get_session),
) -> list[DailyStats]:
    today = date.today()
    start_date = today - timedelta(days=days - 1)

    # Fetch all orders in the date range
    start_str = start_date.isoformat()
    end_str = (today + timedelta(days=1)).isoformat()

    order_q = select(OrderORM.created_at, OrderORM.status, OrderORM.total_value).where(
        OrderORM.created_at >= start_str,
        OrderORM.created_at < end_str,
    )
    result = await session.execute(order_q)
    rows = result.all()

    # Exception counts by date
    exc_q = select(OrderExceptionORM.created_at).where(
        OrderExceptionORM.created_at >= start_str,
        OrderExceptionORM.created_at < end_str,
    )
    exc_result = await session.execute(exc_q)
    exc_rows = exc_result.all()

    # Build per-day buckets
    exc_by_day: dict[str, int] = {}
    for (exc_created_at,) in exc_rows:
        if exc_created_at:
            day_key = exc_created_at[:10]
            exc_by_day[day_key] = exc_by_day.get(day_key, 0) + 1

    day_data: dict[str, dict[str, int | float]] = {}
    for created_at, status, total_value in rows:
        if not created_at:
            continue
        day_key = created_at[:10]  # extract YYYY-MM-DD
        if day_key not in day_data:
            day_data[day_key] = {"total_orders": 0, "total_value": 0.0}
        bucket = day_data[day_key]
        bucket["total_orders"] = int(bucket["total_orders"]) + 1
        bucket["total_value"] = float(bucket["total_value"]) + (total_value or 0.0)
        status_key = f"status_{status}"
        bucket[status_key] = int(bucket.get(status_key, 0)) + 1  # type: ignore[arg-type]

    # Build response list for all days in range
    stats_list: list[DailyStats] = []
    for i in range(days):
        d = start_date + timedelta(days=i)
        day_key = d.isoformat()
        bucket = day_data.get(day_key, {})
        total_orders = int(bucket.get("total_orders", 0))
        total_value = float(bucket.get("total_value", 0.0))
        exc_count = exc_by_day.get(day_key, 0)
        exception_rate = exc_count / total_orders if total_orders > 0 else 0.0

        orders_by_status: dict[str, int] = {}
        for k, v in bucket.items():
            if k.startswith("status_"):
                orders_by_status[k[7:]] = int(v)

        stats_list.append(
            DailyStats(
                date=d,
                total_orders=total_orders,
                total_value=round(total_value, 2),
                exception_rate=round(exception_rate, 4),
                orders_by_status=orders_by_status,
            )
        )

    return stats_list
