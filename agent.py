"""OpenAI tool-calling adapter; catalog.recommend remains the sole decision maker."""

import json
import os
from copy import deepcopy
from time import perf_counter

from catalog import recommend

MODEL = "gpt-4.1-mini"
TOOL_NAME = "recommend_contractors"
TOOL = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": "Apply the catalog's strict deterministic filters and return ordered contractor cards for the current form request.",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "strict": True,
    },
}
SYSTEM = (
    "Ты помощник Firebird Match. Всегда вызывай recommend_contractors для подбора. "
    "Используй только результат инструмента, не добавляй факты из собственных знаний. "
    "Нельзя менять ID, кандидатов, порядок, цены, город, календарь или результат фильтров. "
    "Объясни максимум три выбранных профиля в том же порядке. Для каждого дай 1–2 конкретных предложения: "
    "дата только 'по календарю датасета не занята', цена именно 'от', бюджет, формат, язык и длительность если заданы, "
    "а также индивидуальная деталь из description. Субъективные заявления атрибутируй: 'В профиле указано, что...'. "
    "Не обещай бронь, не придумывай опыт, услуги, отзывы и рейтинг. "
    "Если кандидатов меньше трёх, объясни причину из fewer_reason. "
    "При NO_MATCH объясни фактические пересекающиеся причины исключения; при NO_CATEGORY_IN_CITY скажи, "
    "что в каталоге города нет профиля этой категории. "
    "Ответь только JSON объектом с полями explanations (словарь ID -> текст) и summary (строка)."
)


def recommend_contractors(catalog, request):
    """Deterministic tool payload, including source descriptions for grounded wording."""
    result = recommend(catalog, request)
    by_id = {row["id"]: row for row in catalog}
    cards = [dict(card, description=by_id[card["id"]]["description"]) for card in result["cards"]]
    return dict(result, request=dict(request), cards=cards,
                candidate_order=[card["id"] for card in result["cards"]])


def format_agent_result(tool_result, answer):
    """Accept only text for exact tool-selected IDs; preserve card facts and order."""
    output = deepcopy(tool_result)
    output["source"] = "deterministic"
    output["summary"] = ""
    if not isinstance(answer, dict) or not isinstance(answer.get("explanations"), dict):
        return output
    expected = output["candidate_order"]
    explanations = answer["explanations"]
    if set(explanations) != set(expected) or any(not isinstance(explanations[id], str) or not explanations[id].strip() for id in expected):
        return output
    if not isinstance(answer.get("summary"), str):
        return output
    for card in output["cards"]:
        card["explanation"] = explanations[card["id"]].strip()
    output["summary"] = answer["summary"].strip()
    output["source"] = "ai"
    return output


def run_matching(catalog, request, api_key=None, client=None):
    """Run one forced tool call, then generate prose; fall back to deterministic text."""
    key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
    if not key and client is None:
        result = format_agent_result(recommend_contractors(catalog, request), None)
        result.update(tool_calls=0, model=None, latency_seconds=None, ai_error="API key отсутствует")
        return result
    if client is None:
        from openai import OpenAI
        client = OpenAI(api_key=key, timeout=20.0, max_retries=0)
    started = perf_counter()
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "Подбери подрядчиков по форме: " + json.dumps(request, ensure_ascii=False)},
    ]
    tool_calls = 0
    tool_result = None
    try:
        first = client.chat.completions.create(
            model=MODEL, messages=messages, tools=[TOOL],
            tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
            temperature=0,
        )
        call_items = first.choices[0].message.tool_calls or []
        if len(call_items) != 1 or call_items[0].function.name != TOOL_NAME:
            raise RuntimeError("Ожидался один вызов recommend_contractors")
        if json.loads(call_items[0].function.arguments) != {}:
            raise RuntimeError("Инструмент не принимает изменённых параметров")
        tool_result = recommend_contractors(catalog, request)
        tool_calls = 1
        messages.append(first.choices[0].message)
        messages.append({"role": "tool", "tool_call_id": call_items[0].id,
                         "content": json.dumps(tool_result, ensure_ascii=False)})
        second = client.chat.completions.create(
            model=MODEL, messages=messages, response_format={"type": "json_object"},
            temperature=0,
        )
        answer = json.loads(second.choices[0].message.content or "")
        result = format_agent_result(tool_result, answer)
        if result["source"] != "ai":
            result["ai_error"] = "Некорректный формат AI-объяснения"
    except Exception as exc:
        # The local decision and cards remain available after an API failure.
        result = format_agent_result(tool_result or recommend_contractors(catalog, request), None)
        result["ai_error"] = f"{type(exc).__name__}: {exc}"
    result.update(tool_calls=tool_calls, model=MODEL, latency_seconds=perf_counter() - started)
    return result
