"""TMS API service with SQLAlchemy models and endpoints."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Float, ForeignKey, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, selectinload

from models.shared import PaginatedResponse
from models.tms import (
    CarrierStats,
    Shipment,
    ShipmentStatus,
    ShipmentWithTracking,
    SLAStatus,
    SLASummary,
    TrackingEvent,
)
from services.common import apply_filters, build_paginated_response, create_app

# ---------------------------------------------------------------------------
# SQLAlchemy ORM models
# Schema also defined in: models/tms.py (Pydantic). The seeder derives its
# tables from this ORM (Base.metadata), so there is no third copy.
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "tms.db"
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"


class Base(DeclarativeBase):
    pass


class ShipmentORM(Base):
    __tablename__ = "shipments"

    shipment_id: Mapped[str] = mapped_column(String, primary_key=True)
    order_id: Mapped[str] = mapped_column(String)
    carrier: Mapped[str] = mapped_column(String)
    service_level: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    tracking_number: Mapped[str] = mapped_column(String)
    origin_center_id: Mapped[str] = mapped_column(String)
    destination_zip: Mapped[str | None] = mapped_column(String, nullable=True)
    destination_state: Mapped[str | None] = mapped_column(String, nullable=True)
    weight_lbs: Mapped[float] = mapped_column(Float)
    shipping_cost: Mapped[float] = mapped_column(Float)
    label_created_at: Mapped[str] = mapped_column(String)
    estimated_delivery: Mapped[str] = mapped_column(String)
    actual_delivery: Mapped[str | None] = mapped_column(String, nullable=True)
    sla_target: Mapped[str] = mapped_column(String)
    sla_status: Mapped[str] = mapped_column(String)

    tracking_events: Mapped[list[TrackingEventORM]] = relationship(
        back_populates="shipment", lazy="selectin"
    )


class TrackingEventORM(Base):
    __tablename__ = "tracking_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    shipment_id: Mapped[str] = mapped_column(String, ForeignKey("shipments.shipment_id"))
    timestamp: Mapped[str] = mapped_column(String)
    location: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String)

    shipment: Mapped[ShipmentORM] = relationship(back_populates="tracking_events")


# ---------------------------------------------------------------------------
# Database engine & session
# ---------------------------------------------------------------------------

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Patch request models
# ---------------------------------------------------------------------------


class ShipmentPatch(BaseModel):
    status: ShipmentStatus | None = None
    sla_status: SLAStatus | None = None
    actual_delivery: datetime | None = None
    estimated_delivery: datetime | None = None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = create_app("tms")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/shipments", response_model=PaginatedResponse[Shipment])
async def list_shipments(
    carrier: str | None = None,
    status: str | None = None,
    sla_status: str | None = None,
    origin_center_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
) -> PaginatedResponse[Shipment]:
    """List shipments with optional filters and pagination."""
    query = select(ShipmentORM)
    count_query = select(func.count()).select_from(ShipmentORM)

    filters = []
    if carrier is not None:
        filters.append(ShipmentORM.carrier == carrier)
    if status is not None:
        filters.append(ShipmentORM.status == status)
    if sla_status is not None:
        filters.append(ShipmentORM.sla_status == sla_status)
    if origin_center_id is not None:
        filters.append(ShipmentORM.origin_center_id == origin_center_id)
    if date_from is not None:
        filters.append(ShipmentORM.label_created_at >= date_from)
    if date_to is not None:
        filters.append(ShipmentORM.label_created_at <= date_to)

    query, count_query = apply_filters(query, count_query, filters)
    return await build_paginated_response(db, query, count_query, Shipment, offset, limit)


@app.get("/shipments/sla-breaches", response_model=PaginatedResponse[Shipment])
async def sla_breaches(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
) -> PaginatedResponse[Shipment]:
    """Shipments where sla_status is 'breached' or 'at_risk'."""
    condition = ShipmentORM.sla_status.in_(["breached", "at_risk"])
    count_query = select(func.count()).select_from(ShipmentORM).where(condition)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = select(ShipmentORM).where(condition).offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.scalars().all()

    return PaginatedResponse[Shipment](
        items=[Shipment.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@app.get("/shipments/by-order/{order_id}", response_model=list[Shipment])
async def shipments_by_order(
    order_id: str,
    db: AsyncSession = Depends(get_session),
) -> list[Shipment]:
    """Return shipments for a specific order."""
    query = select(ShipmentORM).where(ShipmentORM.order_id == order_id)
    result = await db.execute(query)
    rows = result.scalars().all()
    return [Shipment.model_validate(r) for r in rows]


@app.get("/shipments/{shipment_id}", response_model=ShipmentWithTracking)
async def get_shipment(
    shipment_id: str,
    db: AsyncSession = Depends(get_session),
) -> ShipmentWithTracking:
    """Single shipment with tracking events. 404 if not found."""
    query = (
        select(ShipmentORM)
        .options(selectinload(ShipmentORM.tracking_events))
        .where(ShipmentORM.shipment_id == shipment_id)
    )
    result = await db.execute(query)
    shipment = result.scalar_one_or_none()
    if shipment is None:
        raise HTTPException(status_code=404, detail=f"Shipment {shipment_id} not found")

    shipment_data = Shipment.model_validate(shipment)
    events = [TrackingEvent.model_validate(e) for e in shipment.tracking_events]
    return ShipmentWithTracking(**shipment_data.model_dump(), tracking_events=events)


@app.get("/stats/carrier-performance", response_model=list[CarrierStats])
async def carrier_performance(
    db: AsyncSession = Depends(get_session),
) -> list[CarrierStats]:
    """Carrier stats computed via SQL aggregation."""
    # Count on-time (met + on_track) per carrier
    on_time_sub = (
        select(
            ShipmentORM.carrier,
            func.count().label("on_time"),
        )
        .where(ShipmentORM.sla_status.in_(["met", "on_track"]))
        .group_by(ShipmentORM.carrier)
        .subquery()
    )

    query = select(
        ShipmentORM.carrier,
        func.count().label("total_shipments"),
        func.avg(ShipmentORM.shipping_cost).label("avg_cost"),
    ).group_by(ShipmentORM.carrier)

    result = await db.execute(query)
    carrier_rows = result.all()

    on_time_result = await db.execute(select(on_time_sub))
    on_time_map: dict[str, int] = {}
    for row in on_time_result.all():
        on_time_map[row[0]] = row[1]

    # Compute avg transit days: for delivered shipments, diff between actual and label_created
    transit_query = (
        select(
            ShipmentORM.carrier,
            func.avg(
                func.julianday(ShipmentORM.actual_delivery)
                - func.julianday(ShipmentORM.label_created_at)
            ).label("avg_transit_days"),
        )
        .where(ShipmentORM.actual_delivery.isnot(None))
        .group_by(ShipmentORM.carrier)
    )
    transit_result = await db.execute(transit_query)
    transit_map: dict[str, float] = {}
    for row in transit_result.all():
        transit_map[row[0]] = float(row[1]) if row[1] is not None else 0.0

    stats: list[CarrierStats] = []
    for row in carrier_rows:
        carrier_name = row[0]
        total = row[1]
        avg_cost = row[2] or 0.0
        on_time = on_time_map.get(carrier_name, 0)
        on_time_rate = round(on_time / total, 4) if total > 0 else 0.0
        avg_transit = round(transit_map.get(carrier_name, 0.0), 2)

        stats.append(
            CarrierStats(
                carrier=carrier_name,
                on_time_rate=on_time_rate,
                avg_transit_days=avg_transit,
                avg_cost=round(avg_cost, 2),
                total_shipments=total,
            )
        )

    return stats


@app.get("/stats/sla-summary", response_model=SLASummary)
async def sla_summary(
    db: AsyncSession = Depends(get_session),
) -> SLASummary:
    """SLA compliance summary across shipments."""
    query = select(
        func.count().label("total"),
        func.sum(func.iif(ShipmentORM.sla_status == "on_track", 1, 0)).label("on_track"),
        func.sum(func.iif(ShipmentORM.sla_status == "at_risk", 1, 0)).label("at_risk"),
        func.sum(func.iif(ShipmentORM.sla_status == "breached", 1, 0)).label("breached"),
        func.sum(func.iif(ShipmentORM.sla_status == "met", 1, 0)).label("met"),
    ).select_from(ShipmentORM)

    result = await db.execute(query)
    row = result.one()
    total = row[0] or 0
    on_track = row[1] or 0
    at_risk = row[2] or 0
    breached = row[3] or 0
    met = row[4] or 0
    compliance_rate = round((on_track + met) / total, 4) if total > 0 else 0.0

    # By carrier breakdown
    carrier_query = select(
        ShipmentORM.carrier,
        ShipmentORM.sla_status,
        func.count().label("cnt"),
    ).group_by(ShipmentORM.carrier, ShipmentORM.sla_status)

    carrier_result = await db.execute(carrier_query)
    by_carrier: dict[str, dict[str, int]] = {}
    for crow in carrier_result.all():
        carrier_name = crow[0]
        sla_val = crow[1]
        cnt = crow[2]
        if carrier_name not in by_carrier:
            by_carrier[carrier_name] = {}
        by_carrier[carrier_name][sla_val] = cnt

    return SLASummary(
        total_shipments=total,
        on_track=on_track,
        at_risk=at_risk,
        breached=breached,
        met=met,
        compliance_rate=compliance_rate,
        by_carrier=by_carrier,
    )


@app.patch("/shipments/{shipment_id}", response_model=Shipment)
async def update_shipment(
    shipment_id: str,
    body: ShipmentPatch,
    db: AsyncSession = Depends(get_session),
) -> Shipment:
    """Update shipment fields with typed validation."""
    query = select(ShipmentORM).where(ShipmentORM.shipment_id == shipment_id)
    result = await db.execute(query)
    shipment = result.scalar_one_or_none()
    if shipment is None:
        raise HTTPException(status_code=404, detail=f"Shipment {shipment_id} not found")

    for field, value in body.model_dump(exclude_unset=True, mode="json").items():
        setattr(shipment, field, value)

    await db.commit()
    await db.refresh(shipment)
    return Shipment.model_validate(shipment)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8003)
