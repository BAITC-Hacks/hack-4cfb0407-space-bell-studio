import unittest
from copy import deepcopy
from pathlib import Path

from agent import recommend_contractors, run_matching
from catalog import load_catalog, recommend
from comparison import before_selection, comparison_rows, profile_detail, query_delta
from tests.test_agent import REQUEST, ROWS as AGENT_ROWS, fake_client


ROWS = load_catalog(Path(__file__).resolve().parents[1] / "contractors.csv")
BASE = {"city": "Алматы", "date": "2026-09-23", "event_format": "день рождения",
        "category": "Банкетный зал", "budget_kzt": 10000000, "language": None, "hours": None}


def delta(first, second, rows=ROWS):
    return query_delta(rows, first, recommend(rows, first), second, recommend(rows, second))


class QueryDeltaTests(unittest.TestCase):
    def test_first_submit_and_same_query_have_no_delta(self):
        result = recommend(ROWS, BASE)
        self.assertIsNone(query_delta(ROWS, None, None, BASE, result))
        self.assertIsNone(query_delta(ROWS, BASE, result, BASE.copy(), result))

    def test_date_change_appears_and_disappears_only_for_busy_dates(self):
        later = dict(BASE, date="2026-09-26")
        change = delta(BASE, later)
        self.assertEqual("date", change["kind"])
        by_id = {p["id"]: p for p in ROWS}
        self.assertTrue(change["appeared_ids"])
        self.assertTrue(change["disappeared_ids"])
        for pid in change["appeared_ids"]:
            self.assertIn(BASE["date"], by_id[pid]["busy_dates"])
            self.assertNotIn(later["date"], by_id[pid]["busy_dates"])
        for pid in change["disappeared_ids"]:
            self.assertIn(later["date"], by_id[pid]["busy_dates"])
            self.assertNotIn(BASE["date"], by_id[pid]["busy_dates"])
        self.assertNotIn("HK-", " ".join(change["lines"]))

    def test_top_three_exit_is_not_eligible_exit(self):
        template = next(p for p in ROWS if p["id"] == "HK-50695")
        profiles = []
        for i, price in enumerate((1000000, 2000000, 3000000, 4000000)):
            p = deepcopy(template)
            p.update(id=f"TEST-{i}", anon_name=f"Профиль {i}", price_from_kzt=price,
                     busy_dates=["2026-09-23"] if i == 0 else [])
            profiles.append(p)
        first = dict(BASE, date="2026-09-23")
        second = dict(BASE, date="2026-09-26")
        self.assertEqual("TEST-3", recommend(profiles, first)["cards"][2]["id"])
        self.assertNotIn("TEST-3", [c["id"] for c in recommend(profiles, second)["cards"]])
        change = delta(first, second, profiles)
        self.assertEqual(["TEST-0"], change["appeared_ids"])
        self.assertEqual([], change["disappeared_ids"])
        self.assertNotIn("Профиль 3 исчез", " ".join(change["lines"]))

    def test_budget_up_and_down_use_price_threshold(self):
        low = dict(BASE, date="2026-09-26", budget_kzt=2000000)
        high = dict(low, budget_kzt=10000000)
        by_id = {p["id"]: p for p in ROWS}
        up = delta(low, high)
        down = delta(high, low)
        self.assertEqual("budget_kzt", up["kind"])
        self.assertTrue(up["appeared_ids"])
        self.assertEqual(up["appeared_ids"], down["disappeared_ids"])
        for pid in up["appeared_ids"]:
            self.assertLess(low["budget_kzt"], by_id[pid]["price_from_kzt"])
            self.assertLessEqual(by_id[pid]["price_from_kzt"], high["budget_kzt"])
        self.assertTrue(any("начальная цена «от»" in line for line in up["lines"]))

    def test_multiple_changes_and_missing_category_do_not_claim_cause(self):
        multiple = delta(BASE, dict(BASE, date="2026-09-26", budget_kzt=2000000))
        self.assertEqual("multiple", multiple["kind"])
        self.assertEqual(1, len(multiple["lines"]))
        self.assertEqual("other", delta(BASE, dict(BASE, event_format="корпоратив"))["kind"])
        missing = dict(BASE, city="Зарубежье")
        self.assertEqual("no_category", delta(missing, dict(missing, budget_kzt=2000000))["kind"])


class ComparisonTests(unittest.TestCase):
    def test_comparison_fields_and_exact_evidence(self):
        request = dict(BASE, date="2026-09-26", event_format="корпоратив", language="русский", hours=4.0)
        result = recommend_contractors(ROWS, request)
        cards = result["cards"]
        self.assertEqual([], comparison_rows(cards[:1], request, ROWS))
        compared = comparison_rows(cards, request, ROWS)
        self.assertEqual(len(cards), len(compared))
        for card, entry in zip(cards, compared):
            self.assertEqual(card["anon_name"], entry["Имя"])
            self.assertEqual(profile_detail(card), entry["Особенность профиля"])
            self.assertIn("Язык", entry)
            self.assertIn("Длительность", entry)
            self.assertEqual({"Имя", "Цена «от»", "Город", "Категория", "Особенность профиля",
                              "Что нужно уточнить", "Язык", "Длительность"}, set(entry))
        plain = comparison_rows(cards, dict(request, language=None, hours=None), ROWS)
        self.assertNotIn("Язык", plain[0])
        self.assertNotIn("Длительность", plain[0])

    def test_notes_follow_flags(self):
        card = {"price_imputed": True, "city_imputed": True, "synthetic": True}
        text = "; ".join(before_selection(card))
        for phrase in ("Окончательную цену", "Город работы", "Фактическую доступность",
                       "Демонстрационный профиль, не реальное предложение для заказа"):
            self.assertIn(phrase, text)
        self.assertEqual(["Фактическую доступность на дату перед бронированием"],
                         before_selection({key: False for key in card}))

    def test_ai_detail_reuses_verified_selection_without_new_call(self):
        request = REQUEST
        api, client = fake_client()
        result = run_matching(AGENT_ROWS, request, api_key="offline-test", client=client)
        self.assertEqual("ai_evidence", result["source"])
        count = len(api.calls)
        compared = comparison_rows(result["cards"], request, AGENT_ROWS)
        self.assertEqual(2, count)
        self.assertEqual(count, len(api.calls))
        for card, entry in zip(result["cards"], compared):
            self.assertEqual(card["selected_evidence"], entry["Особенность профиля"])
            self.assertIn(card["selected_evidence"], [e["text"] for e in card["evidence"]])


if __name__ == "__main__":
    unittest.main()
