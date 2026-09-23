"""Streamlit workspace for deterministic Firebird matching and Plan B."""
from datetime import date
from pathlib import Path

import streamlit as st

from agent import run_matching
from catalog import load_catalog
from cli import demo_requests
from comparison import before_selection, comparison_rows, profile_detail, query_delta
from plan_b import with_alternatives

CATALOG_PATH = Path(__file__).resolve().with_name("contractors.csv")
MIN_DATE, MAX_DATE = date(2026, 9, 23), date(2026, 12, 31)
REASONS = {
    "busy": "Заняты на выбранную дату", "over_budget": "Выше бюджета",
    "format": "Другой формат", "language": "Другой язык",
    "duration": "Не подходит длительность",
}
ERROR_LABELS = {
    "KEY_MISSING": "ключ не задан", "AUTH_ERROR": "ошибка авторизации",
    "QUOTA_OR_RATE_LIMIT": "лимит API", "MODEL_ACCESS_ERROR": "модель недоступна",
    "TIMEOUT": "превышен бюджет ожидания", "NETWORK_ERROR": "сетевая ошибка",
    "RESPONSE_INVALID": "ответ не прошёл проверку",
    "SDK_OR_CONFIG_ERROR": "ошибка конфигурации клиента",
}


@st.cache_data
def catalog():
    return load_catalog(CATALOG_PATH)


def money(value):
    return f"{value:,.0f}".replace(",", " ")


def profile_word(count):
    if count % 100 in (11, 12, 13, 14):
        return "подходящих профилей"
    if count % 10 == 1:
        return "подходящий профиль"
    if count % 10 in (2, 3, 4):
        return "подходящих профиля"
    return "подходящих профилей"


def query_summary(request):
    shown_date = date.fromisoformat(request["date"]).strftime("%d.%m.%Y")
    parts = [request["city"], shown_date, request["event_format"],
             request["category"], f"до {money(request['budget_kzt'])} ₸"]
    if request.get("language"):
        parts.append(request["language"])
    if request.get("hours") is not None:
        parts.append(f"{request['hours']:g} ч")
    return " · ".join(parts)


st.set_page_config(page_title="Firebird Match", page_icon="🔥", layout="wide")
st.title("🔥 Firebird Match")
st.caption("Подбор event-подрядчиков по календарю, бюджету и условиям заказа")
try:
    rows = catalog()
except (OSError, ValueError):
    st.error("Не удалось прочитать каталог. Проверьте contractors.csv и его формат.")
    st.stop()

cities = sorted({p["city"] for p in rows})
formats = sorted({f for p in rows for f in p["event_formats"]})
categories = sorted({c for p in rows for c in p["categories"]})
languages = sorted({l for p in rows for l in p["languages"]})
default_day = min(max(date.today(), MIN_DATE), MAX_DATE)
st.session_state.setdefault("last_request", None)
st.session_state.setdefault("last_result", None)
st.session_state.setdefault("last_submitted_request", None)
st.session_state.setdefault("previous_submitted_request", None)
st.session_state.setdefault("previous_result", None)

left, right = st.columns([1, 2], gap="large")
with left:
    with st.container(border=True):
        st.header("Параметры мероприятия")
        with st.form("request"):
            city = st.selectbox("Город", cities)
            event_date = st.date_input("Дата", value=default_day, min_value=MIN_DATE, max_value=MAX_DATE)
            event_format = st.selectbox("Формат", formats)
            category = st.selectbox("Категория", categories)
            budget = st.number_input("Бюджет, ₸", min_value=1, value=1000000, step=10000, format="%d")
            with st.expander("Дополнительные условия"):
                language = st.selectbox("Язык", ["Не выбран"] + languages)
                use_hours = st.checkbox("Учитывать длительность")
                hours = st.number_input("Длительность, часы", min_value=0.5, value=4.0, step=0.5,
                                        help="Учитывается только при установленном флажке")
            submitted = st.form_submit_button("Подобрать подрядчиков", type="primary", width="stretch")
        st.caption(f"{len(rows)} профилей · {len(categories)} категорий · календарь {MIN_DATE:%d.%m}–{MAX_DATE:%d.%m.%Y}")

    with st.expander("Демо-сценарии A–F"):
        st.caption("Выберите параметры в форме. Результат всегда вычисляется из каталога.")
        for label, demo in demo_requests(rows).items():
            shown_date = date.fromisoformat(demo["date"]).strftime("%d.%m.%Y")
            st.write(f"**{label}** · {demo['city']} · {shown_date} · {demo['event_format']} · "
                     f"{demo['category']} · {money(demo['budget_kzt'])} ₸")

if submitted:
    request = {
        "city": city, "date": event_date.isoformat(), "event_format": event_format,
        "category": category, "budget_kzt": budget,
        "hours": hours if use_hours else None,
        "language": None if language == "Не выбран" else language,
    }
    try:
        with st.spinner("Подбираем подрядчиков…"):
            result = with_alternatives(rows, request, run_matching(rows, request))
    except ValueError:
        st.error("Проверьте дату, бюджет и параметры заказа.")
        st.stop()
    st.session_state.previous_submitted_request = st.session_state.last_submitted_request
    st.session_state.previous_result = st.session_state.last_result
    st.session_state.last_submitted_request = request.copy()
    st.session_state.last_request = request.copy()
    st.session_state.last_result = result

with right:
    st.header("Результаты подбора")
    request = st.session_state.last_submitted_request
    result = st.session_state.last_result
    if result is None:
        st.info("Укажите условия мероприятия и нажмите «Подобрать подрядчиков».")
    else:
        st.caption("Последний выполненный запрос")
        st.markdown(f"**{query_summary(request)}**")
        if result["status"] == "MATCHED":
            st.success(f"Найдено {result['eligible_count']} {profile_word(result['eligible_count'])} · показываем {len(result['cards'])}")
        elif result["status"] == "NO_CATEGORY_IN_CITY":
            st.warning(f"В каталоге города {request['city']} нет категории «{request['category']}»")
        else:
            st.warning("По текущим условиям подходящих вариантов нет")
        if result["source"] == "ai_evidence":
            st.caption("✨ AI-assisted explanation · Подбор, фильтры и порядок рассчитаны Python.")
        else:
            st.caption("Локальное объяснение · подбор, фильтры и порядок рассчитаны Python.")

        if result["status"] == "MATCHED":
            for start in range(0, len(result["cards"]), 2):
                card_columns = st.columns(2, gap="medium")
                for index, card in enumerate(result["cards"][start:start + 2]):
                    with card_columns[index]:
                        with st.container(border=True):
                            st.subheader(card["anon_name"])
                            st.caption(f"{card['category']} · {card['city']}")
                            st.markdown(f"### {card['price_label']}")
                            st.markdown("**Почему прошёл фильтры**")
                            st.markdown(card["deterministic_facts"])
                            evidence = profile_detail(card)
                            if evidence:
                                st.markdown("**AI-выбранная деталь профиля**" if result["source"] == "ai_evidence" else "**Деталь профиля**")
                                st.markdown(f"«{evidence}»")
                            badges = ["Синтетический" if card["synthetic"] else "Анонимизированный"]
                            if card["city_imputed"]:
                                badges.append("Город оценочный")
                            if card["price_imputed"]:
                                badges.append("Цена оценочная")
                            st.caption(" · ".join(badges))
                            st.markdown("**Перед выбором уточнить**")
                            st.caption("; ".join(before_selection(card)))

            compared = comparison_rows(result["cards"], request, rows)
            if compared:
                st.subheader("Сравнение вариантов")
                st.caption("Фактические различия профилей, без рейтинга. Деталь профиля выбрана AI только в AI режиме.")
                comparison_columns = st.columns(len(compared), gap="small")
                for column, entry in zip(comparison_columns, compared):
                    with column:
                        with st.container(border=True):
                            for key, value in entry.items():
                                st.markdown(f"**{key}**")
                                st.caption(value)

        delta = query_delta(rows, st.session_state.previous_submitted_request,
                            st.session_state.previous_result, request, result)
        if delta:
            st.subheader("Что изменилось с прошлого подбора")
            for line in delta["lines"]:
                st.write(line)

        if result["status"] == "NO_MATCH" or (result["status"] == "MATCHED" and len(result["cards"]) < 3):
            with st.container(border=True):
                st.markdown("**Почему вариантов меньше трёх**" if result["status"] == "MATCHED" else "**Почему кандидаты исключены**")
                st.markdown(f"В городе профилей этой категории: **{result['category_count']}**")
                reasons = [(REASONS[key], count) for key, count in result["exclusions"].items() if count]
                if not reasons:
                    st.write("В выбранном городе мало профилей этой категории.")
                for label, count in reasons:
                    st.markdown(f"{label}: **{count}**")
            st.caption("Один профиль может иметь несколько причин исключения.")

        if result["status"] == "NO_MATCH":
            st.subheader("План Б")
            alternatives = result["alternatives"]
            alternative_date = alternatives["alternative_date"]
            minimum_budget = alternatives["minimum_budget"]
            if alternative_date:
                with st.container(border=True):
                    st.markdown("**Попробовать другую дату**")
                    shown_date = date.fromisoformat(alternative_date["alternative_date"]).strftime("%d.%m.%Y")
                    st.write(f"На {shown_date} найдено {alternative_date['eligible_count']} "
                             f"{profile_word(alternative_date['eligible_count'])} при тех же остальных условиях.")
            if minimum_budget:
                with st.container(border=True):
                    st.markdown("**Изменить бюджет**")
                    st.write(f"Первый вариант появляется при минимальной начальной цене «от» "
                             f"{money(minimum_budget['minimum_budget_kzt'])} ₸ при тех же остальных условиях.")
                    st.caption("Это не окончательная стоимость.")
            if not alternative_date and not minimum_budget:
                st.info("Одного изменения даты или бюджета недостаточно.")

        with st.expander("Диагностика"):
            st.write(f"Запрошенная модель: {result['requested_model']}")
            st.write(f"Возвращённая модель: {result['returned_model'] or 'нет'}")
            elapsed = result["latency_seconds"]
            st.write(f"Полное время: {elapsed:.2f} с" if elapsed is not None else "Полное время: не замерялось")
            st.write(f"API вызовы: {result['api_calls']}; tool calls: {result['tool_calls']}")
            if result.get("error_code"):
                st.write(f"Код ошибки: {result['error_code']} — {ERROR_LABELS.get(result['error_code'], 'ошибка')}")
            if result.get("skipped_reason"):
                st.write("Причина пропуска AI: кандидатов нет")

with st.expander("Как работает подбор?"):
    st.markdown("""1. Проверяем город и категорию.
2. Исключаем занятых на выбранную дату.
3. Проверяем бюджет и формат.
4. При необходимости проверяем язык и длительность.
5. Сортируем стабильно по цене «от», затем ID.
6. Показываем до трёх вариантов.
7. AI при наличии выбирает релевантную деталь из уже проверенного профиля.
8. Если никто не подошёл, отдельно проверяем изменение только даты или только бюджета.

Основные ограничения никогда не ослабляются автоматически. Цена «от» и свободный день в датасете не гарантируют окончательную стоимость или бронь.""")
