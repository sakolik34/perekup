from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import ImportRun, Listing, PriceHistory, utcnow
from app.providers.base import ProviderError
from app.providers.mock import MockProvider
from app.services.importer import ImportBusy, mutation_lock, run_import


class BatchProvider:
    source = "mock"

    def __init__(self, batch):
        self.batch = batch

    def fetch(self):
        return self.batch


def test_import_is_idempotent_and_records_price_changes(factory, settings):
    first = run_import(factory, MockProvider(), settings)
    second = run_import(factory, MockProvider(), settings)
    changed = run_import(factory, MockProvider(1), settings)
    assert first["created"] == 41
    assert second["created"] == second["price_changes"] == 0
    assert changed["price_changes"] == 4
    with factory() as db:
        assert db.scalar(select(func.count(Listing.id))) == 41
        assert db.scalar(select(func.count(PriceHistory.id))) == 45


def test_duplicates_in_same_batch(factory, settings):
    batch = MockProvider().fetch()
    batch.listings.append(batch.listings[0])
    assert run_import(factory, BatchProvider(batch), settings)["created"] == 41


def test_database_unique_constraint(seeded):
    with seeded() as db:
        values = MockProvider().fetch().listings[0].model_dump(exclude={"photos"})
        db.add(Listing(**values))
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize("complete, expected", [(True, False), (False, True)])
def test_only_complete_import_deactivates_old_unseen(seeded, settings, complete, expected):
    with seeded.begin() as db:
        row = db.scalar(select(Listing).where(Listing.external_id == "demo-0-0"))
        row.last_seen_at = utcnow() - timedelta(days=30)
    batch = MockProvider().fetch()
    batch.listings = batch.listings[1:]
    batch.complete = complete
    run_import(seeded, BatchProvider(batch), settings)
    with seeded() as db:
        assert (
            db.scalar(select(Listing).where(Listing.external_id == "demo-0-0")).is_active
            is expected
        )


def test_scope_change_does_not_deactivate(seeded, settings):
    with seeded.begin() as db:
        row = db.scalar(select(Listing).where(Listing.external_id == "demo-0-0"))
        row.last_seen_at = utcnow() - timedelta(days=30)
    batch = MockProvider().fetch()
    batch.listings = []
    batch.scope = "other"
    run_import(seeded, BatchProvider(batch), settings)
    with seeded() as db:
        assert db.scalar(select(func.count(Listing.id)).where(Listing.is_active)) == 41


def test_recent_missing_stays_active(seeded, settings):
    batch = MockProvider().fetch()
    batch.listings = batch.listings[1:]
    run_import(seeded, BatchProvider(batch), settings)
    with seeded() as db:
        assert db.scalar(select(Listing).where(Listing.external_id == "demo-0-0")).is_active


def test_invalid_batch_rolls_back_everything(seeded, settings):
    batch = MockProvider(1).fetch()
    batch.listings[-1].source = "wrong"
    with pytest.raises(ProviderError):
        run_import(seeded, BatchProvider(batch), settings)
    with seeded() as db:
        assert db.scalar(select(func.count(PriceHistory.id))) == 41
        assert db.scalar(select(ImportRun).order_by(ImportRun.id.desc())).status == "failed"


def test_failed_fetch_does_not_change_listings(seeded, settings):
    class Broken:
        source = "mock"

        def fetch(self):
            raise RuntimeError("https://example.com?api_key=SECRET")

    with pytest.raises(ProviderError) as exc:
        run_import(seeded, Broken(), settings)
    assert "SECRET" not in str(exc.value)
    with seeded() as db:
        assert db.scalar(select(func.count(Listing.id)).where(Listing.is_active)) == 41
        assert "SECRET" not in str(
            db.scalar(select(ImportRun).order_by(ImportRun.id.desc())).details
        )


def test_concurrent_import_rejected(factory, settings):
    mutation_lock.acquire()
    try:
        with pytest.raises(ImportBusy):
            run_import(factory, MockProvider(), settings)
    finally:
        mutation_lock.release()


def test_explicit_inactive_and_reactivation(seeded, settings):
    batch = MockProvider().fetch()
    batch.listings[0].is_active = False
    run_import(seeded, BatchProvider(batch), settings)
    with seeded() as db:
        assert not db.scalar(select(Listing).where(Listing.external_id == "demo-0-0")).is_active
    run_import(seeded, MockProvider(), settings)
    with seeded() as db:
        assert db.scalar(select(Listing).where(Listing.external_id == "demo-0-0")).is_active
