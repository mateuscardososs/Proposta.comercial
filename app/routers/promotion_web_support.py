from __future__ import annotations

from fastapi import HTTPException

from app.services.promotion_campaign_service import verify_promotion_form_token


def _require_form_token(scope: str, form) -> None:
    token = str(form.get("form_token", ""))
    if not verify_promotion_form_token(scope, token):
        raise HTTPException(status_code=403, detail="Formulário expirado ou inválido. Atualize a página e tente novamente.")
