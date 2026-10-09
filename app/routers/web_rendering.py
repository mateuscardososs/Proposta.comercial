from __future__ import annotations

from fastapi import Request

from app.utils.currency import format_brl
from app.utils.dates import format_date_br


def render_template(request: Request, template_name: str, context: dict, *, status_code: int = 200) -> object:
    templates = request.app.state.templates
    base_context = {
        "request": request,
        "format_brl": format_brl,
        "format_date_br": format_date_br,
    }
    base_context.update(context)
    return templates.TemplateResponse(template_name, base_context, status_code=status_code)
