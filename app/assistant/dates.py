from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta


WEEKDAYS = {
    "segunda": 0,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "domingo": 6,
}


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def resolve_date_expression(value: str | None, *, today: date) -> date | None:
    if value is None or not value.strip():
        return None
    raw = value.strip()
    normalized = normalize_text(raw)
    if normalized == "hoje":
        return today
    if normalized in {"amanha", "no dia seguinte"}:
        return today + timedelta(days=1)
    if normalized == "depois de amanha":
        return today + timedelta(days=2)
    if normalized in {"esta semana", "nesta semana", "ate o fim da semana"}:
        return today + timedelta(days=6 - today.weekday())

    days_match = re.fullmatch(r"(?:em|daqui a)\s+(\d{1,3})\s+dias?", normalized)
    if days_match:
        return today + timedelta(days=int(days_match.group(1)))

    weekday_match = re.fullmatch(r"(?:(proxima|nesta)\s+)?(segunda|terca|quarta|quinta|sexta|sabado|domingo)(?:-feira)?", normalized)
    if weekday_match:
        qualifier, weekday_name = weekday_match.groups()
        delta = (WEEKDAYS[weekday_name] - today.weekday()) % 7
        if qualifier == "proxima" and delta == 0:
            delta = 7
        return today + timedelta(days=delta)

    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return date.fromisoformat(raw) if date_format == "%Y-%m-%d" else datetime.strptime(raw, date_format).date()
        except ValueError:
            continue
    raise ValueError(f"Nao consegui interpretar a data '{raw}'.")
