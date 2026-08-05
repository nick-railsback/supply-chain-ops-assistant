"""WMS API service with SQLAlchemy models and endpoints."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, HTTPException, Query
from sqlalchemy import Boolean, Float, Integer, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from models.shared import PaginatedResponse
from models.wms import FulfillmentCenter, InventoryItem, InventoryPatch, StockMovement
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
    # When the row was last written to, whichever field moved. Null on a row
    # that has never been patched, so a seeded value is distinguishable from a
    # changed one -- last_counted_at cannot carry that, since it dates a
    # physical count and a reorder-point change is not one.
    updated_at: Mapped[str | None] = mapped_column(String, nullable=True)


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


@app.patch("/inventory/{inventory_id}", response_model=InventoryItem)
async def update_inventory(
    inventory_id: str,
    body: InventoryPatch,
    session: AsyncSession = Depends(get_session),
) -> InventoryItem:
    """Adjust on-hand count and reorder point, keeping availability derived."""
    result = await session.execute(
        select(InventoryORM).where(InventoryORM.inventory_id == inventory_id)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail=f"Inventory {inventory_id} not found")

    # exclude_unset distinguishes "field absent" from "field sent as null", and
    # absent is what decides whether this patch counts as a stock count below.
    changes = body.model_dump(exclude_unset=True)

    # A field named with no value is a caller error, not a request to leave it
    # alone -- omitting it is how you do that. Dropping it here would answer
    # 200 to a caller who sent a count, having stored nothing and stamped no
    # count, and they would have no way to tell.
    nulled = sorted(field for field, value in changes.items() if value is None)
    if nulled:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Fields {nulled} were sent as null; omit a field to leave it "
                f"unchanged, or give it a value"
            ),
        )

    # Reject before writing anything: a refused patch must leave the row intact.
    new_on_hand = changes.get("quantity_on_hand")
    if new_on_hand is not None and new_on_hand < item.quantity_allocated:
        raise HTTPException(
            status_code=422,
            detail=(
                f"quantity_on_hand {new_on_hand} is below quantity_allocated "
                f"{item.quantity_allocated}; availability cannot be negative"
            ),
        )

    for field, value in changes.items():
        setattr(item, field, value)

    # A count is what moves this field; a reorder-point change is policy, not a count.
    if "quantity_on_hand" in changes:
        item.last_counted_at = datetime.now(UTC).isoformat()

    # Every patch that writes something is dated, the way patch_order dates an
    # order. A reorder-point change stamps no count, so without this it would
    # leave the row indistinguishable from one seeded that way. A body naming
    # no field asked for nothing and is not a mutation to record.
    if changes:
        item.updated_at = datetime.now(UTC).isoformat()

    # Availability is derived, never patched -- recomputed on every accepted patch
    # so GET /inventory/low-stock cannot drift out of sync with on-hand.
    item.quantity_available = item.quantity_on_hand - item.quantity_allocated

    await session.commit()
    await session.refresh(item)
    return InventoryItem.model_validate(item)
