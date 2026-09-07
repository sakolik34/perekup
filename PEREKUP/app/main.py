import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import DealScore, ImportRun, Listing, aware, utcnow
from app.providers.base import ProviderError
from app.providers.mock import MockProvider
from app.schemas import CalculateRequest, ListingFilters
from app.services.importer import (
    ImportBusy,
    database_lock,
    load_listings,
    mutation_lock,
    run_import,
)
from app.services.scoring import calculate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
settings = get_settings()
ROOT = Path(__file__).parent
DB = Annotated[Session, Depends(get_db)]


def provider():
    if settings.listing_provider == "autoria":
        from app.providers.autoria import AutoRiaProvider

        return AutoRiaProvider(settings)
    if settings.listing_provider == "rst":
        from app.providers.rst import RstProvider

        return RstProvider()
    return MockProvider()


def scheduled_import():
    try:
        run_import(SessionLocal, provider(), settings)
    except (ProviderError, ImportBusy):
        logging.getLogger(__name__).warning("Scheduled import did not complete; see import status")


@asynccontextmanager
async def lifespan(app):
    with SessionLocal() as db:
        db.execute(select(Listing.id).limit(1))
    scheduler = BackgroundScheduler(timezone="UTC")
    if settings.scheduler_enabled:
        scheduler.add_job(
            scheduled_import,
            "interval",
            minutes=settings.import_interval_minutes,
            id="listing_import",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        scheduler.start()
    task = (
        asyncio.create_task(asyncio.to_thread(scheduled_import))
        if settings.import_on_startup
        else None
    )
    yield
    if scheduler.running:
        await asyncio.to_thread(scheduler.shutdown, wait=True)
    if task:
        await task


app = FastAPI(
    title="ПЕРЕКУП · API",
    version="0.1.0",
    lifespan=lifespan,
    description="Предварительная оценка объявлений для личной проверки. Не гарантия дохода.",
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


@app.middleware("http")
async def same_origin_writes(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method == "POST" and origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse(
            {"detail": "Запрос разрешён только со страницы приложения"}, status_code=403
        )
    return await call_next(request)


def serialize_score(score):
    if not score:
        return None
    result = {
        c.name: getattr(score, c.name)
        for c in DealScore.__table__.columns
        if c.name not in {"id", "listing_id"}
    }
    for key in (
        "estimated_market_price",
        "estimated_repair_cost",
        "estimated_expenses",
        "potential_profit",
    ):
        result[key] = float(result[key]) if result[key] is not None else None
    result["calculated_at"] = aware(score.calculated_at).isoformat()
    return result


def serialize_listing(item, detail=False):
    result = {
        c.name: getattr(item, c.name) for c in Listing.__table__.columns if c.name != "import_scope"
    }
    result["price_usd"] = float(item.price_usd)
    for key in ("first_seen_at", "last_seen_at", "created_at", "updated_at"):
        result[key] = aware(result[key]).isoformat()
    result["photos"] = [p.photo_url for p in item.photos]
    result["score"] = serialize_score(item.score)
    if detail:
        result["price_history"] = [
            {"price_usd": float(p.price_usd), "recorded_at": aware(p.recorded_at).isoformat()}
            for p in item.price_history
        ]
    return result


def get_listing(db, listing_id):
    item = db.scalar(
        select(Listing)
        .where(Listing.id == listing_id)
        .options(selectinload(Listing.photos), selectinload(Listing.score))
    )
    if not item:
        raise HTTPException(404, "Объявление не найдено")
    return item


@app.get("/api/listings")
def listings(filters: Annotated[ListingFilters, Query()], db: DB):
    statement = (
        select(Listing)
        .outerjoin(DealScore)
        .where(Listing.is_active.is_(True), Listing.source == settings.listing_provider)
    )
    for field in ("brand", "model", "fuel_type", "transmission"):
        value = getattr(filters, field)
        if value:
            statement = statement.where(getattr(Listing, field) == value)
    for value, column, lower in [
        (filters.year_from, Listing.year, True),
        (filters.year_to, Listing.year, False),
        (filters.price_from, Listing.price_usd, True),
        (filters.price_to, Listing.price_usd, False),
        (filters.mileage_max, Listing.mileage_km, False),
        (filters.discount_min, DealScore.discount_percent, True),
        (filters.profit_min, DealScore.potential_profit, True),
        (filters.risk_max, DealScore.risk_score, False),
    ]:
        if value is not None:
            statement = statement.where(column >= value if lower else column <= value)
    if filters.q:
        term = filters.q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(Listing.title.ilike(f"%{term}%", escape="\\"))
    if filters.location:
        term = filters.location.replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(
            or_(
                Listing.city.ilike(f"%{term}%", escape="\\"),
                Listing.region.ilike(f"%{term}%", escape="\\"),
            )
        )
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    ordering = {
        "profit": DealScore.potential_profit.desc().nulls_last(),
        "price": Listing.price_usd.asc(),
        "date": Listing.first_seen_at.desc(),
        "score": DealScore.total_score.desc().nulls_last(),
    }
    items = db.scalars(
        statement.order_by(ordering[filters.sort], Listing.id)
        .offset((filters.page - 1) * filters.page_size)
        .limit(filters.page_size)
        .options(selectinload(Listing.photos), selectinload(Listing.score))
    ).all()
    return {
        "items": [serialize_listing(x) for x in items],
        "total": total,
        "page": filters.page,
        "page_size": filters.page_size,
    }


@app.get("/api/listings/{listing_id}")
def listing_detail(listing_id: int, db: DB):
    item = get_listing(db, listing_id)
    result = serialize_listing(item, detail=True)
    ids = item.score.explanation.get("comparable_ids", []) if item.score else []
    comparables = (
        db.scalars(
            select(Listing)
            .where(Listing.id.in_(ids), Listing.is_active.is_(True))
            .options(selectinload(Listing.photos), selectinload(Listing.score))
        ).all()
        if ids
        else []
    )
    result["comparables"] = [serialize_listing(x) for x in comparables]
    return result


@app.post("/api/import")
def import_listings():
    try:
        return run_import(SessionLocal, provider(), settings)
    except ImportBusy as exc:
        raise HTTPException(409, str(exc)) from None
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from None


@app.post("/api/listings/{listing_id}/calculate")
def calculate_listing(listing_id: int, payload: CalculateRequest, db: DB):
    if not mutation_lock.acquire(blocking=False):
        raise HTTPException(409, "Дождитесь завершения импорта или пересчёта")
    try:
        database_lock(db)
        item = get_listing(db, listing_id)
        calculate(
            item, load_listings(db), settings, payload.repair_cost, payload.additional_expenses
        )
        db.commit()
        return serialize_score(item.score)
    except ImportBusy as exc:
        raise HTTPException(409, str(exc)) from None
    finally:
        mutation_lock.release()


@app.get("/api/stats")
def stats(db: DB):
    base = (Listing.is_active.is_(True), Listing.source == settings.listing_provider)
    active = db.scalar(select(func.count(Listing.id)).where(*base))
    new = db.scalar(
        select(func.count(Listing.id)).where(
            *base, Listing.first_seen_at >= utcnow() - timedelta(days=1)
        )
    )
    deals = db.scalar(
        select(func.count(Listing.id))
        .join(DealScore)
        .where(
            *base,
            DealScore.potential_profit > 0,
            DealScore.discount_percent >= 10,
            DealScore.risk_score <= 40,
        )
    )
    latest = db.scalar(
        select(ImportRun)
        .where(ImportRun.source == settings.listing_provider)
        .order_by(ImportRun.id.desc())
        .limit(1)
    )
    successful = db.scalar(
        select(func.max(ImportRun.finished_at)).where(
            ImportRun.source == settings.listing_provider, ImportRun.status == "success"
        )
    )
    facets = {}
    for key in ("brand", "model", "city", "region", "fuel_type", "transmission"):
        column = getattr(Listing, key)
        facets[key] = list(
            db.scalars(select(column).where(*base, column.is_not(None)).distinct().order_by(column))
        )
    models_by_brand = {}
    for brand, model in db.execute(
        select(Listing.brand, Listing.model).where(*base).distinct().order_by(Listing.model)
    ):
        models_by_brand.setdefault(brand, []).append(model)
    return {
        "models_by_brand": models_by_brand,
        "active": active,
        "new_today": new,
        "potential_deals": deals,
        "provider": settings.listing_provider,
        "last_updated": aware(successful).isoformat() if successful else None,
        "import_running": mutation_lock.locked(),
        "interval_minutes": settings.import_interval_minutes,
        "last_import": {"status": latest.status, "details": latest.details} if latest else None,
        "facets": facets,
    }


@app.get("/health")
def health(db: DB):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}
    except Exception:
        return JSONResponse({"status": "error", "database": "unavailable"}, status_code=503)


@app.get("/", include_in_schema=False)
def index(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={"provider": settings.listing_provider}
    )


@app.get("/listings/{listing_id}", include_in_schema=False)
def detail_page(request: Request, listing_id: int, db: DB):
    get_listing(db, listing_id)
    return templates.TemplateResponse(
        request=request,
        name="detail.html",
        context={"listing_id": listing_id, "provider": settings.listing_provider},
    )


@app.get("/guide", include_in_schema=False)
def guide(request: Request):
    import json

    credits = json.loads((ROOT / "static/cars/credits.json").read_text())
    return templates.TemplateResponse(
        request=request,
        name="guide.html",
        context={"provider": settings.listing_provider, "credits": credits},
    )


@app.get("/guide/github.md", include_in_schema=False)
def github_guide():
    return FileResponse(
        ROOT.parent / "docs/GITHUB.md",
        media_type="text/markdown; charset=utf-8",
        filename="PEREKUP-GitHub.md",
    )
