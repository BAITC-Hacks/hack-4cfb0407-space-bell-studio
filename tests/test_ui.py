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
        self.assertTrue(any('AI недоступен; показан локальный результат' in item.value for item in app.caption))

if __name__ == '__main__': unittest.main()
