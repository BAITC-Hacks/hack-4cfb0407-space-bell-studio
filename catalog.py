import csv
import math
import re
from datetime import date
from pathlib import Path

REQUIRED_COLUMNS = {
    "id", "anon_name", "categories", "city", "city_imputed", "synthetic",
    "price_from_kzt", "price_imputed", "event_formats", "languages",
    "max_hours", "busy_dates", "description",
}
LIST_FIELDS = ("categories", "event_formats", "languages", "busy_dates")
BOOL_FIELDS = ("city_imputed", "synthetic", "price_imputed")


def _parse_bool(value, field, row_number):
    normalized = value.strip().casefold()
    if normalized not in {"true", "false"}:
        raise ValueError(f"Строка {row_number}: {field} должен быть True или False")
    return normalized == "true"


def load_catalog(path):
    """Load and validate contractor rows from a UTF-8 CSV file."""
    records = []
    ids = set()
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError("CSV не содержит заголовка")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError("В CSV отсутствуют обязательные столбцы: " + ", ".join(sorted(missing)))
        for row_number, raw in enumerate(reader, start=2):
            row = {key: (value or "").strip() for key, value in raw.items() if key is not None}
            if not row.get("id"):
                raise ValueError(f"Строка {row_number}: пустой id")
            if row["id"] in ids:
                raise ValueError(f"Строка {row_number}: повторяется id {row['id']}")
            ids.add(row["id"])
            for field in LIST_FIELDS:
                row[field] = [item.strip() for item in row[field].split("|") if item.strip()]
            for field in BOOL_FIELDS:
                row[field] = _parse_bool(row[field], field, row_number)
            try:
                row["price_from_kzt"] = float(row["price_from_kzt"])
                row["max_hours"] = float(row["max_hours"]) if row["max_hours"] else None
                if not math.isfinite(row["price_from_kzt"]) or row["price_from_kzt"] <= 0:
                    raise ValueError("цена должна быть конечной и положительной")
                if row["max_hours"] is not None and (not math.isfinite(row["max_hours"]) or row["max_hours"] <= 0):
                    raise ValueError("max_hours должен быть конечным и положительным")
            except ValueError as exc:
                raise ValueError(f"Строка {row_number}: некорректное числовое значение") from exc
            for raw_day in row["busy_dates"]:
                try:
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_day):
                        raise ValueError
                    date.fromisoformat(raw_day)
                except ValueError as exc:
                    raise ValueError(f"Строка {row_number}: некорректная дата {raw_day}") from exc
            records.append(row)
    return records


def validate_request(request):
    """Validate query fields and return normalized fields alongside originals."""
    errors = []
    normalized = {}
    for field in ("city", "date", "event_format", "category"):
        value = str(request.get(field, "")).strip()
        if not value:
            errors.append(f"Поле {field} обязательно")
        normalized[field] = value.casefold()
    try:
        raw_date = str(request.get("date", "")).strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
            raise ValueError
        parsed_date = date.fromisoformat(raw_date)
        if parsed_date.isoformat() != str(request.get("date", "")).strip():
            raise ValueError
    except ValueError:
        errors.append("Дата должна быть в формате YYYY-MM-DD")
        parsed_date = None
    if parsed_date and not (date(2026, 9, 23) <= parsed_date <= date(2026, 12, 31)):
        errors.append("Для этой даты нет данных о занятости")
    try:
        budget = float(request.get("budget_kzt"))
        if budget <= 0 or budget != budget or budget in (float("inf"), float("-inf")):
            raise ValueError
    except (TypeError, ValueError):
        errors.append("Бюджет должен быть конечным положительным числом")
        budget = None
    normalized["budget_kzt"] = budget
    original_hours = request.get("hours")
    if original_hours in (None, ""):
        normalized["hours"] = None
    else:
        try:
            hours = float(original_hours)
            if hours <= 0 or hours != hours or hours in (float("inf"), float("-inf")):
                raise ValueError
            normalized["hours"] = hours
        except (TypeError, ValueError):
            errors.append("Длительность должна быть конечным положительным числом")
            normalized["hours"] = None
    language = str(request.get("language") or "").strip()
    normalized["language"] = language.casefold() or None
    normalized["date"] = parsed_date.isoformat() if parsed_date else ""
    if errors:
        raise ValueError("; ".join(errors))
    return normalized


def _norm(value):
    return " ".join(str(value).split()).casefold()


def _has(values, expected):
    return any(_norm(value) == expected for value in values)


def build_explanation(profile, request):
    money = lambda value: f"{value:,.0f}".replace(",", " ") if float(value).is_integer() else f"{value:,.2f}".replace(",", " ")
    pieces = [f"По календарю датасета дата {request['date']} не занята",
              f"начальная цена {money(profile['price_from_kzt'])} ₸ укладывается в бюджет {money(request['budget_kzt'])} ₸",
              f"подходит формат «{request['event_format']}»"]
    if request.get("language"):
        pieces.append(f"указан язык «{request['language']}»")
    if request.get("hours") is not None and profile["max_hours"] is not None:
        pieces.append(f"длительность {request['hours']:g} ч не превышает максимум {profile['max_hours']:g} ч")
    desc = " ".join(profile["description"].split())
    if len(desc) > 180:
        desc = desc[:177].rsplit(" ", 1)[0] + "…"
    return "; ".join(pieces) + ". В описании указано: «" + desc + "»"


def recommend(catalog, request):
    """Return status, up to three deterministic cards, and overlapping exclusion counts."""
    req = validate_request(request)
    group = [p for p in catalog if _norm(p["city"]) == req["city"] and _has(p["categories"], req["category"])]
    if not group:
        return {"status": "NO_CATEGORY_IN_CITY", "cards": [], "exclusions": {}}
    excluded = {key: 0 for key in ("busy", "over_budget", "format", "language", "duration")}
    eligible = []
    for p in group:
        reasons = []
        if req["date"] in p["busy_dates"]: reasons.append("busy")
        if p["price_from_kzt"] > req["budget_kzt"]: reasons.append("over_budget")
        if not _has(p["event_formats"], req["event_format"]): reasons.append("format")
        if req["language"] and not _has(p["languages"], req["language"]): reasons.append("language")
        if req["hours"] is not None and p["max_hours"] is not None and req["hours"] > p["max_hours"]: reasons.append("duration")
        if reasons:
            for reason in reasons: excluded[reason] += 1
        else:
            eligible.append(p)
    eligible.sort(key=lambda p: (p["price_from_kzt"], p["id"]))
    if not eligible:
        return {"status": "NO_MATCH", "cards": [], "exclusions": excluded, "exclusions_overlap": True, "category_count": len(group)}
    cards = []
    for p in eligible[:3]:
        cards.append({"id": p["id"], "anon_name": p["anon_name"], "category": req["category"], "city": p["city"], "price_from_kzt": p["price_from_kzt"], "price_label": f"от {format(p['price_from_kzt'], ',.0f').replace(',', ' ')} ₸", "explanation": build_explanation(p, req), "synthetic": p["synthetic"], "city_imputed": p["city_imputed"], "price_imputed": p["price_imputed"], "profile_status": "Синтетический профиль из датасета организаторов" if p["synthetic"] else "Анонимизированный профиль", "city_is_estimated": p["city_imputed"], "price_is_estimated": p["price_imputed"]})
    return {"status": "MATCHED", "cards": cards, "exclusions": excluded, "exclusions_overlap": True, "category_count": len(group), "eligible_count": len(eligible), "fewer_reason": "В городе всего профилей этой категории: " + str(len(group)) if len(cards) < 3 and len(group) <= 2 else "Подходящих профилей по строгим фильтрам: " + str(len(eligible)) if len(cards) < 3 else None}
