import logging
from datetime import timedelta
from threading import Lock

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.models import ImportRun, Listing, ListingPhoto, PriceHistory, aware, utcnow
from app.providers.base import ProviderError
from app.services.scoring import recalculate_all

logger = logging.getLogger(__name__)
mutation_lock = Lock()


class ImportBusy(Exception):
    pass


def database_lock(session):
    if session.bind.dialect.name == "postgresql":
        if not session.scalar(text("SELECT pg_try_advisory_xact_lock(782193004)")):
            raise ImportBusy("Другой процесс уже обновляет объявления")


def load_listings(session):
    return list(
        session.scalars(
            select(Listing).options(selectinload(Listing.photos), selectinload(Listing.score))
        )
    )


def apply_batch(session, batch, source, settings):
    now = utcnow()
    existing = {(x.source, x.external_id): x for x in load_listings(session)}
    created = updated = price_changes = 0
    seen = set()
    for data in batch.listings:
        if data.source != source:
            raise ProviderError("Источник записи не совпадает с провайдером")
        key = (source, data.external_id)
        if key in seen:
            continue
        seen.add(key)
        values = data.model_dump(exclude={"photos"})
        row = existing.get(key)
        if row is None:
            row = Listing(**values, first_seen_at=now, last_seen_at=now, import_scope=batch.scope)
            session.add(row)
            existing[key] = row
            row.price_history.append(PriceHistory(price_usd=data.price_usd, recorded_at=now))
            created += 1
        else:
            if row.price_usd != data.price_usd:
                row.price_history.append(PriceHistory(price_usd=data.price_usd, recorded_at=now))
                price_changes += 1
            for field, value in values.items():
                setattr(row, field, value)
            row.last_seen_at = now
            row.updated_at = now
            row.import_scope = batch.scope
            updated += 1
        if [p.photo_url for p in row.photos] != data.photos:
            row.photos = [
                ListingPhoto(photo_url=url, position=i) for i, url in enumerate(data.photos)
            ]
    deactivated = 0
    if batch.complete:
        cutoff = now - timedelta(days=settings.inactive_after_days)
        for key, row in existing.items():
            if (
                row.source == source
                and row.import_scope == batch.scope
                and key not in seen
                and row.is_active
                and aware(row.last_seen_at) < cutoff
            ):
                row.is_active = False
                deactivated += 1
    session.flush()
    recalculate_all(list(existing.values()), settings)
    return {
        "created": created,
        "updated": updated,
        "price_changes": price_changes,
        "deactivated": deactivated,
        "complete": batch.complete,
        "warnings": list(batch.warnings),
    }


def run_import(factory, provider, settings):
    if not mutation_lock.acquire(blocking=False):
        raise ImportBusy("Импорт или пересчёт уже выполняется")
    started = utcnow()
    logger.info("Import started: source=%s", provider.source)
    try:
        with factory() as session:
            with session.begin():
                database_lock(session)
                if provider.source == "autoria":
                    previous = session.scalar(
                        select(ImportRun)
                        .where(ImportRun.source == "autoria")
                        .order_by(ImportRun.id.desc())
                        .limit(1)
                    )
                    interval = max(3600, settings.import_interval_minutes * 60)
                    if (
                        previous
                        and (started - aware(previous.started_at)).total_seconds() < interval
                    ):
                        raise ImportBusy(
                            "AUTO.RIA: следующий импорт доступен после настроенного интервала (минимум час)."
                        )
                batch = provider.fetch()
                details = apply_batch(session, batch, provider.source, settings)
                session.add(
                    ImportRun(
                        source=provider.source,
                        status="success",
                        started_at=started,
                        finished_at=utcnow(),
                        details=details,
                    )
                )
        logger.info("Import completed: %s", details)
        return details
    except ImportBusy:
        raise
    except Exception as exc:
        # Исключения HTTP-клиента могут содержать URL с ключом; сохраняем только безопасный текст.
        message = (
            str(exc)
            if isinstance(exc, ProviderError)
            else "Ошибка импорта; данные не изменены. Проверьте подключение к БД и формат данных."
        )
        logger.error("Import failed: source=%s type=%s", provider.source, type(exc).__name__)
        try:
            with factory.begin() as session:
                session.add(
                    ImportRun(
                        source=provider.source,
                        status="failed",
                        started_at=started,
                        finished_at=utcnow(),
                        details={"error": message},
                    )
                )
        except Exception:
            logger.error("Could not record import failure")
        raise ProviderError(message) from None
    finally:
        mutation_lock.release()
