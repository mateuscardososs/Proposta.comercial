from datetime import date

from app.assistant.dates import resolve_date_expression


def test_this_week_resolves_to_sunday():
    assert resolve_date_expression("esta semana", today=date(2026, 9, 30)) == date(2026, 10, 4)


def test_this_weekday_can_resolve_to_today():
    assert resolve_date_expression("nesta quarta", today=date(2026, 9, 30)) == date(2026, 9, 30)


def test_next_weekday_never_resolves_to_today():
    assert resolve_date_expression("proxima quarta", today=date(2026, 9, 30)) == date(2026, 10, 7)
