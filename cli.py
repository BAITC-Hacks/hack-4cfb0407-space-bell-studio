import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from catalog import load_catalog, recommend
from plan_b import with_alternatives


def demo_requests(rows):
    """Fixed, previously verified inputs; all outcomes are computed from current CSV."""
    cases = {
        'A: Плотная категория': dict(city='Алматы', category='Банкетный зал', date='2026-09-26', event_format='корпоратив', budget_kzt=10000000),
        'B: Редкая категория': dict(city='Алматы', category='Флорист', date='2026-09-23', event_format='конференция', budget_kzt=10000000),
        'C: Категории нет в городе': dict(city='Зарубежье', category='Банкетный зал', date='2026-09-26', event_format='корпоратив', budget_kzt=1000000),
        'D: Условия исключают всех': dict(city='Алматы', category='Банкетный зал', date='2026-09-26', event_format='корпоратив', budget_kzt=1),
    }
    cases['E: Первая дата'] = dict(city='Алматы', category='Банкетный зал', date='2026-09-23', event_format='день рождения', budget_kzt=10000000)
    cases['E: Вторая дата'] = dict(cases['E: Первая дата'], date='2026-09-26')
    cases['F: План Б'] = dict(city='Алматы', category='Банкетный зал', date='2026-09-26',
                             event_format='день рождения', budget_kzt=2000000)
    return cases


def print_result(label, request, rows):
    result = with_alternatives(rows, request, recommend(rows, request))
    print(f"\n{label}: {result['status']}")
    if result['cards']:
        for card in result['cards']:
            print(f"- {card['anon_name']} ({card['id']}) — {card['category']}, {card['city']}, {card['price_label']}")
            print(f"  {card['explanation']}")
            print(f"  {card['profile_status']}; город оценочный: {card['city_is_estimated']}; цена оценочная: {card['price_is_estimated']}")
        if len(result['cards']) < 3:
            print(f"В городе профилей категории: {result['category_count']}; подошло: {result['eligible_count']}.")
            reasons = {key: count for key, count in result['exclusions'].items() if count}
            if reasons:
                print('Исключения (счётчики пересекаются): ' + json.dumps(reasons, ensure_ascii=False))
            if result.get('fewer_reason'):
                print(result['fewer_reason'])
    elif result['status'] == 'NO_MATCH':
        print('Подходящих профилей нет. Счётчики исключений пересекаются: ' + json.dumps(result['exclusions'], ensure_ascii=False))
        alternative_date = result['alternatives']['alternative_date']
        minimum_budget = result['alternatives']['minimum_budget']
        if alternative_date:
            print(f"План Б — дата: {alternative_date['alternative_date']}; подходящих профилей: {alternative_date['eligible_count']}.")
        if minimum_budget:
            shown_price = f"{minimum_budget['minimum_budget_kzt']:,.0f}".replace(',', ' ')
            print(f"План Б — минимальная начальная цена «от»: {shown_price} ₸.")
    else:
        print('В этом городе нет профиля запрошенной категории.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Локальный подбор подрядчиков Firebird Match')
    parser.add_argument('--csv', type=Path, default=Path(__file__).resolve().with_name('contractors.csv'))
    parser.add_argument('--city')
    parser.add_argument('--date')
    parser.add_argument('--event-format')
    parser.add_argument('--category')
    parser.add_argument('--budget-kzt', type=float)
    parser.add_argument('--hours', type=float)
    parser.add_argument('--language')
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    try:
        rows = load_catalog(args.csv)
        if args.demo:
            cases = demo_requests(rows)
            for label, request in cases.items():
                print_result(label, request, rows)
            first_id = [c['id'] for c in recommend(rows, cases['E: Первая дата'])['cards']]
            second_id = [c['id'] for c in recommend(rows, cases['E: Вторая дата'])['cards']]
            changed = set(second_id) - set(first_id)
            for contractor_id in sorted(changed):
                profile = next(p for p in rows if p['id'] == contractor_id)
                if cases['E: Первая дата']['date'] in profile['busy_dates'] and cases['E: Вторая дата']['date'] not in profile['busy_dates']:
                    print(f"Проверка календаря: {contractor_id} отсутствует {cases['E: Первая дата']['date']} — дата есть в busy_dates; на {cases['E: Вторая дата']['date']} по календарю датасета не занят.")
            return 0
        fields = ('city', 'date', 'event_format', 'category', 'budget_kzt')
        missing = [field for field in fields if getattr(args, field) is None]
        if missing:
            parser.error('укажите параметры: ' + ', '.join('--' + x.replace('_', '-') for x in missing) + ' (или --demo)')
        request = {field: getattr(args, field) for field in fields}
        request.update(hours=args.hours, language=args.language)
        print_result('Результат', request, rows)
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(f'Ошибка: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
