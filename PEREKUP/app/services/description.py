import re
from abc import ABC, abstractmethod


class DescriptionAnalyzer(ABC):
    @abstractmethod
    def analyze(self, description: str) -> list[dict]:
        """Возвращает признаки риска, а не заключение о состоянии автомобиля."""


class RuleDescriptionAnalyzer(DescriptionAnalyzer):
    RULES = [
        (
            "high",
            30,
            r"не\s+(?:растаможен\w*|розмитнен\w*)|на\s+запчаст[ьи]н?\w*|арест\w*|арешт\w*|проблем[аыі]?\s+[сзіз]+\s+документ\w*",
        ),
        ("high", 25, r"не\s+на\s+ходу|(?:двигатель|двигун)\s+(?:требует|потребує)\s+ремонт\w*"),
        ("medium", 18, r"(?:после|після)\s+дтп|(?:требует|потребує)\s+ремонт\w*|кредит\w*"),
        ("low", 3, r"торг\s+[уыі]?\s*капота"),
    ]

    def analyze(self, description):
        text = re.sub(r"\s+", " ", description.casefold())
        found = []
        covered = []
        for severity, points, pattern in self.RULES:
            for match in re.finditer(pattern, text):
                if any(a <= match.start() and match.end() <= b for a, b in covered):
                    continue
                # Ближайшее отрицание снижает риск, но не заменяет понимание контекста.
                negated = bool(
                    re.search(
                        r"(?:без|не|нет|немає)\s+$",
                        text[max(0, match.start() - 12) : match.start()],
                    )
                )
                found.append(
                    {
                        "phrase": match.group(),
                        "severity": "low" if negated else severity,
                        "points": 1 if negated else points,
                        "uncertain": True,
                        "note": "Возможно отрицание: проверьте контекст."
                        if negated
                        else "Совпадение фразы; требуется проверка.",
                    }
                )
                covered.append(match.span())
        return found
