"""Presentation facts and query deltas; the catalog remains the only matcher."""

from catalog import recommend


def profile_detail(card):
    """Reuse the already verified AI selection or deterministic fallback excerpt."""
    return card.get("selected_evidence") or (card["evidence"][0]["text"] if card["evidence"] else "")


def before_selection(card):
    notes = []
    if card["price_imputed"]:
        notes.append("Окончательную цену")
    if card["city_imputed"]:
        notes.append("Город работы")
    notes.append("Фактическую доступность на дату перед бронированием")
    if card["synthetic"]:
        notes.append("Демонстрационный профиль, не реальное предложение для заказа.")
    return notes


def comparison_rows(cards, request, profiles):
    if len(cards) < 2:
        return []
    rows = []
    by_id = {profile["id"]: profile for profile in profiles}
    for card in cards:
        row = {
            "Имя": card["anon_name"],
            "Цена «от»": card["price_label"],
            "Город": card["city"],
            "Категория": card["category"],
            "Особенность профиля": profile_detail(card) or "Не указана",
        }
        if request.get("language"):
            row["Язык"] = request["language"]
        if request.get("hours") is not None:
            maximum = by_id[card["id"]]["max_hours"]
            row["Длительность"] = (f"до {maximum:g} ч" if maximum is not None
                                  else "Ограничение не указано")
        row["Что нужно уточнить"] = "; ".join(before_selection(card))
        rows.append(row)
    return rows


def eligible_profiles(rows, request):
    """Ask the unchanged matcher about each profile, including those beyond top three."""
    return {p["id"]: p for p in rows if recommend([p], request)["status"] == "MATCHED"}


def query_delta(rows, previous_request, previous_result, request, result):
    if previous_request is None or previous_result is None:
        return None
    keys = ("city", "date", "event_format", "category", "budget_kzt", "language", "hours")
    changed = [key for key in keys if previous_request.get(key) != request.get(key)]
    if not changed:
        return None
    if len(changed) > 1:
        return {"kind": "multiple", "lines": ["Изменилось несколько параметров. Результат рассчитан заново по текущим условиям."]}
    if changed[0] not in ("date", "budget_kzt"):
        return {"kind": "other", "lines": ["Изменился параметр запроса. Результат рассчитан заново по текущим условиям."]}
    if "NO_CATEGORY_IN_CITY" in (previous_result["status"], result["status"]):
        return {"kind": "no_category", "lines": ["Для этой категории в выбранном городе нет профилей; изменение даты или бюджета не объясняет состав выдачи."]}

    old = eligible_profiles(rows, previous_request)
    new = eligible_profiles(rows, request)
    by_id = {p["id"]: p for p in rows}
    appeared = sorted(new.keys() - old.keys(), key=lambda pid: (by_id[pid]["price_from_kzt"], pid))
    disappeared = sorted(old.keys() - new.keys(), key=lambda pid: (by_id[pid]["price_from_kzt"], pid))
    label = lambda ids: ", ".join(by_id[pid]["anon_name"] for pid in ids) if ids else "нет"
    lines = [f"Подходящих профилей: было {len(old)}, стало {len(new)}.",
             f"Появились: {label(appeared)}. Исчезли: {label(disappeared)}."]
    if previous_result["status"] == "MATCHED" and result["status"] == "NO_MATCH":
        lines.append("Ранее были подходящие варианты, теперь условия исключают всех.")
    elif previous_result["status"] == "NO_MATCH" and result["status"] == "MATCHED":
        lines.append("Теперь появились подходящие варианты.")

    if changed[0] == "date":
        for pid in appeared:
            p = by_id[pid]
            if previous_request["date"] in p["busy_dates"] and request["date"] not in p["busy_dates"]:
                lines.append(f"{p['anon_name']} появился: на прежнюю дату он отмечен занятым, на новую — нет.")
        for pid in disappeared:
            p = by_id[pid]
            if request["date"] in p["busy_dates"] and previous_request["date"] not in p["busy_dates"]:
                lines.append(f"{p['anon_name']} исчез: на новую дату он отмечен занятым.")
    else:
        old_budget, new_budget = previous_request["budget_kzt"], request["budget_kzt"]
        for pid in appeared:
            p = by_id[pid]
            price = p["price_from_kzt"]
            if old_budget < price <= new_budget:
                lines.append(f"{p['anon_name']} появился: начальная цена «от» {price:,.0f} ₸ превышала прежний лимит и укладывается в новый.".replace(",", " "))
        for pid in disappeared:
            p = by_id[pid]
            price = p["price_from_kzt"]
            if new_budget < price <= old_budget:
                lines.append(f"{p['anon_name']} больше не проходит бюджет: начальная цена «от» {price:,.0f} ₸ выше нового лимита.".replace(",", " "))
    return {"kind": changed[0], "before_count": len(old), "after_count": len(new),
            "appeared_ids": appeared, "disappeared_ids": disappeared, "lines": lines}
