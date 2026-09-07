from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class Base(DeclarativeBase):
    pass


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_listing_source_external"),
        Index("ix_listing_comparables", "source", "is_active", "brand", "model", "year"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(30))
    import_scope: Mapped[str] = mapped_column(String(64), default="")
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(250))
    brand: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(100))
    generation: Mapped[str | None] = mapped_column(String(100))
    year: Mapped[int] = mapped_column(Integer)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    mileage_km: Mapped[int | None] = mapped_column(Integer)
    city: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    fuel_type: Mapped[str | None] = mapped_column(String(100))
    engine_volume: Mapped[float | None]
    transmission: Mapped[str | None] = mapped_column(String(100))
    drive_type: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    seller_type: Mapped[str | None] = mapped_column(String(100))
    vin: Mapped[str | None] = mapped_column(String(30))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    photos: Mapped[list["ListingPhoto"]] = relationship(
        cascade="all, delete-orphan", order_by="ListingPhoto.position"
    )
    price_history: Mapped[list["PriceHistory"]] = relationship(
        cascade="all, delete-orphan", order_by="PriceHistory.recorded_at"
    )
    score: Mapped["DealScore | None"] = relationship(cascade="all, delete-orphan", uselist=False)


class ListingPhoto(Base):
    __tablename__ = "listing_photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    photo_url: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)


class PriceHistory(Base):
    __tablename__ = "price_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    price_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DealScore(Base):
    __tablename__ = "deal_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), unique=True
    )
    estimated_market_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    discount_percent: Mapped[float | None]
    estimated_repair_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    estimated_expenses: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    potential_profit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    liquidity_score: Mapped[float]
    risk_score: Mapped[float]
    total_score: Mapped[float | None]
    explanation: Mapped[dict] = mapped_column(JSON)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportRun(Base):
    __tablename__ = "import_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
