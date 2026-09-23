import csv
import tempfile
import unittest
from pathlib import Path
from catalog import load_catalog, recommend

HEADER = ["id", "anon_name", "categories", "city", "city_imputed", "synthetic", "price_from_kzt", "price_imputed", "event_formats", "languages", "max_hours", "busy_dates", "description"]

def profile(id, category="Ведущий", city="Алматы", price=100, busy="", formats="свадьба", languages="русский", max_hours="4", synthetic="False"):
    return dict(id=id, anon_name=id, categories=[category], city=city, city_imputed=False, synthetic=(synthetic == "True"), price_from_kzt=float(price), price_imputed=False, event_formats=formats.split("|"), languages=languages.split("|"), max_hours=float(max_hours) if max_hours else None, busy_dates=busy.split("|") if busy else [], description=f"Профиль {id} оказывает услуги." )

def request(**overrides):
    data = dict(city="Алматы", date="2026-10-10", event_format="свадьба", category="Ведущий", budget_kzt=100, hours=3, language="русский")
    data.update(overrides)
    return data

class CatalogTests(unittest.TestCase):
    def test_real_loader_unique_ids_and_flags(self):
        rows = load_catalog(Path(__file__).resolve().parents[1] / "contractors.csv")
        self.assertEqual(66, len(rows)); self.assertEqual(66, len({p['id'] for p in rows}))
        self.assertTrue(all(isinstance(p['synthetic'], bool) for p in rows))

    def test_utf8_bom_and_empty_max_hours(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'x.csv'
            with path.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.writer(stream); writer.writerow(HEADER); writer.writerow(['x','имя','a|b','Город','False','False',10,'True','свадьба','ru','','2026-09-23','текст'])
            item = load_catalog(path)[0]
            self.assertIsNone(item['max_hours']); self.assertFalse(item['synthetic']); self.assertFalse(item['city_imputed'])

    def test_busy_excludes_provider_and_venue(self):
        for cat in ('Ведущий', 'Банкетный зал'):
            rows = [profile('busy', category=cat, busy='2026-10-10'), profile('free', category=cat)]
            result = recommend(rows, request(category=cat))
            self.assertEqual(['free'], [c['id'] for c in result['cards']])
            self.assertEqual(1, result['exclusions']['busy'])

    def test_budget_boundary_inclusive(self):
        self.assertEqual('MATCHED', recommend([profile('one', price=100)], request(budget_kzt=100))['status'])

    def test_no_category_differs_from_no_match(self):
        self.assertEqual('NO_CATEGORY_IN_CITY', recommend([profile('x')], request(category='Фотограф'))['status'])
        self.assertEqual('NO_MATCH', recommend([profile('x')], request(budget_kzt=10))['status'])

    def test_format_language_duration_filters(self):
        rows = [profile('format', formats='корпоратив'), profile('language', languages='казахский'), profile('duration', max_hours='2')]
        self.assertEqual('NO_MATCH', recommend(rows, request())['status'])
        counts = recommend(rows, request())['exclusions']
        self.assertEqual((1,1,1), (counts['format'], counts['language'], counts['duration']))

    def test_none_max_hours_not_filtered(self):
        self.assertEqual('MATCHED', recommend([profile('x', max_hours='')], request(hours=100))['status'])

    def test_max_three_stable_and_input_order_independent(self):
        rows = [profile(str(i), price=100+i) for i in range(5)]
        expected = ['0','1','2']
        req = request(budget_kzt=200)
        self.assertEqual(expected, [c['id'] for c in recommend(rows, req)['cards']])
        self.assertEqual(expected, [c['id'] for c in recommend(list(reversed(rows)), req)['cards']])
        self.assertEqual(expected, [c['id'] for c in recommend(rows, req)['cards']])


    def test_normalizes_multiple_spaces_in_request_and_catalog(self):
        row = profile('spaces', category='Банкетный   зал')
        row['city'] = 'Алматы'
        result = recommend([row], request(category='Банкетный зал', city='Алматы  '))
        self.assertEqual('MATCHED', result['status'])
        self.assertEqual(['spaces'], [card['id'] for card in result['cards']])

    def test_none_required_text_is_missing(self):
        for field in ('city', 'date', 'event_format', 'category'):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    recommend([profile('x')], request(**{field: None}))

    def test_outside_dates_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Для этой даты нет данных о занятости'):
            recommend([profile('x')], request(date='2027-01-01'))

if __name__ == '__main__': unittest.main()
