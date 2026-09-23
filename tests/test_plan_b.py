import unittest
from pathlib import Path

from catalog import load_catalog, recommend
from plan_b import find_minimum_budget, find_nearest_alternative_date, with_alternatives


def profile(identifier, *, price=100, busy=(), event_format="свадьба", language="русский",
            hours=4, city="Алматы", category="Ведущий"):
    return {
        "id": identifier, "anon_name": identifier, "city": city, "categories": [category],
        "price_from_kzt": float(price), "busy_dates": list(busy),
        "event_formats": [event_format], "languages": [language], "max_hours": hours,
        "description": "Проверенное описание профиля для теста.",
        "synthetic": False, "city_imputed": False, "price_imputed": False,
    }


def request(**overrides):
    query = dict(city="Алматы", category="Ведущий", event_format="свадьба",
                 date="2026-10-10", budget_kzt=100, language="русский", hours=3)
    query.update(overrides)
    return query


class PlanBTests(unittest.TestCase):
    def test_date_preserves_all_other_fields_and_is_a_real_match(self):
        original = request()
        rows = [profile("busy", busy=["2026-10-10"])]
        self.assertEqual("NO_MATCH", recommend(rows, original)["status"])
        option = find_nearest_alternative_date(rows, original)
        self.assertEqual("2026-10-11", option["alternative_date"])
        changed = dict(original, date=option["alternative_date"])
        self.assertEqual({k: v for k, v in original.items() if k != "date"},
                         {k: v for k, v in changed.items() if k != "date"})
        matched = recommend(rows, changed)
        self.assertEqual("MATCHED", matched["status"])
        self.assertEqual(matched["eligible_count"], option["eligible_count"])
        self.assertEqual([card["id"] for card in matched["cards"]], option["up_to_3_candidate_ids"])

    def test_date_tie_prefers_future_and_is_deterministic(self):
        rows = [profile("busy", busy=["2026-10-10"])]
        first = find_nearest_alternative_date(rows, request())
        self.assertEqual("2026-10-11", first["alternative_date"])
        self.assertEqual(first, find_nearest_alternative_date(list(reversed(rows)), request()))

    def test_date_none_when_other_constraints_cannot_be_fixed_by_date(self):
        rows = [profile("wrong-language", language="казахский")]
        self.assertIsNone(find_nearest_alternative_date(rows, request()))

    def test_date_keeps_budget_format_language_duration(self):
        rows = [profile("format", busy=["2026-10-10"], event_format="корпоратив"),
                profile("language", busy=["2026-10-10"], language="казахский"),
                profile("duration", busy=["2026-10-10"], hours=2),
                profile("price", price=101, busy=["2026-10-10"]),
                profile("valid", busy=["2026-10-10"])]
        self.assertEqual(["valid"], find_nearest_alternative_date(rows, request())["up_to_3_candidate_ids"])

    def test_budget_preserves_all_other_fields_and_is_minimal(self):
        original = request(budget_kzt=50)
        rows = [profile("low", price=90), profile("first", price=120), profile("high", price=150)]
        self.assertEqual("NO_MATCH", recommend(rows, original)["status"])
        option = find_minimum_budget(rows, original)
        self.assertEqual(90, option["minimum_budget_kzt"])
        changed = dict(original, budget_kzt=option["minimum_budget_kzt"])
        self.assertEqual({k: v for k, v in original.items() if k != "budget_kzt"},
                         {k: v for k, v in changed.items() if k != "budget_kzt"})
        self.assertEqual("NO_MATCH", recommend(rows, dict(changed, budget_kzt=89.99))["status"])
        matched = recommend(rows, changed)
        self.assertEqual("MATCHED", matched["status"])
        self.assertEqual(matched["eligible_count"], option["candidate_count_at_that_budget"])
        self.assertEqual([card["id"] for card in matched["cards"]], option["candidate_ids"])

    def test_budget_skips_busy_wrong_format_language_and_duration(self):
        rows = [profile("busy", price=60, busy=["2026-10-10"]),
                profile("format", price=65, event_format="корпоратив"),
                profile("language", price=70, language="казахский"),
                profile("duration", price=75, hours=2),
                profile("eligible", price=120)]
        option = find_minimum_budget(rows, request(budget_kzt=50))
        self.assertEqual(120, option["minimum_budget_kzt"])
        self.assertEqual(["eligible"], option["candidate_ids"])

    def test_budget_none_when_no_single_price_can_help(self):
        rows = [profile("busy", price=100, busy=["2026-10-10"]),
                profile("format", price=200, event_format="корпоратив")]
        self.assertIsNone(find_minimum_budget(rows, request(budget_kzt=50)))

    def test_budget_ids_include_all_eligible_candidates_in_stable_order(self):
        rows = [profile(identifier, price=100) for identifier in ("d", "b", "a", "c")]
        option = find_minimum_budget(rows, request(budget_kzt=50))
        self.assertEqual(4, option["candidate_count_at_that_budget"])
        self.assertEqual(["a", "b", "c", "d"], option["candidate_ids"])

    def test_alternatives_are_separate_from_no_match_cards(self):
        rows = [profile("busy", price=100, busy=["2026-10-10"]),
                profile("cost", price=150)]
        original = request()
        core = recommend(rows, original)
        enriched = with_alternatives(rows, original, core)
        self.assertEqual("NO_MATCH", enriched["status"])
        self.assertEqual([], enriched["cards"])
        self.assertEqual([], core["cards"])
        self.assertEqual("2026-10-11", enriched["alternatives"]["alternative_date"]["alternative_date"])
        self.assertEqual(150, enriched["alternatives"]["minimum_budget"]["minimum_budget_kzt"])
        self.assertNotIn("alternatives", core)

    def test_matched_and_no_category_get_no_plan_b(self):
        rows = [profile("one")]
        for query, status in ((request(), "MATCHED"),
                              (request(category="Фотограф"), "NO_CATEGORY_IN_CITY")):
            core = recommend(rows, query)
            self.assertEqual(status, core["status"])
            self.assertIs(core, with_alternatives(rows, query, core))
            self.assertNotIn("alternatives", core)
            self.assertIsNone(find_nearest_alternative_date(rows, query))
            self.assertIsNone(find_minimum_budget(rows, query))

    def test_real_csv_scenario_f_shows_both_options(self):
        rows = load_catalog(Path(__file__).resolve().parents[1] / "contractors.csv")
        query = dict(city="Алматы", category="Банкетный зал", date="2026-09-26",
                     event_format="день рождения", budget_kzt=2000000)
        result = with_alternatives(rows, query, recommend(rows, query))
        self.assertEqual("NO_MATCH", result["status"])
        self.assertEqual([], result["cards"])
        self.assertEqual("2026-09-28", result["alternatives"]["alternative_date"]["alternative_date"])
        self.assertEqual(2500000, result["alternatives"]["minimum_budget"]["minimum_budget_kzt"])


if __name__ == "__main__":
    unittest.main()
