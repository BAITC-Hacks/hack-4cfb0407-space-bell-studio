import unittest
from pathlib import Path
from datetime import date
from streamlit.testing.v1 import AppTest

class StreamlitSmokeTests(unittest.TestCase):
    def test_hours_control_and_matched_form_use_offline_fallback(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20).run()
        app.checkbox[0].set_value(True).run()
        self.assertFalse(app.number_input[1].disabled)
        for widget in app.selectbox:
            if widget.label == 'Город': widget.set_value('Алматы')
            elif widget.label == 'Тип мероприятия': widget.set_value('корпоратив')
            elif widget.label == 'Категория подрядчика': widget.set_value('Банкетный зал')
        app.date_input[0].set_value(date(2026, 9, 26))
        app.number_input[0].set_value(10000000)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(3, len(app.subheader))
        self.assertIn('Показано: 3.', app.success[0].value)
        self.assertTrue(any('AI недоступен; показан локальный результат' in item.value for item in app.caption))
        self.assertTrue(any('Синтетический профиль' in item.value for item in app.caption))
        self.assertTrue(any('Город оценочный' in item.value for item in app.caption))
        self.assertTrue(any('Цена оценочная' in item.value for item in app.caption))

    def test_rare_case_shows_actual_count_and_optional_language(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20).run()
        for widget in app.selectbox:
            if widget.label == 'Город': widget.set_value('Алматы')
            elif widget.label == 'Тип мероприятия': widget.set_value('конференция')
            elif widget.label == 'Категория подрядчика': widget.set_value('Флорист')
            elif widget.label == 'Язык (необязательно)': widget.set_value('русский')
        app.date_input[0].set_value(date(2026, 9, 23))
        app.number_input[0].set_value(10000000)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(1, len(app.subheader))
        self.assertIn('Показано: 1.', app.success[0].value)
        self.assertTrue(any('профилей этой категории: 2' in item.value for item in app.info))

    def test_no_category_and_no_match_messages(self):
        path = str(Path(__file__).resolve().parents[1] / 'app.py')
        app = AppTest.from_file(path, default_timeout=20).run()
        for widget in app.selectbox:
            if widget.label == 'Город': widget.set_value('Зарубежье')
            elif widget.label == 'Категория подрядчика': widget.set_value('Банкетный зал')
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any('нет профиля категории' in item.value for item in app.warning))

        app = AppTest.from_file(path, default_timeout=20).run()
        for widget in app.selectbox:
            if widget.label == 'Город': widget.set_value('Алматы')
            elif widget.label == 'Тип мероприятия': widget.set_value('корпоратив')
            elif widget.label == 'Категория подрядчика': widget.set_value('Банкетный зал')
        app.date_input[0].set_value(date(2026, 9, 26))
        app.number_input[0].set_value(1)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any('ни один не прошёл' in item.value for item in app.warning))
        self.assertTrue(any('начальная цена выше бюджета' in item.value for item in app.markdown))

if __name__ == '__main__': unittest.main()
