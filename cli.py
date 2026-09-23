import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from catalog import load_catalog, recommend


def demo_requests(rows):
    dates = []
    day = date(2026, 9, 23)
    while day <= date(2026, 12, 31):
        dates.append(day.isoformat())
        day += timedelta(days=1)

    def eligible_count(city, category, day, fmt, budget):
        req = dict(city=city, category=category, date=day, event_format=fmt, budget_kzt=budget)
        return recommend(rows, req)

    dense = None
    for city, category in sorted({(p['city'], c) for p in rows for c in p['categories']}):
        for fmt in sorted({f for p in rows for f in p['event_formats']}):
            for day in dates:
                result = eligible_count(city, category, day, fmt, 10000000)
                if result['status'] == 'MATCHED' and result['eligible_count'] >= 4:
                    dense = dict(city=city, category=category, date=day, event_format=fmt, budget_kzt=10000000)
                    break
            if dense: break
        if dense: break
    if dense is None:
        raise RuntimeError('Не найден пример плотной категории в датасете')

    category_counts = {}
    for p in rows:
        for cat in p['categories']:
            key = (p['city'], cat)
            category_counts[key] = category_counts.get(key, 0) + 1
    rare = None
    for (city, cat), count in sorted(category_counts.items(), key=lambda x: (x[1], x[0])):
        for fmt in sorted({f for p in rows for f in p['event_formats']}):
            for day in dates:
                req = dict(city=city, category=cat, date=day, event_format=fmt, budget_kzt=10000000)
                result = recommend(rows, req)
                if result['status'] == 'MATCHED':
                    rare = req
                    break
            if rare: break
        if rare: break
    if rare is None:
        raise RuntimeError('Не найден пример редкой категории в датасете')

    return {
        'Плотная категория': dense,
        'Редкая категория': rare,
        'Категории нет в городе': dict(city='Зарубежье', category='Банкетный зал', date=dense['date'], event_format=dense['event_format'], budget_kzt=1000000),
        'Нет совпадений': dict(city=dense['city'], category=dense['category'], date=dense['date'], event_format=dense['event_format'], budget_kzt=0.01),
    }


def print_result(label, request, rows):
    result = recommend(rows, request)
    print(f"\n{label}: {result['status']}")
    if result['cards']:
        for card in result['cards']:
            print(f"- {card['anon_name']} ({card['id']}) — {card['category']}, {card['city']}, {card['price_label']}")
            print(f"  {card['explanation']}")
            print(f"  {card['profile_status']}; город оценочный: {card['city_is_estimated']}; цена оценочная: {card['price_is_estimated']}")
        if result.get('fewer_reason'):
            print(result['fewer_reason'])
    elif result['status'] == 'NO_MATCH':
        print('Подходящих профилей нет. Счётчики исключений пересекаются: ' + json.dumps(result['exclusions'], ensure_ascii=False))
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
            # Search real profiles for two same-query cases where the date changes matched IDs.
            found = None
            all_dates = [date(2026, 9, 23) + timedelta(days=n) for n in range(100)]
            for profile in sorted(rows, key=lambda p: p['id']):
                for cat in profile['categories']:
                    for fmt in profile['event_formats']:
                        budget = max(p['price_from_kzt'] for p in rows) + 1
                        base = dict(city=profile['city'], category=cat, event_format=fmt, budget_kzt=budget)
                        for busy in profile['busy_dates']:
                            free = next((d.isoformat() for d in all_dates if d.isoformat() not in profile['busy_dates']), None)
                            if free:
                                a = recommend(rows, dict(base, date=busy))
                                b = recommend(rows, dict(base, date=free))
                                ida = [x['id'] for x in a['cards']]
                                idb = [x['id'] for x in b['cards']]
                                if ida != idb:
                                    found = (dict(base, date=busy), dict(base, date=free))
                                    break
                        if found: break
                    if found: break
                if found: break
            if not found:
                raise RuntimeError('Не найден пример, где занятость меняет ID')
            print('\nСравнение дат (остальные параметры одинаковы):')
            for request in found:
                print_result(request['date'], request, rows)
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
