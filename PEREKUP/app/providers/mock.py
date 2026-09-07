from decimal import Decimal

from app.providers.base import ImportBatch, ListingData, ListingProvider

PHOTO_SETS = {
    "Volkswagen": ["golf-front", "golf-rear"],
    "Skoda": ["octavia-front", "octavia-rear"],
    "Renault": ["megane-front"],
    "Toyota": ["camry-front"],
    "Mazda": ["mazda-front"],
}


def demo_photos(brand, variant=0):
    names = PHOTO_SETS[brand]
    offset = variant % len(names)
    return [f"/static/cars/{name}.jpg" for name in names[offset:] + names[:offset]]


class MockProvider(ListingProvider):
    source = "mock"

    def __init__(self, price_revision: int = 0):
        self.price_revision = price_revision

    def fetch(self):
        cars = []
        groups = [
            (
                "Volkswagen",
                "Golf",
                "VII",
                2016,
                12800,
                "Бензин",
                1.4,
                "Автомат",
                "Киев",
                "Киевская",
            ),
            ("Skoda", "Octavia", "A7", 2017, 14200, "Дизель", 2.0, "Автомат", "Львов", "Львовская"),
            (
                "Renault",
                "Megane",
                "IV",
                2018,
                13300,
                "Дизель",
                1.5,
                "Механика",
                "Одесса",
                "Одесская",
            ),
            (
                "Toyota",
                "Camry",
                "XV50",
                2015,
                16900,
                "Бензин",
                2.5,
                "Автомат",
                "Днепр",
                "Днепропетровская",
            ),
        ]
        for g, (
            brand,
            model,
            generation,
            year,
            price,
            fuel,
            engine,
            gearbox,
            city,
            region,
        ) in enumerate(groups):
            for i in range(10):
                multiplier = [0.77, 0.86, 0.96, 0.99, 1, 1.02, 1.04, 1.06, 1.09, 2.8][i]
                description = "Тестовое объявление. Регулярное обслуживание, сервисная история. Осмотр на СТО приветствуется."
                if i == 1:
                    description += " После ДТП, требует ремонта."
                if i == 8:
                    description += " Торг у капота."
                cars.append(
                    ListingData(
                        external_id=f"demo-{g}-{i}",
                        source=self.source,
                        title=f"{brand} {model} {generation}",
                        brand=brand,
                        model=model,
                        generation=generation,
                        year=year + (i % 3 - 1),
                        price_usd=Decimal(
                            round(
                                price * multiplier - (300 if i == 0 and self.price_revision else 0)
                            )
                        ),
                        mileage_km=125000 + i * 4000,
                        city=city,
                        region=region,
                        fuel_type=fuel,
                        engine_volume=engine,
                        transmission=gearbox,
                        drive_type="Передний",
                        description=description,
                        seller_type="Частное лицо",
                        photos=demo_photos(brand, i) if i != 8 else [],
                    )
                )
        cars.append(
            ListingData(
                external_id="demo-rare",
                source=self.source,
                title="Mazda MX-5 ND",
                brand="Mazda",
                model="MX-5",
                generation="ND",
                year=2020,
                price_usd=23000,
                mileage_km=45000,
                city="Киев",
                region="Киевская",
                fuel_type="Бензин",
                engine_volume=2,
                transmission="Механика",
                description="Редкая модель в тестовой выборке: аналогов недостаточно.",
                photos=demo_photos("Mazda"),
            )
        )
        return ImportBatch(cars)
