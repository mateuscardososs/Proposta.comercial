from __future__ import annotations

from datetime import date, datetime


def today_date() -> date:
    return date.today()


def format_date_br(value: date | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%d/%m/%Y")


def format_file_date(value: date | datetime | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime("%d.%m.%Y")
