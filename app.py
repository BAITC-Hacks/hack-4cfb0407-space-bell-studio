"""Streamlit form for deterministic matching and evidence-grounded explanations."""
from datetime import date
from pathlib import Path
import streamlit as st
from agent import run_matching
from catalog import load_catalog
from cli import demo_requests

CATALOG_PATH = Path(__file__).resolve().with_name('contractors.csv')
MIN_DATE, MAX_DATE = date(2026, 9, 23), date(2026, 12, 31)
REASONS = {'busy':'Заняты на выбранную дату', 'over_budget':'Выше бюджета', 'format':'Другой формат', 'language':'Другой язык', 'duration':'Не подходит длительность'}
ERROR_LABELS = {
    'KEY_MISSING':'ключ не задан', 'AUTH_ERROR':'ошибка авторизации',
    'QUOTA_OR_RATE_LIMIT':'лимит API', 'MODEL_ACCESS_ERROR':'модель недоступна',
    'TIMEOUT':'превышен бюджет ожидания', 'NETWORK_ERROR':'сетевая ошибка',
    'RESPONSE_INVALID':'ответ не прошёл проверку', 'SDK_OR_CONFIG_ERROR':'ошибка конфигурации клиента',
}

@st.cache_data
def catalog():
    return load_catalog(CATALOG_PATH)

st.set_page_config(page_title='Firebird Match', page_icon='🔥', layout='wide')
st.title('🔥 Firebird Match')
st.subheader('Подберите до 3 event-подрядчиков по реальным ограничениям заказа')
st.write('Сначала проверяем календарь, бюджет и формат. Затем объясняем, почему выбран каждый кандидат.')
try:
    rows = catalog()
except (OSError, ValueError):
    st.error('Не удалось прочитать каталог. Проверьте contractors.csv и его формат.')
    st.stop()
cities = sorted({p['city'] for p in rows})
formats = sorted({f for p in rows for f in p['event_formats']})
categories = sorted({c for p in rows for c in p['categories']})
languages = sorted({l for p in rows for l in p['languages']})
st.caption(f"{len(rows)} профилей · {len(categories)} категорий · {' / '.join(cities)}")
st.caption('Цена указана «от». Свободная дата по календарю датасета не подтверждает бронь.')
today = date.today()
default_day = min(max(today, MIN_DATE), MAX_DATE)
def profile_word(count):
    if count % 100 in (11, 12, 13, 14): return 'подходящих профилей'
    if count % 10 == 1: return 'подходящий профиль'
    if count % 10 in (2, 3, 4): return 'подходящих профиля'
    return 'подходящих профилей'

with st.form('request'):
    first = st.columns(3, gap='medium')
    with first[0]: city = st.selectbox('Город', cities)
    with first[1]: event_date = st.date_input('Дата', value=default_day, min_value=MIN_DATE, max_value=MAX_DATE)
    with first[2]: event_format = st.selectbox('Формат', formats)
    second = st.columns([2, 1], gap='medium')
    with second[0]: category = st.selectbox('Категория', categories)
    with second[1]:
        budget = st.number_input('Бюджет, ₸', min_value=1, value=1000000, step=10000, format='%d')
    with st.expander('Дополнительные условия'):
        optional = st.columns(2, gap='medium')
        with optional[0]: language = st.selectbox('Язык', ['Не выбран'] + languages)
        with optional[1]:
            use_hours = st.checkbox('Учитывать длительность')
            hours = st.number_input('Длительность, часы', min_value=0.5, value=4.0, step=0.5,
                                    help='Учитывается только при установленном флажке')
    submitted = st.form_submit_button('🔥 Подобрать подрядчиков', type='primary', use_container_width=True)

with st.expander('Демо-сценарии'):
    st.caption('Выберите эти параметры в форме и нажмите кнопку подбора. Результат всегда вычисляется из каталога.')
    for label, demo in demo_requests(rows).items():
        shown_date = date.fromisoformat(demo['date']).strftime('%d.%m.%Y')
        shown_budget = f"{demo['budget_kzt']:,}".replace(',', ' ')
        st.write(f"**{label}** · {demo['city']} · {shown_date} · {demo['event_format']} · {demo['category']} · {shown_budget} ₸")

if submitted:
    request = {'city':city, 'date':event_date.isoformat(), 'event_format':event_format, 'category':category,
               'budget_kzt':budget, 'hours':hours if use_hours else None,
               'language':None if language == 'Не выбран' else language}
    try:
        with st.spinner('Подбираем подрядчиков…'):
            result = run_matching(rows, request)
    except ValueError:
        st.error('Проверьте дату, бюджет и параметры заказа.')
        st.stop()
    st.divider()
    if result['status'] == 'MATCHED':
        st.success(f"Найдено {result['eligible_count']} {profile_word(result['eligible_count'])} · показываем {len(result['cards'])}")
    elif result['status'] == 'NO_CATEGORY_IN_CITY':
        st.warning(f'В каталоге города {city} нет категории «{category}»')
    else:
        st.warning('Профили категории есть, но условия заказа исключили всех кандидатов')
    if result['source'] == 'ai_evidence':
        st.caption('✨ AI-assisted explanation · Подбор и порядок рассчитаны Python')
    else:
        st.caption('✓ Проверенное локальное объяснение · AI сейчас не использовался; подбор полностью рассчитан локально.')
    if result['status'] == 'MATCHED':
        for card in result['cards']:
            with st.container(border=True):
                st.subheader(card['anon_name'])
                st.caption(f"{card['category']} · {card['city']}")
                st.markdown(f"### {card['price_label']}")
                st.markdown('**Почему подходит**')
                st.write(card['explanation'])
                badges = ['Синтетический' if card['synthetic'] else 'Анонимизированный']
                if card['city_imputed']: badges.append('Город оценочный')
                if card['price_imputed']: badges.append('Цена оценочная')
                st.caption(' · '.join(badges))
    if result['status'] == 'NO_MATCH' or (result['status'] == 'MATCHED' and len(result['cards']) < 3):
        with st.container(border=True):
            st.markdown('**Почему вариантов меньше трёх**')
            st.write(f"В городе профилей этой категории: **{result['category_count']}**")
            reasons = [(REASONS[reason], count) for reason, count in result['exclusions'].items() if count]
            if not reasons: st.write('В выбранном городе мало профилей этой категории.')
            for label, count in reasons: st.write(f'{label}: **{count}**')
        st.caption('Один профиль может иметь несколько причин исключения.')
    with st.expander('Диагностика'):
        st.write(f"Запрошенная модель: {result['requested_model']}")
        st.write(f"Возвращённая модель: {result['returned_model'] or 'нет'}")
        elapsed = result['latency_seconds']
        st.write(f"Полное время: {elapsed:.2f} с" if elapsed is not None else 'Полное время: не замерялось')
        st.write(f"API вызовы: {result['api_calls']}; tool calls: {result['tool_calls']}")
        if result.get('error_code'):
            st.write(f"Код ошибки: {result['error_code']} — {ERROR_LABELS.get(result['error_code'], 'ошибка')}")
        if result.get('skipped_reason'):
            st.write('Причина пропуска AI: кандидатов нет')

with st.expander('Как работает подбор?'):
    st.markdown('''1. Проверяем город и категорию.
2. Исключаем занятых на выбранную дату.
3. Проверяем бюджет и формат.
4. При необходимости проверяем язык и длительность.
5. Сортируем стабильно по цене «от», затем ID.
6. Показываем до трёх вариантов.
7. AI при наличии выбирает релевантную деталь из уже проверенного профиля.''')
