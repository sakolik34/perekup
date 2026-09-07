"""Запуск: python -m scripts.seed [--with-history]."""

import argparse

from app.config import get_settings
from app.db import SessionLocal
from app.providers.mock import MockProvider
from app.services.importer import run_import


def main():
    parser = argparse.ArgumentParser(description="Заполнить базу демонстрационными автомобилями")
    parser.add_argument(
        "--with-history", action="store_true", help="Создать изменения четырёх тестовых цен"
    )
    args = parser.parse_args()
    settings = get_settings()
    if settings.listing_provider != "mock":
        parser.error("Команда предназначена для LISTING_PROVIDER=mock")
    if args.with_history:
        print(run_import(SessionLocal, MockProvider(1), settings))
    print(run_import(SessionLocal, MockProvider(), settings))


if __name__ == "__main__":
    main()
