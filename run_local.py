"""Safe local runner. API keys are read from the environment or hidden TTY input."""
import argparse
import getpass
import os
import subprocess
import sys
import warnings
from pathlib import Path

from agent import run_matching
from catalog import load_catalog

ROOT = Path(__file__).resolve().parent
CHECK_REQUEST = {'city':'Алматы','date':'2026-09-26','event_format':'корпоратив','category':'Банкетный зал','budget_kzt':10000000}


def hidden_key():
    if os.environ.get('OPENAI_API_KEY', '').strip():
        return os.environ['OPENAI_API_KEY'].strip()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError('Скрытый ввод ключа доступен только в интерактивном терминале.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            key = getpass.getpass('OpenAI API key (ввод скрыт): ')
    except (getpass.GetPassWarning, OSError, EOFError):
        raise RuntimeError('Не удалось безопасно прочитать скрытый ввод ключа.') from None
    if not key:
        raise RuntimeError('Введён пустой ключ.')
    return key


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Безопасный локальный запуск Firebird Match')
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check-ai', action='store_true', help='один настоящий сквозной AI запрос')
    modes.add_argument('--web', action='store_true', help='локальный Streamlit только на 127.0.0.1')
    parser.add_argument('--ask-key', action='store_true', help='скрыто запросить ключ, если он отсутствует в окружении')
    args = parser.parse_args(argv)
    try:
        key = os.environ.get('OPENAI_API_KEY')
        if args.ask_key and not (key or '').strip():
            key = hidden_key()
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
    except RuntimeError:
        print('Ошибка: безопасный локальный запуск недоступен.', file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print('Ошибка: локальный каталог или запуск недоступен.', file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
