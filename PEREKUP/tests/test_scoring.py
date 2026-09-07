from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from app.models import Listing
from app.providers.mock import MockProvider
from app.services.description import RuleDescriptionAnalyzer
from app.services.importer import load_listings, run_import
from app.services.scoring import calculate, comparable_listings, remove_outliers


def test_outlier_removal_handles_equal_prices():
    rows = [SimpleNamespace(price_usd=p) for p in [10000, 10000, 10000, 10100, 90000]]
    assert len(remove_outliers(rows)) == 4


def test_low_price_is_compared_to_others_not_itself(seeded, settings):
    with seeded() as db:
        rows = load_listings(db)
        target = rows[0]
        score = calculate(target, rows, settings, Decimal(1000), Decimal(400))
        assert target.id not in score.explanation["comparable_ids"]
        assert score.estimated_market_price > target.price_usd
        assert score.potential_profit == score.estimated_market_price - target.price_usd - 1400
        assert 0 <= score.total_score <= 100
        assert score.explanation["outliers_removed"] >= 1
        assert (
            round(max(0, min(100, sum(score.explanation["components"].values()))), 2)
            == score.total_score
        )


def test_rare_model_has_no_fabricated_market(seeded, settings):
    with seeded() as db:
        item = db.scalar(select(Listing).where(Listing.model == "MX-5"))
        assert item.score.estimated_market_price is None
        assert item.score.potential_profit is None
        assert item.score.total_score is None
        assert item.score.explanation["status"] == "Недостаточно данных"


def test_missing_spec_prevents_unreliable_analogs(seeded):
    with seeded() as db:
        rows = load_listings(db)
        target = rows[0]
        target.fuel_type = None
        assert comparable_listings(target, rows) == []


def test_demo_and_real_sources_not_mixed(seeded):
    with seeded() as db:
        rows = load_listings(db)
        target = rows[0]
        target.source = "autoria"
        assert comparable_listings(target, rows) == []


def test_manual_costs_survive_import(seeded, settings):
    with seeded.begin() as db:
        rows = load_listings(db)
        calculate(rows[0], rows, settings, 1234, 678)
    run_import(seeded, MockProvider(1), settings)
    with seeded() as db:
        score = db.scalar(select(Listing).order_by(Listing.id)).score
        assert score.estimated_repair_cost == 1234
        assert score.estimated_expenses == 678


def test_description_russian_ukrainian_and_negation():
    analyzer = RuleDescriptionAnalyzer()
    assert any(r["severity"] == "high" for r in analyzer.analyze("Не розмитнений. На запчастини."))
    assert any(r["severity"] == "medium" for r in analyzer.analyze("Після ДТП, потребує ремонту"))
    assert analyzer.analyze("Без кредита")[0]["points"] == 1
    assert analyzer.analyze("Торг у капота")[0]["severity"] == "low"
    assert analyzer.analyze("Регулярное обслуживание") == []
    assert len(analyzer.analyze("двигатель требует ремонта")) == 1
