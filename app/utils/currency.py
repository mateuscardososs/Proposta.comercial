from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


TWOPLACES = Decimal("0.01")


def to_decimal(value: Decimal | int | float | str | None, default: str = "0.00") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if text == "":
        return Decimal(default)
    text = text.replace(".", "").replace(",", ".") if "," in text else text
    return Decimal(text)


def quantize_2(value: Decimal | int | float | str | None) -> Decimal:
    return to_decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def format_decimal_br(value: Decimal | int | float | str | None) -> str:
    number = quantize_2(value)
    sign = "-" if number < 0 else ""
    formatted = f"{abs(number):,.2f}"
    formatted = formatted.replace(",", "#").replace(".", ",").replace("#", ".")
    return f"{sign}{formatted}"


def format_brl(value: Decimal | int | float | str | None) -> str:
    return f"R$ {format_decimal_br(value)}"
