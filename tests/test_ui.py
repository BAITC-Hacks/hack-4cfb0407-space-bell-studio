import unittest
from pathlib import Path
from datetime import date
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from tests.test_agent import ROWS, REQUEST, fake_client
from agent import run_matching

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
        self.assertEqual(3, sum(item.value in [card['anon_name'] for card in app.session_state['last_result']['cards']] for item in app.subheader))
        self.assertIn('показываем 3', app.success[0].value)
        self.assertTrue(app.checkbox[0].value)
        self.assertTrue(any('длительность 4 ч' in item.value for item in app.markdown))
        self.assertTrue(any('Локальное объяснение' in item.value for item in app.caption))
        self.assertTrue(any('Синтетический' in item.value for item in app.caption))
        self.assertTrue(any('Город оценочный' in item.value for item in app.caption))
        self.assertTrue(any('Цена оценочная' in item.value for item in app.caption))

    def test_ai_mode_separates_python_facts_from_verified_evidence(self):
        result = run_matching(ROWS, REQUEST, api_key='offline-test', client=fake_client()[1])
        self.assertEqual('ai_evidence', result['source'])
        with patch('agent.run_matching', return_value=result):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20).run()
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any('✨ AI-assisted explanation' in item.value for item in app.caption))
        self.assertTrue(any('Подбор, фильтры и порядок рассчитаны Python' in item.value for item in app.caption))
        self.assertEqual(len(result['cards']), sum('Почему прошёл фильтры' in item.value for item in app.markdown))
        self.assertEqual(len(result['cards']), sum('AI-выбранная деталь профиля' in item.value for item in app.markdown))
        for card in result['cards']:
            self.assertEqual(1, sum(card['selected_evidence'] in item.value for item in app.markdown))

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
        self.assertEqual(1, len(app.subheader))
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
        self.assertTrue(any('По текущим условиям подходящих вариантов нет' in item.value for item in app.warning))
        self.assertTrue(any('Выше бюджета' in item.value for item in app.markdown))

    def test_plan_b_scenario_f_keeps_original_query_and_shows_both_options(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20).run()
        for widget in app.selectbox:
            if widget.label == 'Город': widget.set_value('Алматы')
            elif widget.label == 'Формат': widget.set_value('день рождения')
            elif widget.label == 'Категория': widget.set_value('Банкетный зал')
        app.date_input[0].set_value(date(2026, 9, 26))
        app.number_input[0].set_value(2000000)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual('NO_MATCH', app.session_state['last_result']['status'])
        self.assertEqual([], app.session_state['last_result']['cards'])
        self.assertEqual('2026-09-26', app.session_state['last_request']['date'])
        self.assertTrue(any('План Б' in item.value for item in app.subheader))
        self.assertTrue(any('Попробовать другую дату' in item.value for item in app.markdown))
        self.assertTrue(any('28.09.2026' in item.value for item in app.markdown))
        self.assertTrue(any('2 500 000' in item.value for item in app.markdown))
        self.assertTrue(any('Диагностика' == item.label for item in app.expander))

    def test_submitted_snapshot_survives_form_edit_and_no_category_has_no_plan_b(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20).run()
        for widget in app.selectbox:
            if widget.label == 'Город': widget.set_value('Алматы')
            elif widget.label == 'Формат': widget.set_value('корпоратив')
            elif widget.label == 'Категория': widget.set_value('Банкетный зал')
        app.date_input[0].set_value(date(2026, 9, 26))
        app.number_input[0].set_value(10000000)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual('MATCHED', app.session_state['last_result']['status'])
        self.assertNotIn('alternatives', app.session_state['last_result'])
        app.selectbox[0].set_value('Зарубежье').run()
        self.assertFalse(app.exception)
        self.assertEqual('Алматы', app.session_state['last_request']['city'])
        self.assertTrue(any('Алматы · 26.09.2026' in item.value for item in app.markdown))
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual('NO_CATEGORY_IN_CITY', app.session_state['last_result']['status'])
        self.assertNotIn('alternatives', app.session_state['last_result'])

    def test_comparison_and_delta_update_only_on_submit(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=20).run()
        for widget in app.selectbox:
            if widget.label == 'Город': widget.set_value('Алматы')
            elif widget.label == 'Формат': widget.set_value('день рождения')
            elif widget.label == 'Категория': widget.set_value('Банкетный зал')
        app.date_input[0].set_value(date(2026, 9, 23))
        app.number_input[0].set_value(10000000)
        app.button[0].click().run()
        self.assertIsNone(app.session_state['previous_submitted_request'])
        self.assertFalse(any(item.value == 'Что изменилось с прошлого подбора' for item in app.subheader))
        app.date_input[0].set_value(date(2026, 9, 26)).run()
        self.assertEqual('2026-09-23', app.session_state['last_submitted_request']['date'])
        self.assertIsNone(app.session_state['previous_submitted_request'])
        app.button[0].click().run()
        self.assertEqual('2026-09-23', app.session_state['previous_submitted_request']['date'])
        self.assertEqual('2026-09-26', app.session_state['last_submitted_request']['date'])
        self.assertTrue(any(item.value == 'Что изменилось с прошлого подбора' for item in app.subheader))
        self.assertFalse(app.exception)

if __name__ == '__main__': unittest.main()
