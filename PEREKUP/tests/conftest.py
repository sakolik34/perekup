import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ["LISTING_PROVIDER"] = "mock"
os.environ["IMPORT_ON_STARTUP"] = "false"
os.environ["SCHEDULER_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.models import Base
from app.providers.mock import MockProvider
from app.services.importer import run_import


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        database_url="sqlite://",
        listing_provider="mock",
        import_on_startup=False,
        scheduler_enabled=False,
    )


@pytest.fixture
def factory(tmp_path):
    postgres = os.getenv("TEST_DATABASE_URL")
    if postgres:
        admin = create_engine(postgres)
        schema = "test_" + uuid.uuid4().hex
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(postgres, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = create_engine(
            f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
        )
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()
    if postgres:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def seeded(factory, settings):
    run_import(factory, MockProvider(), settings)
    return factory


@pytest.fixture
def client(seeded, settings, monkeypatch):
    from app import main

    def db():
        with seeded() as session:
            yield session

    monkeypatch.setattr(main, "SessionLocal", seeded)
    monkeypatch.setattr(main, "settings", settings)
    main.app.dependency_overrides[main.get_db] = db
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()
