import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent import format_agent_result, recommend_contractors, run_matching
from catalog import load_catalog, recommend

ROWS = load_catalog(Path(__file__).resolve().parents[1] / "contractors.csv")
REQUEST = dict(city="Алматы", date="2026-09-26", event_format="корпоратив",
               category="Банкетный зал", budget_kzt=10000000)

class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="recommend_contractors", arguments="{}"))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])
        payload = json.loads(kwargs["messages"][-1]["content"])
        explanations = {id: f"AI текст для {id}. В профиле указана индивидуальная деталь." for id in payload["candidate_order"]}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"explanations": explanations, "summary": "По условиям заказа."})))])

class AgentTests(unittest.TestCase):
    def test_tool_preserves_core_ids_and_order(self):
        core = recommend(ROWS, REQUEST)
        tool = recommend_contractors(ROWS, REQUEST)
        self.assertEqual(core["status"], tool["status"])
        self.assertEqual([c["id"] for c in core["cards"]], tool["candidate_order"])

    def test_agent_text_cannot_reorder_or_add_candidates(self):
        tool = recommend_contractors(ROWS, REQUEST)
        ids = tool["candidate_order"]
        answer = {"explanations": {id: f"Особенности {id}." for id in reversed(ids)}, "summary": "Итог."}
        result = format_agent_result(tool, answer)
        self.assertEqual(ids, [c["id"] for c in result["cards"]])
        self.assertEqual("ai", result["source"])
        self.assertEqual([c["price_from_kzt"] for c in tool["cards"]], [c["price_from_kzt"] for c in result["cards"]])
        bad = format_agent_result(tool, {"explanations": {"invented": "Выдумка"}, "summary": ""})
        self.assertEqual("deterministic", bad["source"])

    def test_forced_tool_loop_uses_catalog_result(self):
        fake = FakeCompletions()
        result = run_matching(ROWS, REQUEST, client=SimpleNamespace(chat=SimpleNamespace(completions=fake)))
        self.assertEqual("ai", result["source"])
        self.assertEqual(1, result["tool_calls"])
        self.assertEqual(recommend_contractors(ROWS, REQUEST)["candidate_order"], [c["id"] for c in result["cards"]])
        self.assertEqual("recommend_contractors", fake.calls[0]["tool_choice"]["function"]["name"])

    def test_fallback_and_no_match_without_key(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            matched = run_matching(ROWS, REQUEST)
            no_match = run_matching(ROWS, dict(REQUEST, budget_kzt=1))
        self.assertEqual("deterministic", matched["source"])
        self.assertEqual(0, matched["tool_calls"])
        self.assertEqual(recommend(ROWS, REQUEST)["cards"][0]["explanation"], matched["cards"][0]["explanation"])
        self.assertEqual("NO_MATCH", no_match["status"])
        self.assertGreater(no_match["exclusions"]["over_budget"], 0)

    def test_no_category_without_key(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            result = run_matching(ROWS, dict(REQUEST, category="Несуществующая категория"))
        self.assertEqual("NO_CATEGORY_IN_CITY", result["status"])
        self.assertEqual([], result["cards"])

if __name__ == "__main__":
    unittest.main()
