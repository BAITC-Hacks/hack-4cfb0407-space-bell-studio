"""Safe local runner. API keys are read from the environment or hidden TTY input."""
import argparse
import getpass
import os
import subprocess
import sys
import warnings
import re
from time import perf_counter
from urllib.parse import urlsplit
from pathlib import Path

from agent import run_matching, create_api_client, _diagnostic_fields, UnexpectedEndpointError
from catalog import load_catalog

ROOT = Path(__file__).resolve().parent
CHECK_REQUEST = {'city':'Алматы','date':'2026-09-26','event_format':'корпоратив','category':'Банкетный зал','budget_kzt':10000000}


def _validate_key(value):
    if not isinstance(value, str):
        raise RuntimeError('Ключ не задан.')
    key = value.strip()
    if not key:
        raise RuntimeError('Введена пустая строка ключа.')
    if (re.search(r"\s", key) or key[:1] in "\"'" or key[-1:] in "\"'"
            or key.lower().startswith("bearer ") or "..." in key or "…" in key):
        raise RuntimeError('Некорректный формат ключа: проверьте пробелы внутри, кавычки, Bearer или маскировку.')
    return key

def hidden_key():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError('Скрытый ввод ключа недоступен: запустите команду в интерактивном терминале.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            key = getpass.getpass('Вставьте полный Secret API key с OpenAI Platform, не промокод $50 и не замаскированное значение. Ключ не будет показан или сохранён: ')
    except (getpass.GetPassWarning, OSError, EOFError):
        raise RuntimeError('Не удалось безопасно прочитать скрытый ввод ключа.') from None
    return _validate_key(key)

def api_configuration():
    base = os.environ.get('OPENAI_BASE_URL', '').strip() or 'https://api.openai.com/v1'
    try:
        parts = urlsplit(base)
        safe = f'{parts.scheme}://{parts.hostname}{parts.path.rstrip("/")}'
    except ValueError:
        safe = 'INVALID'
    print('OPENAI_BASE_URL=' + safe)
    print('OPENAI_ORG_ID=' + ('PRESENT' if os.environ.get('OPENAI_ORG_ID') else 'MISSING'))
    print('OPENAI_PROJECT_ID=' + ('PRESENT' if os.environ.get('OPENAI_PROJECT_ID') else 'MISSING'))
    print('OPENAI_MODEL=' + ('PRESENT' if os.environ.get('OPENAI_MODEL') else 'MISSING'))
    if safe != 'https://api.openai.com/v1':
        raise UnexpectedEndpointError

def diagnose(key):
    api_configuration()
    model = (os.environ.get('OPENAI_MODEL') or '').strip() or 'gpt-4.1-mini'
    try:
        client = create_api_client(key, timeout=10.0)
    except Exception as exc:
        fields = _diagnostic_fields(exc, 'client_init')
        print('MODEL_PROBE=FAIL')
        print(f'error_phase={fields[1]} http_status={fields[2] or "UNAVAILABLE"} safe_server_code={fields[3]} safe_server_type={fields[4]} ai_error_code={fields[0]}')
        return 1
    started = perf_counter()
    responses = 0
    try:
        probe = client.chat.completions.create(model=model, messages=[{'role':'user','content':'Reply OK'}], max_tokens=5, timeout=10.0)
        responses += 1
        returned_model = getattr(probe, 'model', None)
        probe_text = getattr(probe.choices[0].message, 'content', None) if getattr(probe, 'choices', None) else None
        if not isinstance(probe_text, str) or probe_text.strip().upper() != 'OK':
            raise ValueError('invalid probe response')
    except Exception as exc:
        fields = _diagnostic_fields(exc, 'model_probe')
        print('MODEL_PROBE=FAIL')
        print(f'probe_api_attempts=1 probe_responses={responses} probe_time={perf_counter()-started:.2f}s')
        print(f'error_phase={fields[1]} http_status={fields[2] or "UNAVAILABLE"} safe_server_code={fields[3]} safe_server_type={fields[4]} ai_error_code={fields[0]}')
        if fields[2] == 401 and fields[3] == 'invalid_api_key':
            print('Сервис не принял credential.')
        elif fields[2] == 401 and fields[3] == 'ip_not_authorized':
            print('Доступ ограничен; обратитесь к организатору или владельцу API-проекта.')
        return 1
    print('MODEL_PROBE=PASS')
    print(f'probe_api_attempts=1 probe_responses={responses} probe_time={perf_counter()-started:.2f}s')
    print(f'requested_model={model} returned_model={returned_model or "UNAVAILABLE"}')
    agent_started = perf_counter()
    result = run_matching(load_catalog(ROOT / 'contractors.csv'), CHECK_REQUEST, api_key=key, client=client)
    elapsed = perf_counter() - agent_started
    passed = result.get('source') == 'ai_evidence' and result.get('tool_calls') == 1
    print('AGENT_RUN=' + ('PASS' if passed else 'FAIL'))
    print('MODE=' + ('AI_EVIDENCE' if result.get('source') == 'ai_evidence' else 'LOCAL_FALLBACK'))
    print('tool_result_source=LOCAL_READ_ONLY_CATALOG')
    print(f"requested_model={result.get('requested_model') or model} returned_model={result.get('returned_model') or 'UNAVAILABLE'}")
    print(f"API attempts={result.get('api_calls',0)} responses={result.get('responses',0)} tool calls served={result.get('tool_calls',0)}")
    print(f"TOTAL API attempts={1 + result.get('api_calls',0)} responses={responses + result.get('responses',0)}")
    print('candidate_ids=' + (', '.join(str(c.get('id','')) for c in result.get('cards',[])) or 'none'))
    print(f'agent_run_time={elapsed:.2f}s')
    if not passed:
        print(f"ai_error_code={result.get('ai_error_code') or 'UNAVAILABLE'} error_phase={result.get('error_phase') or 'UNAVAILABLE'} http_status={result.get('http_status') or 'UNAVAILABLE'} safe_server_code={result.get('safe_server_code') or 'UNAVAILABLE'} safe_server_type={result.get('safe_server_type') or 'UNAVAILABLE'}")
    print('Evidence and explanations:')
    for card in result.get('cards',[]):
        print(f"{card.get('id','')}: evidence_id={card.get('selected_evidence') or 'UNAVAILABLE'}; {card.get('explanation','')}")
    return 0 if passed else 1


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Безопасный локальный запуск Firebird Match')
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check-ai', action='store_true', help='один настоящий сквозной AI запрос')
    modes.add_argument('--diagnose-api', action='store_true', help='проверить модель, затем выполнить полный Firebird agent run')
    modes.add_argument('--web', action='store_true', help='локальный Streamlit только на 127.0.0.1')
    parser.add_argument('--ask-key', action='store_true', help='всегда использовать скрытый ввод ключа в интерактивном терминале')
    args = parser.parse_args(argv)
    try:
        if args.ask_key:
            key = hidden_key()
            print('KEY_SOURCE=HIDDEN_INPUT')
        else:
            raw_key = os.environ.get('OPENAI_API_KEY')
            key = _validate_key(raw_key) if raw_key is not None else None
            print('KEY_SOURCE=ENVIRONMENT')
        if args.diagnose_api:
            return diagnose(key)
        if args.check_ai:
            rows = load_catalog(ROOT / 'contractors.csv')
            result = run_matching(rows, CHECK_REQUEST, api_key=key)
            is_ai = result.get('source') == 'ai_evidence'
            print('Режим:', 'AI_EVIDENCE' if is_ai else 'LOCAL_FALLBACK')
            print('Запрошенная модель:', result.get('requested_model') or 'нет')
            print('Возвращённая модель:', result.get('returned_model') or 'нет')
            print('API calls:', result.get('api_calls', 0))
            print('Tool calls:', result.get('tool_calls', 0))
            cards = result.get('cards') or []
            print('Candidate IDs:', ', '.join(str(c.get('id', '')) for c in cards) or 'нет')
            latency = result.get('latency_seconds')
            print('Latency:', f'{latency:.2f} с' if isinstance(latency, (int, float)) else 'нет')
            print('AI error code:', result.get('ai_error_code') or 'нет')
            print('Explanations:')
            for card in cards:
                print(f"{card.get('id', '')}: {card.get('explanation', '')}")
            return 0 if is_ai else 1
        env = os.environ.copy()
        if key:
            env['OPENAI_API_KEY'] = key
        command = [sys.executable, '-m', 'streamlit', 'run', 'app.py', '--server.address', '127.0.0.1']
        return subprocess.call(command, cwd=ROOT, env=env)
    except RuntimeError as exc:
        print('Ошибка: ' + str(exc), file=sys.stderr)
        return 2
    except UnexpectedEndpointError:
        print('UNEXPECTED_API_ENDPOINT', file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print('Ошибка: локальный каталог или запуск недоступен.', file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
