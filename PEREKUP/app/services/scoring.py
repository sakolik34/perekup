from collections import defaultdict
from decimal import Decimal
from statistics import median

from app.models import DealScore, aware, utcnow
from app.services.description import RuleDescriptionAnalyzer

analyzer = RuleDescriptionAnalyzer()


def normalize(value):
    return (value or "").strip().casefold()


def comparable_listings(target, listings):
    result = []
    for item in listings:
        if item.id == target.id or not item.is_active or item.source != target.source:
            continue
        if (normalize(item.brand), normalize(item.model)) != (
            normalize(target.brand),
            normalize(target.model),
        ):
            continue
        if abs(item.year - target.year) > 2:
            continue
        if (
            target.generation
            and item.generation
            and normalize(target.generation) != normalize(item.generation)
        ):
            continue
        if not target.fuel_type or not target.transmission or target.mileage_km is None:
            continue
        if normalize(target.fuel_type) != normalize(item.fuel_type) or normalize(
            target.transmission
        ) != normalize(item.transmission):
            continue
        if target.engine_volume is None or item.engine_volume is None:
            if normalize(target.fuel_type) not in {"электро", "електро"}:
                continue
        elif abs(target.engine_volume - item.engine_volume) > 0.31:
            continue
        if item.mileage_km is None or abs(item.mileage_km - target.mileage_km) > max(
            40000, target.mileage_km * 0.3
        ):
            continue
        if any(
            r["severity"] == "high" or r["points"] >= 18 for r in analyzer.analyze(item.description)
        ):
            continue
        result.append(item)
    return result


def remove_outliers(items):
    if len(items) < 3:
        return items
    prices = [float(x.price_usd) for x in items]
    center = median(prices)
    mad = median([abs(p - center) for p in prices])
    # Порог 20% защищает одинаковые цены (MAD=0); 3*MAD отсекает явные выбросы.
    threshold = max(3 * mad, center * 0.20)
    return [x for x in items if abs(float(x.price_usd) - center) <= threshold]


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def calculate(target, listings, settings, repair=None, expenses=None):
    old = target.score
    repair = money(
        repair
        if repair is not None
        else old.estimated_repair_cost
        if old
        else settings.default_repair_cost
    )
    expenses = money(
        expenses
        if expenses is not None
        else old.estimated_expenses
        if old
        else settings.default_additional_expenses
    )
    candidates = comparable_listings(target, listings)
    regional = [
        x for x in candidates if target.region and normalize(x.region) == normalize(target.region)
    ]
    cleaned_regional = remove_outliers(regional)
    use_region = len(cleaned_regional) >= settings.min_comparable_listings
    before = regional if use_region else candidates
    analogs = cleaned_regional if use_region else remove_outliers(candidates)
    risks = analyzer.analyze(target.description)
    age_days = max(0, (utcnow() - aware(target.first_seen_at)).days)
    missing = [
        label
        for key, label in [
            ("vin", "VIN"),
            ("mileage_km", "пробег"),
            ("engine_volume", "двигатель"),
            ("transmission", "коробка"),
            ("fuel_type", "топливо"),
            ("city", "город"),
            ("description", "описание"),
        ]
        if getattr(target, key) in (None, "")
    ]
    mileage_risk = (
        12 if target.mileage_km is None else min(20, max(0, (target.mileage_km - 150000) / 10000))
    )
    photo_risk = max(0, 5 - len(target.photos)) * 2
    risk = min(100, sum(x["points"] for x in risks) + len(missing) * 4 + mileage_risk + photo_risk)
    liquidity = min(100, len(candidates) * 8)
    market = (
        money(median([x.price_usd for x in analogs]))
        if len(analogs) >= settings.min_comparable_listings
        else None
    )
    discount = round(float((market - target.price_usd) / market * 100), 2) if market else None
    profit = market - target.price_usd - repair - expenses if market else None
    components = {}
    if market:
        components = {
            "Скидка к рынку (до 30)": round(min(30, max(0, discount) * 1.5), 2),
            "Прибыль относительно цены (до 25)": round(
                min(25, max(0, float(profit / target.price_usd)) * 250), 2
            ),
            "Надёжность выборки (до 15)": round(min(15, len(analogs) * 1.5), 2),
            "Ликвидность: объём предложения (до 10)": round(liquidity * 0.1, 2),
            "Пробег (до 10)": round(max(0, 10 - mileage_risk * 0.5), 2),
            "Свежесть наблюдения (до 10)": round(max(0, 10 - age_days / 3), 2),
            "Штраф за риски и неполные данные": round(-risk * 0.5, 2),
        }
    explanation = {
        "status": "Оценка рассчитана" if market else "Недостаточно данных",
        "comparable_count": len(analogs),
        "required_count": settings.min_comparable_listings,
        "comparable_ids": [x.id for x in analogs],
        "outliers_removed": len(before) - len(analogs),
        "region_preferred": use_region,
        "risks": risks,
        "missing_fields": missing,
        "photo_count": len(target.photos),
        "risk_components": {
            "Фразы": sum(x["points"] for x in risks),
            "Неполные данные": len(missing) * 4,
            "Пробег": mileage_risk,
            "Фотографии": photo_risk,
        },
        "components": components,
        "age_days": age_days,
        "formula": "Медиана аналогов − цена продавца − ремонт − дополнительные расходы",
        "liquidity_note": "Объём похожих предложений — условный показатель, не измеренная скорость продаж.",
    }
    score = old or DealScore()
    score.estimated_market_price = market
    score.discount_percent = discount
    score.estimated_repair_cost = repair
    score.estimated_expenses = expenses
    score.potential_profit = profit
    score.liquidity_score = liquidity
    score.risk_score = round(risk, 2)
    score.total_score = round(max(0, min(100, sum(components.values()))), 2) if market else None
    score.explanation = explanation
    score.calculated_at = utcnow()
    target.score = score
    return score


def recalculate_all(listings, settings):
    groups = defaultdict(list)
    for item in listings:
        groups[(item.source, normalize(item.brand), normalize(item.model))].append(item)
    for group in groups.values():
        for listing in group:
            calculate(listing, group, settings)
