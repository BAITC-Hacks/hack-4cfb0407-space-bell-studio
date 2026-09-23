"""Deterministic one-field alternatives for an unsuccessful catalog request."""

from datetime import date, timedelta

from catalog import recommend, validate_request


MIN_DATE = date(2026, 9, 23)
MAX_DATE = date(2026, 12, 31)


def find_nearest_alternative_date(catalog, request):
    """Try +1, -1, +2, -2 days, keeping every other request field fixed."""
    original = validate_request(request)
    if recommend(catalog, original)["status"] != "NO_MATCH":
        return None
    selected = date.fromisoformat(original["date"])
    for distance in range(1, (MAX_DATE - MIN_DATE).days + 1):
        for offset in (distance, -distance):
            candidate_date = selected + timedelta(days=offset)
            if not MIN_DATE <= candidate_date <= MAX_DATE:
                continue
            result = recommend(catalog, dict(original, date=candidate_date.isoformat()))
            if result["status"] == "MATCHED":
                return {
                    "alternative_date": candidate_date.isoformat(),
                    "eligible_count": result["eligible_count"],
                    "up_to_3_candidate_ids": [card["id"] for card in result["cards"]],
                }
    return None


def find_minimum_budget(catalog, request):
    """Try sorted catalog prices above the current budget through recommend()."""
    original = validate_request(request)
    if recommend(catalog, original)["status"] != "NO_MATCH":
        return None
    for price in sorted({row["price_from_kzt"] for row in catalog if row["price_from_kzt"] > original["budget_kzt"]}):
        changed = dict(original, budget_kzt=price)
        result = recommend(catalog, changed)
        if result["status"] == "MATCHED":
            eligible = [row for row in catalog if recommend([row], changed)["status"] == "MATCHED"]
            eligible.sort(key=lambda row: (row["price_from_kzt"], row["id"]))
            return {
                "minimum_budget_kzt": price,
                "candidate_count_at_that_budget": result["eligible_count"],
                "candidate_ids": [row["id"] for row in eligible],
            }
    return None


def with_alternatives(catalog, request, result):
    """Keep the original result and its cards intact; add Plan B only for NO_MATCH."""
    if result["status"] != "NO_MATCH":
        return result
    return dict(result, alternatives={
        "alternative_date": find_nearest_alternative_date(catalog, request),
        "minimum_budget": find_minimum_budget(catalog, request),
    })
