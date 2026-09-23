import unittest
from pathlib import Path
from datetime import date
from streamlit.testing.v1 import AppTest

class StreamlitSmokeTests(unittest.TestCase):
    def test_matched_form_uses_offline_fallback(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20).run()
        app.checkbox[0].set_value(True)
        for widget in app.selectbox:
            if widget.label == 'Город': widget.set_value('Алматы')
            elif widget.label == 'Формат': widget.set_value('корпоратив')
            elif widget.label == 'Категория': widget.set_value('Банкетный зал')
        app.date_input[0].set_value(date(2026, 9, 26))
        app.number_input[0].set_value(10000000)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(4, len(app.subheader))
        self.assertIn('показываем 3', app.success[0].value)
        self.assertTrue(app.checkbox[0].value)
        self.assertTrue(any('длительность 4 ч' in item.value for item in app.markdown))
        self.assertTrue(any('Проверенное локальное объяснение' in item.value for item in app.caption))
        self.assertTrue(any('Синтетический' in item.value for item in app.caption))
        self.assertTrue(any('Город оценочный' in item.value for item in app.caption))
        self.assertTrue(any('Цена оценочная' in item.value for item in app.caption))

    def test_rare_case_shows_actual_count_and_optional_language(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20).run()
        for widget in app.selectbox:
            if widget.label == 'Город': widget.set_value('Алматы')
            elif widget.label == 'Формат': widget.set_value('конференция')
            elif widget.label == 'Категория': widget.set_value('Флорист')
            elif widget.label == 'Язык': widget.set_value('русский')
        app.date_input[0].set_value(date(2026, 9, 23))
        app.number_input[0].set_value(10000000)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(2, len(app.subheader))
        self.assertIn('показываем 1', app.success[0].value)
        self.assertTrue(any('Почему вариантов меньше трёх' in item.value for item in app.markdown))
        self.assertTrue(any('В городе профилей этой категории: **2**' in item.value for item in app.markdown))
        self.assertTrue(any('Один профиль может' in item.value for item in app.caption))

    def test_no_category_and_no_match_messages(self):
        path = str(Path(__file__).resolve().parents[1] / 'app.py')
        app = AppTest.from_file(path, default_timeout=20).run()
        for widget in app.selectbox:
            if widget.label == 'Город': widget.set_value('Зарубежье')
            elif widget.label == 'Категория': widget.set_value('Банкетный зал')
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any('нет категории' in item.value for item in app.warning))

        app = AppTest.from_file(path, default_timeout=20).run()
        for widget in app.selectbox:
            if widget.label == 'Город': widget.set_value('Алматы')
            elif widget.label == 'Формат': widget.set_value('корпоратив')
            elif widget.label == 'Категория': widget.set_value('Банкетный зал')
        app.date_input[0].set_value(date(2026, 9, 26))
        app.number_input[0].set_value(1)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any('исключили всех кандидатов' in item.value for item in app.warning))
        self.assertTrue(any('Выше бюджета' in item.value for item in app.markdown))

if __name__ == '__main__': unittest.main()
