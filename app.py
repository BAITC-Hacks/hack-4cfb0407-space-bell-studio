"""Streamlit form for deterministic matching and evidence-grounded explanations."""
from datetime import date
from pathlib import Path
import streamlit as st
from agent import run_matching
from catalog import load_catalog

CATALOG_PATH = Path(__file__).resolve().with_name('contractors.csv')
MIN_DATE, MAX_DATE = date(2026, 9, 23), date(2026, 12, 31)
REASONS = {'busy':'занят по календарю', 'over_budget':'начальная цена выше бюджета', 'format':'не подходит формат', 'language':'не подходит язык', 'duration':'не подходит длительность'}
ERROR_LABELS = {
    'KEY_MISSING':'ключ не задан', 'AUTH_ERROR':'ошибка авторизации',
    'QUOTA_OR_RATE_LIMIT':'лимит API', 'MODEL_ACCESS_ERROR':'модель недоступна',
    'TIMEOUT':'превышен бюджет ожидания', 'NETWORK_ERROR':'сетевая ошибка',
    'RESPONSE_INVALID':'ответ не прошёл проверку', 'SDK_OR_CONFIG_ERROR':'ошибка конфигурации клиента',
}

@st.cache_data
def catalog():
    return load_catalog(CATALOG_PATH)

st.set_page_config(page_title='Firebird Match', page_icon='🔥')
st.title('Firebird Match')
st.write('Подбор подрядчиков по каталогу Firebird #79-lite')
st.caption('Цена указана «от». Свободная дата по календарю датасета не подтверждает бронь.')
try:
    rows = catalog()
except (OSError, ValueError):
    st.error('Не удалось прочитать каталог. Проверьте contractors.csv и его формат.')
    st.stop()
cities = sorted({p['city'] for p in rows})
formats = sorted({f for p in rows for f in p['event_formats']})
categories = sorted({c for p in rows for c in p['categories']})
languages = sorted({l for p in rows for l in p['languages']})
today = date.today()
default_day = min(max(today, MIN_DATE), MAX_DATE)
# Outside the form so toggling immediately enables/disables the field without submitting.
use_hours = st.checkbox('Указать длительность', key='use_hours')
with st.form('request'):
    city = st.selectbox('Город', cities)
    event_date = st.date_input('Дата', value=default_day, min_value=MIN_DATE, max_value=MAX_DATE)
    event_format = st.selectbox('Тип мероприятия', formats)
    category = st.selectbox('Категория подрядчика', categories)
    budget = st.number_input('Бюджет, ₸', min_value=1, value=1000000, step=10000)
    hours = st.number_input('Длительность, часы', min_value=0.5, value=4.0, step=0.5, disabled=not use_hours)
    language = st.selectbox('Язык (необязательно)', ['Не выбран'] + languages)
    submitted = st.form_submit_button('Подобрать подрядчиков')

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
    if result['source'] == 'ai_evidence':
        st.caption('AI выбрал детали из профилей; факты запроса проверены кодом. Цитаты — заявления из профилей.')
    elif result.get('skipped_reason') == 'NO_CANDIDATES':
        st.caption('Объяснение по правилам; AI не запускался, поскольку кандидатов нет.')
    elif result.get('error_code'):
        st.caption('AI недоступен; показан локальный результат.')
    else:
        st.caption('Объяснение по правилам; AI не запускался.')
    if result['status'] == 'MATCHED':
        st.success(f"Найдено подходящих профилей: {result['eligible_count']}. Показано до трёх.")
        for card in result['cards']:
            with st.container(border=True):
                st.subheader(card['anon_name'])
                st.write(f"{card['category']} · {card['city']} · **{card['price_label']}**")
                st.text(card['explanation'])
                st.caption('Синтетический профиль' if card['synthetic'] else 'Анонимизированный профиль')
                if card['city_imputed']: st.caption('Город оценочный')
                if card['price_imputed']: st.caption('Цена оценочная')
        if result.get('summary'): st.info(result['summary'])
    elif result['status'] == 'NO_CATEGORY_IN_CITY':
        st.warning(f"В каталоге города {city} нет профиля категории «{category}».")
        st.write(result['summary'])
    else:
        st.warning('В этой категории есть профили, но ни один не прошёл все условия заказа.')
        st.caption('Один профиль может учитываться в нескольких причинах исключения.')
        for reason, count in result['exclusions'].items():
            if count: st.write(f"{REASONS[reason]}: {count}")
        st.write(result['summary'])
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
