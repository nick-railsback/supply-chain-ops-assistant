"""WMS API service with SQLAlchemy models and endpoints."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path

from fastapi import Depends, Query
from sqlalchemy import Boolean, Float, Integer, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from models.shared import PaginatedResponse
from models.wms import FulfillmentCenter, InventoryItem, StockMovement
from services.common import apply_filters, build_paginated_response, create_app

# ---------------------------------------------------------------------------
# SQLAlchemy ORM models
# Schema also defined in: models/wms.py (Pydantic). The seeder derives its
# tables from this ORM (Base.metadata), so there is no third copy.
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR / 'wms.db'}"


class Base(DeclarativeBase):
    pass


class FulfillmentCenterORM(Base):
    __tablename__ = "fulfillment_centers"

    center_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    region: Mapped[str] = mapped_column(String)
    capacity_units: Mapped[int] = mapped_column(Integer)
    current_utilization: Mapped[float] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class InventoryORM(Base):
    __tablename__ = "inventory"

    inventory_id: Mapped[str] = mapped_column(String, primary_key=True)
    sku: Mapped[str] = mapped_column(String, nullable=False)
    product_name: Mapped[str] = mapped_column(String)
    fulfillment_center_id: Mapped[str] = mapped_column(String)
    quantity_on_hand: Mapped[int] = mapped_column(Integer)
    quantity_allocated: Mapped[int] = mapped_column(Integer)
    quantity_available: Mapped[int] = mapped_column(Integer)
    reorder_point: Mapped[int] = mapped_column(Integer)
    last_counted_at: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)


class StockMovementORM(Base):
    __tablename__ = "stock_movements"

    movement_id: Mapped[str] = mapped_column(String, primary_key=True)
    sku: Mapped[str] = mapped_column(String, nullable=False)
    fulfillment_center_id: Mapped[str] = mapped_column(String)
    movement_type: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer)
    reference_id: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp: Mapped[str] = mapped_column(String)


# ---------------------------------------------------------------------------
# Async engine & session
# ---------------------------------------------------------------------------

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = create_app("wms")

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/inventory/low-stock", response_model=PaginatedResponse[InventoryItem])
async def list_low_stock_inventory(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[InventoryItem]:
    """Return inventory items where quantity_available < reorder_point."""
    condition = InventoryORM.quantity_available < InventoryORM.reorder_point

    total_result = await session.execute(
        select(func.count()).select_from(InventoryORM).where(condition)
    )
    total = total_result.scalar_one()

    rows_result = await session.execute(
        select(InventoryORM).where(condition).offset(offset).limit(limit)
    )
    rows = rows_result.scalars().all()

    return PaginatedResponse[InventoryItem](
        items=[InventoryItem.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@app.get("/inventory", response_model=PaginatedResponse[InventoryItem])
async def list_inventory(
    sku: str | None = Query(None),
    fulfillment_center_id: str | None = Query(None),
    category: str | None = Query(None),
    below_reorder_point: bool | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[InventoryItem]:
    """List inventory with optional filters."""
    stmt = select(InventoryORM)
    count_stmt = select(func.count()).select_from(InventoryORM)

    filters = []
    if sku is not None:
        filters.append(InventoryORM.sku == sku)
    if fulfillment_center_id is not None:
        filters.append(InventoryORM.fulfillment_center_id == fulfillment_center_id)
    if category is not None:
        filters.append(InventoryORM.category == category)
    if below_reorder_point is True:
        filters.append(InventoryORM.quantity_available < InventoryORM.reorder_point)

    stmt, count_stmt = apply_filters(stmt, count_stmt, filters)
    return await build_paginated_response(session, stmt, count_stmt, InventoryItem, offset, limit)


@app.get("/centers", response_model=list[FulfillmentCenter])
async def list_centers(
    session: AsyncSession = Depends(get_session),
) -> list[FulfillmentCenter]:
    """Return all fulfillment centers."""
    result = await session.execute(select(FulfillmentCenterORM))
    rows = result.scalars().all()
    return [FulfillmentCenter.model_validate(r) for r in rows]


@app.get(
    "/centers/{center_id}/inventory",
    response_model=PaginatedResponse[InventoryItem],
)
async def list_center_inventory(
    center_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[InventoryItem]:
    """Return inventory at a specific fulfillment center."""
    condition = InventoryORM.fulfillment_center_id == center_id

    total = (
        await session.execute(select(func.count()).select_from(InventoryORM).where(condition))
    ).scalar_one()

    rows = (
        (await session.execute(select(InventoryORM).where(condition).offset(offset).limit(limit)))
        .scalars()
        .all()
    )

    return PaginatedResponse[InventoryItem](
        items=[InventoryItem.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@app.get("/movements", response_model=PaginatedResponse[StockMovement])
async def list_movements(
    sku: str | None = Query(None),
    fulfillment_center_id: str | None = Query(None),
    movement_type: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> PaginatedResponse[StockMovement]:
    """List stock movements with optional filters."""
    stmt = select(StockMovementORM)
    count_stmt = select(func.count()).select_from(StockMovementORM)

    if sku is not None:
        stmt = stmt.where(StockMovementORM.sku == sku)
        count_stmt = count_stmt.where(StockMovementORM.sku == sku)
    if fulfillment_center_id is not None:
        stmt = stmt.where(StockMovementORM.fulfillment_center_id == fulfillment_center_id)
        count_stmt = count_stmt.where(
            StockMovementORM.fulfillment_center_id == fulfillment_center_id
        )
    if movement_type is not None:
        stmt = stmt.where(StockMovementORM.movement_type == movement_type)
        count_stmt = count_stmt.where(StockMovementORM.movement_type == movement_type)
    if date_from is not None:
        date_from_str = date_from.isoformat()
        stmt = stmt.where(StockMovementORM.timestamp >= date_from_str)
        count_stmt = count_stmt.where(StockMovementORM.timestamp >= date_from_str)
    if date_to is not None:
        date_to_str = date_to.isoformat()
        stmt = stmt.where(StockMovementORM.timestamp <= date_to_str)
        count_stmt = count_stmt.where(StockMovementORM.timestamp <= date_to_str)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.offset(offset).limit(limit))).scalars().all()

    return PaginatedResponse[StockMovement](
        items=[StockMovement.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@app.get("/stats/utilization", response_model=list[FulfillmentCenter])
async def utilization_stats(
    session: AsyncSession = Depends(get_session),
) -> list[FulfillmentCenter]:
    """Return all centers with their current utilization."""
    result = await session.execute(select(FulfillmentCenterORM))
    rows = result.scalars().all()
    return [FulfillmentCenter.model_validate(r) for r in rows]
