from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.models import Client, Lancamento, Proposal
from app.schemas import (
    LancamentoCreate,
    LancamentoMove,
    LancamentoRead,
    LancamentoUpdate,
)
from app.services import lancamento_service
from app.utils.currency import format_brl
from app.utils.dates import format_date_br
from app.utils.formatters import decimal_from_str


router = APIRouter(tags=["financeiro"])

BOARD_CONFIG = {
    "receber": {
        "board_url": "/web/contas-a-receber",
        "new_url": "/web/contas-a-receber/new",
        "edit_prefix": "/web/contas-a-receber",
        "page_title": "Contas a Receber",
        "page_subtitle": "Acompanhe recebimentos pendentes e pagos.",
        "pending_label": "A Receber",
        "new_label": "Novo Recebimento",
    },
    "pagar": {
        "board_url": "/web/contas-a-pagar",
        "new_url": "/web/contas-a-pagar/new",
        "edit_prefix": "/web/contas-a-pagar",
        "page_title": "Contas a Pagar",
        "page_subtitle": "Acompanhe pagamentos pendentes e realizados.",
        "pending_label": "A Pagar",
        "new_label": "Novo Pagamento",
    },
}


def _render_template(request: Request, template_name: str, context: dict[str, object]) -> object:
    base_context = {
        "request": request,
        "format_brl": format_brl,
        "format_date_br": format_date_br,
    }
    base_context.update(context)
    return request.app.state.templates.TemplateResponse(
        request=request,
        name=template_name,
        context=base_context,
    )


def _optional_int(value: object) -> int | None:
    text = str(value or "").strip()
    return int(text) if text else None


def _parse_payload(form: object, tipo: str, *, update: bool) -> LancamentoCreate | LancamentoUpdate:
    values = {
        "descricao": str(form.get("descricao", "")).strip(),
        "client_id": _optional_int(form.get("client_id")),
        "proposal_id": _optional_int(form.get("proposal_id")),
        "fornecedor": str(form.get("fornecedor", "")).strip() or None,
        "valor": decimal_from_str(str(form.get("valor", ""))),
        "data_emissao": date.fromisoformat(str(form.get("data_emissao", ""))),
        "data_vencimento": date.fromisoformat(str(form.get("data_vencimento", ""))),
        "status": str(form.get("status", "pendente")),
        "data_pagamento": (
            date.fromisoformat(str(form.get("data_pagamento")))
            if form.get("data_pagamento")
            else None
        ),
    }
    if update:
        return LancamentoUpdate(**values)
    return LancamentoCreate(tipo=tipo, **values)


def _entry_form_data(entry: Lancamento | None) -> dict[str, object]:
    if entry is None:
        return {
            "descricao": "",
            "client_id": "",
            "proposal_id": "",
            "fornecedor": "",
            "valor": "",
            "data_emissao": date.today().isoformat(),
            "data_vencimento": "",
            "status": "pendente",
            "data_pagamento": "",
        }
    return {
        "descricao": entry.descricao,
        "client_id": str(entry.client_id or ""),
        "proposal_id": str(entry.proposal_id or ""),
        "fornecedor": entry.fornecedor or "",
        "valor": f"{Decimal(entry.valor):.2f}",
        "data_emissao": entry.data_emissao.isoformat(),
        "data_vencimento": entry.data_vencimento.isoformat(),
        "status": entry.status,
        "data_pagamento": entry.data_pagamento.isoformat() if entry.data_pagamento else "",
    }


def _form_context(
    db: Session,
    tipo: str,
    entry: Lancamento | None,
    *,
    form_data: dict[str, object] | None = None,
    error: str = "",
) -> dict[str, object]:
    clients = db.query(Client).order_by(Client.razao_social.asc()).all()
    proposals = (
        db.query(Proposal)
        .options(joinedload(Proposal.client))
        .order_by(Proposal.numero.desc(), Proposal.id.desc())
        .all()
    )
    return {
        "config": BOARD_CONFIG[tipo],
        "tipo": tipo,
        "entry": entry,
        "form_data": form_data or _entry_form_data(entry),
        "clients": clients,
        "proposals": proposals,
        "action_url": (
            f"{BOARD_CONFIG[tipo]['edit_prefix']}/{entry.id}/edit"
            if entry
            else BOARD_CONFIG[tipo]["new_url"]
        ),
        "error": error,
    }


def _board(request: Request, tipo: str, db: Session) -> object:
    entries = lancamento_service.list_lancamentos(db, tipo)
    return _render_template(
        request,
        "lancamentos_board.html",
        {
            "config": BOARD_CONFIG[tipo],
            "tipo": tipo,
            "pendentes": [entry for entry in entries if entry.status == "pendente"],
            "pagos": [entry for entry in entries if entry.status == "pago"],
            "today": date.today(),
            "is_atrasado": lancamento_service.is_atrasado,
        },
    )


def _form_page(
    request: Request,
    tipo: str,
    db: Session,
    lancamento_id: int | None = None,
) -> object:
    entry = (
        lancamento_service.get_lancamento(db, lancamento_id, tipo=tipo)
        if lancamento_id is not None
        else None
    )
    return _render_template(
        request,
        "lancamento_form.html",
        _form_context(db, tipo, entry),
    )


async def _submit(
    request: Request,
    tipo: str,
    db: Session,
    lancamento_id: int | None = None,
) -> object:
    entry = (
        lancamento_service.get_lancamento(db, lancamento_id, tipo=tipo)
        if lancamento_id is not None
        else None
    )
    form = await request.form()
    form_data = {key: str(value) for key, value in form.items()}
    try:
        payload = _parse_payload(form, tipo, update=entry is not None)
        if entry is None:
            lancamento_service.create_lancamento(db, payload)
        else:
            lancamento_service.update_lancamento(db, entry.id, tipo, payload)
    except (ValidationError, ValueError):
        response = _render_template(
            request,
            "lancamento_form.html",
            _form_context(
                db,
                tipo,
                entry,
                form_data=form_data,
                error="Verifique os campos informados.",
            ),
        )
        response.status_code = status.HTTP_400_BAD_REQUEST
        return response
    return RedirectResponse(
        url=BOARD_CONFIG[tipo]["board_url"],
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/web/contas-a-receber", name="web_contas_receber")
def web_contas_receber(request: Request, db: Session = Depends(get_db)) -> object:
    return _board(request, "receber", db)


@router.get("/web/contas-a-receber/new", name="web_contas_receber_new")
def web_contas_receber_new(request: Request, db: Session = Depends(get_db)) -> object:
    return _form_page(request, "receber", db)


@router.post("/web/contas-a-receber/new")
async def web_contas_receber_create(request: Request, db: Session = Depends(get_db)) -> object:
    return await _submit(request, "receber", db)


@router.get("/web/contas-a-receber/{lancamento_id}/edit", name="web_contas_receber_edit")
def web_contas_receber_edit(
    lancamento_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> object:
    return _form_page(request, "receber", db, lancamento_id)


@router.post("/web/contas-a-receber/{lancamento_id}/edit")
async def web_contas_receber_update(
    lancamento_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> object:
    return await _submit(request, "receber", db, lancamento_id)


@router.get("/web/contas-a-pagar", name="web_contas_pagar")
def web_contas_pagar(request: Request, db: Session = Depends(get_db)) -> object:
    return _board(request, "pagar", db)


@router.get("/web/contas-a-pagar/new", name="web_contas_pagar_new")
def web_contas_pagar_new(request: Request, db: Session = Depends(get_db)) -> object:
    return _form_page(request, "pagar", db)


@router.post("/web/contas-a-pagar/new")
async def web_contas_pagar_create(request: Request, db: Session = Depends(get_db)) -> object:
    return await _submit(request, "pagar", db)


@router.get("/web/contas-a-pagar/{lancamento_id}/edit", name="web_contas_pagar_edit")
def web_contas_pagar_edit(
    lancamento_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> object:
    return _form_page(request, "pagar", db, lancamento_id)


@router.post("/web/contas-a-pagar/{lancamento_id}/edit")
async def web_contas_pagar_update(
    lancamento_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> object:
    return await _submit(request, "pagar", db, lancamento_id)


@router.post("/api/lancamentos/{lancamento_id}/move", response_model=LancamentoRead)
def api_move_lancamento(
    lancamento_id: int,
    payload: LancamentoMove,
    db: Session = Depends(get_db),
) -> object:
    return lancamento_service.move_lancamento(db, lancamento_id, payload)
