import io, os, unittest
from contextlib import redirect_stdout, redirect_stderr
from types import SimpleNamespace
from unittest.mock import patch
import run_local
from tests.test_hotfix import REQUEST, ROWS, fake_client, SECRET
from agent import run_matching

class Build09Tests(unittest.TestCase):
    def test_ask_key_always_uses_hidden_input_and_trims(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY':'ENV_SECRET'}), patch.object(run_local.sys.stdin,'isatty',return_value=True), patch.object(run_local.sys.stdout,'isatty',return_value=True), patch.object(run_local.getpass,'getpass',return_value='  hidden-secret  '):
            self.assertEqual('hidden-secret', run_local.hidden_key())
    def test_bad_key_inputs_fail_before_client(self):
        for value in ('', 'mask...x', 'Bearer abc', 'ab c', '"secret"', 'a\nb'):
            with self.subTest(value=value), self.assertRaises(RuntimeError): run_local._validate_key(value)
    def test_error_structure_codes_are_differentiated_and_safe(self):
        for code, expected in [('invalid_api_key','AUTH_ERROR'), ('ip_not_authorized','ACCESS_RESTRICTED')]:
            class AuthenticationError(Exception):
                status_code=401
                body={'error':{'code':code,'type':'authentication_error','message':SECRET}}
            result=run_matching(ROWS, REQUEST, api_key='safe', client=fake_client(AuthenticationError(SECRET)))
            self.assertEqual(expected,result['ai_error_code'])
            self.assertEqual(code,result['safe_server_code'])
            self.assertNotIn(SECRET,repr(result))
    def test_help_without_key(self):
        with self.assertRaises(SystemExit) as e: run_local.main(['--help'])
        self.assertEqual(0,e.exception.code)
    def test_diagnose_requires_both_stages(self):
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(model='m', choices=[SimpleNamespace(message=SimpleNamespace(content='OK'))]))))
        for result, expected in [({'source':'rules','tool_calls':0,'cards':[],'api_calls':0,'responses':0},1), ({'source':'ai_evidence','tool_calls':1,'cards':[],'api_calls':2,'responses':2},0)]:
            out=io.StringIO()
            with patch.object(run_local,'api_configuration'), patch.object(run_local,'create_api_client',return_value=client) as factory, patch.object(run_local,'load_catalog',return_value=ROWS), patch.object(run_local,'run_matching',return_value=result) as agent, patch.dict(os.environ, {'OPENAI_MODEL':'gpt-4.1-mini'}), redirect_stdout(out):
                self.assertEqual(expected,run_local.diagnose('same-key'))
                factory.assert_called_once_with('same-key', timeout=10.0)
                agent.assert_called_once_with(ROWS, run_local.CHECK_REQUEST, api_key='same-key', client=client)
            self.assertIn('MODEL_PROBE=PASS',out.getvalue())
            self.assertIn('AGENT_RUN='+('PASS' if expected==0 else 'FAIL'),out.getvalue())
    def test_probe_failure_does_not_run_agent(self):
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(RuntimeError(SECRET)))))
        out=io.StringIO()
        with patch.object(run_local,'api_configuration'), patch.object(run_local,'create_api_client',return_value=client), patch.object(run_local,'run_matching') as agent, redirect_stdout(out):
            self.assertEqual(1,run_local.diagnose('same-key'))
        agent.assert_not_called()
        self.assertNotIn(SECRET,out.getvalue())
        self.assertIn('MODEL_PROBE=FAIL',out.getvalue())
    def test_unexpected_endpoint_rejected_without_sdk_init(self):
        for endpoint in ('https://evil.example/v1?secret=x', 'https://[broken/v1'):
            with patch.dict(os.environ, {'OPENAI_BASE_URL':endpoint}):
                with self.assertRaises(Exception) as e: run_local.create_api_client('secret')
                self.assertEqual('UnexpectedEndpointError',type(e.exception).__name__)

    def test_web_hidden_key_reaches_subprocess_and_agent_environment(self):
        out = io.StringIO()
        with patch.object(run_local, 'hidden_key', return_value='offline-secret'), \
             patch.object(run_local.subprocess, 'call', return_value=0) as launch, \
             redirect_stdout(out):
            self.assertEqual(0, run_local.main(['--web', '--ask-key']))
        command = launch.call_args.args[0]
        self.assertEqual([run_local.sys.executable, '-m', 'streamlit', 'run', 'app.py'], command[:5])
        self.assertEqual('offline-secret', launch.call_args.kwargs['env']['OPENAI_API_KEY'])
        self.assertNotIn('offline-secret', out.getvalue())

        client = fake_client()
        with patch.dict(os.environ, {'OPENAI_API_KEY':'offline-secret'}), \
             patch('agent.create_api_client', return_value=client) as factory:
            result = run_matching(ROWS, REQUEST)
        factory.assert_called_once()
        self.assertEqual('offline-secret', factory.call_args.args[0])
        self.assertEqual('ai_evidence', result['source'])
        self.assertEqual(1, result['tool_calls'])

if __name__=='__main__': unittest.main()
