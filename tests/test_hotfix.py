import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run_local
from agent import run_matching
from catalog import load_catalog

ROWS = load_catalog(Path(__file__).resolve().parents[1] / 'contractors.csv')
REQUEST = dict(city='Алматы', date='2026-09-26', event_format='корпоратив',
               category='Банкетный зал', budget_kzt=10000000)
FIELDS = {'source', 'status', 'cards', 'requested_model', 'returned_model',
          'api_calls', 'tool_calls', 'latency_seconds', 'ai_error_code'}
SECRET = 'FAKE_SECRET_MUST_NOT_LEAK'


class FakeCompletions:
    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    def create(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        if self.calls == 1:
            call = SimpleNamespace(id='call-1', function=SimpleNamespace(name='recommend_contractors', arguments='{}'))
            return SimpleNamespace(model='returned-test-model', choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])
        import json
        payload = json.loads(kwargs['messages'][-1]['content'])
        selections = [{'id': card['id'], 'evidence_id': card['evidence'][0]['evidence_id']} for card in payload['cards']]
        message = SimpleNamespace(content=json.dumps({'selections': selections}))
        return SimpleNamespace(model='returned-test-model', choices=[SimpleNamespace(message=message, finish_reason='stop')])


def fake_client(error=None):
    completions = FakeCompletions(error)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


class LiveDiagnosticsHotfixTests(unittest.TestCase):
    def test_no_key_fallback_has_full_contract(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY':'', 'OPENAI_MODEL':'gpt-4.1-mini'}):
            result = run_matching(ROWS, REQUEST)
        self.assertTrue(FIELDS <= result.keys())
        self.assertEqual('rules', result['source'])
        self.assertEqual('KEY_MISSING', result['ai_error_code'])
        self.assertEqual('gpt-4.1-mini', result['requested_model'])
        self.assertIsNone(result['returned_model'])
        self.assertEqual((0, 0), (result['api_calls'], result['tool_calls']))

    def test_auth_timeout_unknown_and_config_failures_are_safe(self):
        class AuthenticationError(Exception):
            status_code = 401
        for error, expected in ((AuthenticationError(SECRET), 'AUTH_ERROR'),
                                (TimeoutError(SECRET), 'TIMEOUT'),
                                (RuntimeError(SECRET), 'UNKNOWN_API_ERROR')):
            result = run_matching(ROWS, REQUEST, api_key='offline-test', client=fake_client(error))
            self.assertTrue(FIELDS <= result.keys())
            self.assertEqual(expected, result['ai_error_code'])
            self.assertTrue(result['requested_model'])
            self.assertNotIn(SECRET, repr(result))
        with patch('openai.OpenAI', side_effect=RuntimeError(SECRET)):
            result = run_matching(ROWS, REQUEST, api_key='offline-test')
        self.assertEqual('SDK_OR_CONFIG_ERROR', result['ai_error_code'])
        self.assertNotIn(SECRET, repr(result))

    def test_successful_offline_client_has_models_and_counts(self):
        result = run_matching(ROWS, REQUEST, api_key='offline-test', client=fake_client())
        self.assertTrue(FIELDS <= result.keys())
        self.assertEqual('ai_evidence', result['source'])
        self.assertEqual('gpt-4.1-mini', result['requested_model'])
        self.assertEqual('returned-test-model', result['returned_model'])
        self.assertEqual((2, 1), (result['api_calls'], result['tool_calls']))
        self.assertIsNone(result['ai_error_code'])

    def test_launcher_handles_missing_diagnostics_and_returns_nonzero(self):
        minimal_fallback = {'source':'rules', 'status':'MATCHED', 'cards':[], 'returned_model':None}
        out = io.StringIO()
        with patch.object(run_local, 'load_catalog', return_value=ROWS), \
             patch.object(run_local, 'run_matching', return_value=minimal_fallback), \
             redirect_stdout(out):
            exit_code = run_local.main(['--check-ai'])
        self.assertEqual(1, exit_code)
        for label in ('Режим:', 'Запрошенная модель:', 'Возвращённая модель:',
                      'API calls:', 'Tool calls:', 'Candidate IDs:', 'Latency:',
                      'AI error code:', 'Explanations:'):
            self.assertIn(label, out.getvalue())

    def test_launcher_keeps_secret_out_of_output_and_ai_returns_zero(self):
        class AuthenticationError(Exception):
            status_code = 401
        fallback = run_matching(ROWS, REQUEST, api_key='offline-test', client=fake_client(AuthenticationError(SECRET)))
        success = run_matching(ROWS, REQUEST, api_key='offline-test', client=fake_client())
        for result, expected_exit in ((fallback, 1), (success, 0)):
            out = io.StringIO()
            with patch.object(run_local, 'load_catalog', return_value=ROWS), \
                 patch.object(run_local, 'run_matching', return_value=result), \
                 redirect_stdout(out):
                exit_code = run_local.main(['--check-ai'])
            self.assertEqual(expected_exit, exit_code)
            self.assertNotIn(SECRET, out.getvalue())

if __name__ == '__main__': unittest.main()
