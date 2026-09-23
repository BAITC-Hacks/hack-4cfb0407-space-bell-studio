import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent import EVIDENCE_SCHEMA, recommend_contractors, run_matching
from catalog import load_catalog, recommend
from cli import demo_requests

ROWS = load_catalog(Path(__file__).resolve().parents[1] / "contractors.csv")
REQUEST = dict(city="Алматы", date="2026-09-26", event_format="корпоратив",
               category="Банкетный зал", budget_kzt=10000000)


def good_answer(tool_result):
    return {"selections": [{"id": card["id"], "evidence_id": card["evidence"][0]["evidence_id"]}
                           for card in reversed(tool_result["cards"])]}


class FakeCompletions:
    def __init__(self, answer=None, first_error=None, second_error=None, refusal=False):
        self.calls = []
        self.answer = answer
        self.first_error = first_error
        self.second_error = second_error
        self.refusal = refusal

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            if self.first_error:
                raise self.first_error
            call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="recommend_contractors", arguments="{}"))
            return SimpleNamespace(model="gpt-4.1-mini-2026-09-01", choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])
        if self.second_error:
            raise self.second_error
        if self.refusal:
            message = SimpleNamespace(content=None, refusal="refused", tool_calls=None)
        else:
            payload = json.loads(kwargs["messages"][-1]["content"])
            answer = self.answer if self.answer is not None else good_answer(payload)
            message = SimpleNamespace(content=json.dumps(answer, ensure_ascii=False), refusal=None, tool_calls=None)
        return SimpleNamespace(model="gpt-4.1-mini-2026-09-01", choices=[SimpleNamespace(message=message, finish_reason="stop")])


def fake_client(**kwargs):
    api = FakeCompletions(**kwargs)
    return api, SimpleNamespace(chat=SimpleNamespace(completions=api))


class AgentTests(unittest.TestCase):
    def test_tool_matches_core_order_and_contains_exact_owned_evidence(self):
        core = recommend(ROWS, REQUEST)
        tool = recommend_contractors(ROWS, REQUEST)
        self.assertEqual([c['id'] for c in core['cards']], tool['candidate_order'])
        for card in tool['cards']:
            by_id = {p['id']: p for p in ROWS}
            self.assertTrue(card['evidence'])
            self.assertTrue(all(item['text'] in by_id[card['id']]['description'] for item in card['evidence']))

    def test_good_selection_keeps_order_prices_and_uses_attributed_evidence(self):
        tool = recommend_contractors(ROWS, REQUEST)
        api, client = fake_client()
        result = run_matching(ROWS, REQUEST, api_key='offline-test-key', client=client)
        self.assertEqual('ai_evidence', result['source'])
        self.assertEqual(tool['candidate_order'], [c['id'] for c in result['cards']])
        self.assertEqual([c['price_from_kzt'] for c in recommend(ROWS, REQUEST)['cards']], [c['price_from_kzt'] for c in result['cards']])
        for card in result['cards']:
            self.assertIn('В профиле указано:', card['explanation'])
            self.assertIn(card['selected_evidence'], next(p['description'] for p in ROWS if p['id'] == card['id']))
        self.assertEqual(1, result['tool_calls'])
        self.assertEqual(2, result['api_calls'])
        self.assertEqual('gpt-4.1-mini-2026-09-01', result['returned_model'])
        self.assertEqual(EVIDENCE_SCHEMA, api.calls[1]['response_format'])

    def test_evidence_from_another_provider_and_unknown_evidence_rejected(self):
        tool = recommend_contractors(ROWS, REQUEST)
        first, second = tool['cards'][:2]
        wrong_owner = [{"id": first['id'], "evidence_id": second['evidence'][0]['evidence_id']}]
        result = run_matching(ROWS, REQUEST, api_key='offline-test-key', client=fake_client(answer={"selections": wrong_owner})[1])
        self.assertEqual('RESPONSE_INVALID', result['error_code'])
        unknown = [{"id": c['id'], "evidence_id": 'unknown'} for c in tool['cards']]
        result = run_matching(ROWS, REQUEST, api_key='offline-test-key', client=fake_client(answer={"selections": unknown})[1])
        self.assertEqual('RESPONSE_INVALID', result['error_code'])
        self.assertEqual('rules', result['source'])

    def test_missing_extra_duplicate_ids_rejected(self):
        tool = recommend_contractors(ROWS, REQUEST)
        good = good_answer(tool)['selections']
        for selections in (good[:-1], good + [{"id": "outside", "evidence_id": "e"}], [good[0], good[0]]):
            result = run_matching(ROWS, REQUEST, api_key='offline-test-key', client=fake_client(answer={"selections": selections})[1])
            self.assertEqual('RESPONSE_INVALID', result['error_code'])
            self.assertEqual('rules', result['source'])

    def test_invalid_schema_and_refusal_fall_back(self):
        for api in (fake_client(answer={"summary": "no required shape"}), fake_client(refusal=True)):
            result = run_matching(ROWS, REQUEST, api_key='offline-test-key', client=api[1])
            self.assertEqual('RESPONSE_INVALID', result['error_code'])
            self.assertEqual('rules', result['source'])
            self.assertTrue(result['cards'][0]['explanation'])

    def test_timeout_and_auth_errors_are_sanitized(self):
        class AuthenticationError(Exception):
            status_code = 401
        for exc, code in ((TimeoutError('private test secret KEY_SHOULD_NOT_LEAK'), 'TIMEOUT'),
                          (AuthenticationError('private test secret KEY_SHOULD_NOT_LEAK'), 'AUTH_ERROR')):
            result = run_matching(ROWS, REQUEST, api_key='offline-test-key', client=fake_client(first_error=exc)[1])
            self.assertEqual(code, result['error_code'])
            self.assertNotIn('DO_NOT_LEAK', repr(result))
            self.assertNotIn('private test secret', repr(result))

    def test_invalid_input_and_missing_key_make_no_api_calls(self):
        api, client = fake_client()
        with self.assertRaises(ValueError):
            run_matching(ROWS, dict(REQUEST, city=None), api_key='offline-test-key', client=client)
        self.assertEqual([], api.calls)
        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
            result = run_matching(ROWS, REQUEST)
        self.assertEqual('KEY_MISSING', result['error_code'])
        self.assertEqual(0, result['api_calls'])
        self.assertEqual(0, result['tool_calls'])

    def test_empty_outcome_skips_api(self):
        result = run_matching(ROWS, dict(REQUEST, budget_kzt=1), api_key='offline-test-key')
        self.assertEqual('NO_MATCH', result['status'])
        self.assertEqual('NO_CANDIDATES', result['skipped_reason'])
        self.assertEqual(0, result['api_calls'])

    def test_sdk_initialization_failure_has_safe_code(self):
        with patch('openai.OpenAI', side_effect=RuntimeError('private KEY_SHOULD_NOT_LEAK')):
            result = run_matching(ROWS, REQUEST, api_key='offline-test-key')
        self.assertEqual('SDK_OR_CONFIG_ERROR', result['error_code'])
        self.assertNotIn('KEY_SHOULD_NOT_LEAK', repr(result))

    def test_rare_demo_uses_listed_real_category(self):
        rare = demo_requests(ROWS)['B: Редкая категория']
        self.assertIn(rare['category'], {'Флорист','Декоратор','Подарки и сувениры','Ведущий церемонии','Фото и видеобудки','Отель','Инструменталист'})
        self.assertEqual('MATCHED', recommend(ROWS, rare)['status'])

    def test_all_fixed_demo_outcomes_and_busy_date_evidence(self):
        cases = demo_requests(ROWS)
        expected = {'A: Плотная категория':'MATCHED', 'B: Редкая категория':'MATCHED',
                    'C: Категории нет в городе':'NO_CATEGORY_IN_CITY', 'D: Условия исключают всех':'NO_MATCH'}
        for label, status in expected.items():
            self.assertEqual(status, recommend(ROWS, cases[label])['status'])
        first, second = cases['E: Первая дата'], cases['E: Вторая дата']
        self.assertEqual({k:v for k,v in first.items() if k!='date'}, {k:v for k,v in second.items() if k!='date'})
        first_ids = {c['id'] for c in recommend(ROWS, first)['cards']}
        second_ids = {c['id'] for c in recommend(ROWS, second)['cards']}
        gained = second_ids - first_ids
        self.assertTrue(gained)
        profiles = {p['id']:p for p in ROWS}
        self.assertTrue(any(first['date'] in profiles[i]['busy_dates'] and second['date'] not in profiles[i]['busy_dates'] for i in gained))

if __name__ == '__main__':
    unittest.main()
