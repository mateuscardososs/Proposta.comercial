from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db import get_db
from app.models import Client, Proposal, User
from app.schemas import ProposalCreate, ProposalItemCreate, ScheduleItemCreate, TaskCreate, UserCreate
from app.services import board_service, proposal_service, suggestion_service
from app.routers.users import hash_password
from app.utils.currency import format_brl
from app.utils.dates import format_date_br
from app.utils.formatters import decimal_from_str

router = APIRouter(tags=["pages"])
settings = get_settings()


def render_template(request: Request, template_name: str, context: dict) -> object:
    templates = request.app.state.templates
    base_context = {
        "request": request,
        "format_brl": format_brl,
        "format_date_br": format_date_br,
    }
    base_context.update(context)
    return templates.TemplateResponse(template_name, base_context)


def _default_form_data() -> dict[str, object]:
    return {
        "client_id": "",
        "user_id": "",
        "atencao": "",
        "ref_cliente": "",
        "objeto_tipo": "manutencao_calibracao",
        "objeto_texto": "",
        "canal": "",
        "contato_nome": "",
        "contato_datahora": "",
        "equipamento_nome": "",
        "equipamento_texto": "",
        "local_servico": "",
        "km_ida": "0",
        "km_volta": "0",
        "km_valor": str(settings.default_km_value),
        "alim_tecnicos": "1",
        "alim_refeicoes": "0",
        "alim_valor": "0",
        "condicao_pagamento_dias": "0",
        "imposto_percentual": "0",
        "itens": [{"descricao": "", "unidade": "UN", "qtd": "1", "valor_unit": "0"}],
        "schedule_items": [{"dia_label": "", "descricao": "", "horas_servico": ""}],
    }


def _proposal_to_payload(source: Proposal, user_id: int | None = None) -> ProposalCreate:
    return ProposalCreate(
        client_id=source.client_id,
        user_id=user_id or source.user_id,
        atencao=source.atencao,
        ref_cliente=source.ref_cliente,
        objeto_tipo=source.objeto_tipo,
        objeto_texto=source.objeto_texto,
        canal=source.canal,
        contato_nome=source.contato_nome,
        contato_datahora=source.contato_datahora,
        equipamento_nome=source.equipamento_nome,
        equipamento_texto=source.equipamento_texto,
        local_servico=source.local_servico,
        km_ida=source.km_ida,
        km_volta=source.km_volta,
        km_valor=source.km_valor,
        alim_tecnicos=source.alim_tecnicos,
        alim_refeicoes=source.alim_refeicoes,
        alim_valor=source.alim_valor,
        condicao_pagamento_dias=source.condicao_pagamento_dias,
        imposto_percentual=source.imposto_percentual,
        itens=[
            ProposalItemCreate(
                descricao=item.descricao,
                unidade=item.unidade,
                qtd=item.qtd,
                valor_unit=item.valor_unit,
            )
            for item in source.items
        ],
        schedule_items=[
            ScheduleItemCreate(
                dia_label=item.dia_label,
                descricao=item.descricao,
                horas_servico=item.horas_servico,
            )
            for item in source.schedule_items
        ],
    )


def _prefill_from_last(last: Proposal, fallback: dict[str, object]) -> dict[str, object]:
    prefill = dict(fallback)
    prefill.update(
        {
            "client_id": str(last.client_id),
            "user_id": str(last.user_id),
            "atencao": last.atencao,
            "ref_cliente": last.ref_cliente,
            "objeto_tipo": last.objeto_tipo,
            "objeto_texto": last.objeto_texto,
            "canal": last.canal,
            "contato_nome": last.contato_nome,
            "contato_datahora": last.contato_datahora,
            "equipamento_nome": last.equipamento_nome,
            "equipamento_texto": last.equipamento_texto,
            "local_servico": last.local_servico,
            "km_ida": str(last.km_ida),
            "km_volta": str(last.km_volta),
            "km_valor": str(last.km_valor),
            "alim_tecnicos": str(last.alim_tecnicos),
            "alim_refeicoes": str(last.alim_refeicoes),
            "alim_valor": str(last.alim_valor),
            "condicao_pagamento_dias": str(last.condicao_pagamento_dias),
            "imposto_percentual": str(last.imposto_percentual),
            "itens": [
                {
                    "descricao": item.descricao,
                    "unidade": item.unidade,
                    "qtd": str(item.qtd),
                    "valor_unit": str(item.valor_unit),
                }
                for item in last.items
            ]
            or fallback["itens"],
            "schedule_items": [
                {
                    "dia_label": item.dia_label,
                    "descricao": item.descricao,
                    "horas_servico": item.horas_servico,
                }
                for item in last.schedule_items
            ]
            or fallback["schedule_items"],
        }
    )
    return prefill


def _build_new_proposal_redirect_url(
    request: Request,
    warning: str,
    revision_from: int | None = None,
) -> str:
    base = str(request.url_for("web_proposal_new"))
    params = [f"warning={quote_plus(warning)}"]
    if revision_from:
        params.append(f"revision_from={revision_from}")
    return f"{base}?{'&'.join(params)}"


def _required_positive_int(value: object, label: str) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} invalido.") from exc
    if parsed <= 0:
        raise ValueError(f"{label} invalido.")
    return parsed


@router.get("/", name="web_index")
def index(request: Request, db: Session = Depends(get_db)) -> object:
    total_clients = db.query(Client).count()
    total_users = db.query(User).count()
    total_proposals = db.query(Proposal).count()
    last_proposals = (
        db.query(Proposal)
        .options(joinedload(Proposal.client), joinedload(Proposal.user))
        .order_by(Proposal.id.desc())
        .limit(5)
        .all()
    )
    return render_template(
        request,
        "index.html",
        {
            "total_clients": total_clients,
            "total_users": total_users,
            "total_proposals": total_proposals,
            "last_proposals": last_proposals,
        },
    )


@router.get("/web/clients", name="web_clients")
def clients_page(request: Request, db: Session = Depends(get_db)) -> object:
    clients = db.query(Client).order_by(Client.razao_social.asc()).all()
    return render_template(request, "clients.html", {"clients": clients})


@router.get("/web/clients/new", name="web_client_new")
def client_new_page(request: Request) -> object:
    return render_template(request, "client_form.html", {"client": None, "action_url": "/web/clients/new"})


@router.post("/web/clients/new")
async def client_new_submit(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    form = await request.form()
    client = Client(
        razao_social=str(form.get("razao_social", "")).strip(),
        cnpj=str(form.get("cnpj", "")).strip(),
        endereco_linha1=str(form.get("endereco_linha1", "")).strip(),
        endereco_linha2=str(form.get("endereco_linha2", "")).strip(),
        cep=str(form.get("cep", "")).strip(),
        cidade_uf=str(form.get("cidade_uf", "")).strip(),
        pais=str(form.get("pais", "Brasil")).strip() or "Brasil",
        caixa_postal=str(form.get("caixa_postal", "")).strip(),
        telefone=str(form.get("telefone", "")).strip(),
        site=str(form.get("site", "")).strip(),
        contato_padrao=str(form.get("contato_padrao", "")).strip(),
    )
    if not client.razao_social:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Razao social is required")
    db.add(client)
    db.commit()
    return RedirectResponse(url=request.url_for("web_clients"), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/web/clients/{client_id}", name="web_client_detail")
def client_detail_page(client_id: int, request: Request, db: Session = Depends(get_db)) -> object:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    proposals = (
        db.query(Proposal)
        .filter(Proposal.client_id == client_id)
        .order_by(Proposal.data_geracao.desc(), Proposal.id.desc())
        .limit(10)
        .all()
    )
    return render_template(request, "client_form.html", {"client": client, "action_url": f"/web/clients/{client_id}/edit", "proposals": proposals})


@router.post("/web/clients/{client_id}/edit")
async def client_edit_submit(client_id: int, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    form = await request.form()
    fields = [
        "razao_social",
        "cnpj",
        "endereco_linha1",
        "endereco_linha2",
        "cep",
        "cidade_uf",
        "pais",
        "caixa_postal",
        "telefone",
        "site",
        "contato_padrao",
    ]
    for field in fields:
        setattr(client, field, str(form.get(field, "")).strip())
    if not client.razao_social:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Razao social is required")
    db.add(client)
    db.commit()
    return RedirectResponse(url=request.url_for("web_clients"), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/web/users", name="web_users")
def users_page(request: Request, db: Session = Depends(get_db)) -> object:
    users = db.query(User).order_by(User.nome.asc()).all()
    return render_template(request, "users.html", {"users": users})


@router.get("/web/users/new", name="web_user_new")
def user_new_page(request: Request) -> object:
    return render_template(request, "user_form.html", {"error": ""})


@router.post("/web/users/new")
async def user_new_submit(request: Request, db: Session = Depends(get_db)) -> object:
    form = await request.form()
    payload = UserCreate(
        nome=str(form.get("nome", "")).strip(),
        cargo=str(form.get("cargo", "")).strip(),
        email=str(form.get("email", "")).strip(),
        senha=str(form.get("senha", "123456")).strip() or "123456",
        ativo=True if form.get("ativo") == "on" else False,
    )
    if db.query(User).filter(User.email == payload.email).first():
        return render_template(request, "user_form.html", {"error": "Email ja existe."})
    user = User(
        nome=payload.nome,
        cargo=payload.cargo,
        email=payload.email,
        senha_hash=hash_password(payload.senha),
        ativo=payload.ativo,
    )
    db.add(user)
    db.commit()
    return RedirectResponse(url=request.url_for("web_users"), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/web/proposals", name="web_proposals")
def proposals_page(request: Request, db: Session = Depends(get_db)) -> object:
    proposals = (
        db.query(Proposal)
        .options(joinedload(Proposal.client), joinedload(Proposal.user))
        .order_by(Proposal.data_geracao.desc(), Proposal.id.desc())
        .all()
    )
    return render_template(request, "proposals.html", {"proposals": proposals})


@router.get("/import-proposals", name="web_import_proposals")
def import_proposals_page(request: Request, db: Session = Depends(get_db)) -> object:
    users = db.query(User).filter(User.ativo.is_(True)).order_by(User.nome.asc()).all()
    default_user_id = users[0].id if users else None
    return render_template(
        request,
        "import_proposals.html",
        {
            "users": users,
            "default_user_id": default_user_id,
        },
    )


@router.get("/web/proposals/new", name="web_proposal_new")
def proposal_new_page(
    request: Request,
    client_id: int | None = None,
    load_last: int = 0,
    revision_from: int | None = None,
    warning: str | None = None,
    db: Session = Depends(get_db),
) -> object:
    clients = db.query(Client).order_by(Client.razao_social.asc()).all()
    users = db.query(User).filter(User.ativo.is_(True)).order_by(User.nome.asc()).all()

    form_data = _default_form_data()
    create_mode = "new"
    base_proposal_id = ""
    revision_source = None

    if users:
        form_data["user_id"] = str(users[0].id)
    if client_id:
        form_data["client_id"] = str(client_id)

    if revision_from:
        source = proposal_service.get_proposal_with_details(db, proposal_id=revision_from)
        if source:
            form_data = _prefill_from_last(source, form_data)
            create_mode = "revision"
            base_proposal_id = str(source.id)
            revision_source = source
        else:
            warning = "Proposta base para revisao nao encontrada."
    elif client_id and load_last == 1:
        last = suggestion_service.get_last_proposal_for_client(db, client_id=client_id)
        if last:
            form_data = _prefill_from_last(last, form_data)
        else:
            warning = "Nenhuma proposta anterior encontrada para este cliente."

    return render_template(
        request,
        "proposal_form.html",
        {
            "clients": clients,
            "users": users,
            "form_data": form_data,
            "warning": warning or "",
            "create_mode": create_mode,
            "base_proposal_id": base_proposal_id,
            "revision_source": revision_source,
        },
    )


@router.post("/web/proposals/new")
async def proposal_new_submit(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    form = await request.form()
    mode = str(form.get("mode", "new")).strip().lower()
    if mode not in {"new", "revision"}:
        mode = "new"
    revision_from_raw = str(form.get("base_proposal_id", "")).strip()
    base_proposal_id: int | None = None
    if mode == "revision":
        try:
            base_proposal_id = _required_positive_int(revision_from_raw, "Proposta base")
        except ValueError as exc:
            return RedirectResponse(
                url=_build_new_proposal_redirect_url(
                    request,
                    warning=str(exc),
                    revision_from=int(revision_from_raw) if revision_from_raw.isdigit() else None,
                ),
                status_code=status.HTTP_303_SEE_OTHER,
            )

    try:
        client_id = _required_positive_int(form.get("client_id"), "Cliente")
        user_id = _required_positive_int(form.get("user_id"), "Responsavel")
    except ValueError as exc:
        return RedirectResponse(
            url=_build_new_proposal_redirect_url(request, warning=str(exc), revision_from=base_proposal_id),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    items: list[ProposalItemCreate] = []
    schedule_items: list[ScheduleItemCreate] = []
    try:
        descricoes = form.getlist("item_descricao")
        unidades = form.getlist("item_unidade")
        qtds = form.getlist("item_qtd")
        valores = form.getlist("item_valor_unit")
        schedule_dias = form.getlist("schedule_dia_label")
        schedule_descricoes = form.getlist("schedule_descricao")
        schedule_horas = form.getlist("schedule_horas_servico")

        for index, descricao in enumerate(descricoes):
            if not str(descricao).strip():
                continue
            unidade = str(unidades[index]).strip() if index < len(unidades) else "UN"
            qtd_value = str(qtds[index]) if index < len(qtds) else "0"
            valor_value = str(valores[index]) if index < len(valores) else "0"
            items.append(
                ProposalItemCreate(
                    descricao=str(descricao).strip(),
                    unidade=unidade or "UN",
                    qtd=decimal_from_str(qtd_value, default="0.00"),
                    valor_unit=decimal_from_str(valor_value, default="0.00"),
                )
            )

        for index, dia_label in enumerate(schedule_dias):
            descricao = str(schedule_descricoes[index]).strip() if index < len(schedule_descricoes) else ""
            horas = str(schedule_horas[index]).strip() if index < len(schedule_horas) else ""
            dia = str(dia_label).strip()
            if not dia and not descricao and not horas:
                continue
            schedule_items.append(
                ScheduleItemCreate(
                    dia_label=dia,
                    descricao=descricao,
                    horas_servico=horas,
                )
            )

        payload = ProposalCreate(
            client_id=client_id,
            user_id=user_id,
            atencao=str(form.get("atencao", "")).strip(),
            ref_cliente=str(form.get("ref_cliente", "")).strip(),
            objeto_tipo=str(form.get("objeto_tipo", "manutencao_calibracao")).strip(),
            objeto_texto=str(form.get("objeto_texto", "")).strip(),
            canal=str(form.get("canal", "")).strip(),
            contato_nome=str(form.get("contato_nome", "")).strip(),
            contato_datahora=str(form.get("contato_datahora", "")).strip(),
            equipamento_nome=str(form.get("equipamento_nome", "")).strip(),
            equipamento_texto=str(form.get("equipamento_texto", "")).strip(),
            local_servico=str(form.get("local_servico", "")).strip(),
            km_ida=decimal_from_str(str(form.get("km_ida", "0"))),
            km_volta=decimal_from_str(str(form.get("km_volta", "0"))),
            km_valor=decimal_from_str(str(form.get("km_valor", "2.95"))),
            alim_tecnicos=int(str(form.get("alim_tecnicos", "1")) or "1"),
            alim_refeicoes=int(str(form.get("alim_refeicoes", "0")) or "0"),
            alim_valor=decimal_from_str(str(form.get("alim_valor", "0"))),
            condicao_pagamento_dias=int(str(form.get("condicao_pagamento_dias", "0")) or "0"),
            imposto_percentual=decimal_from_str(str(form.get("imposto_percentual", "0"))),
            itens=items,
            schedule_items=schedule_items,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=_build_new_proposal_redirect_url(request, warning=str(exc), revision_from=base_proposal_id),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        created = proposal_service.create_proposal(
            db,
            payload=payload,
            mode=mode,
            base_proposal_id=base_proposal_id,
        )
        _, pdf_error = proposal_service.generate_documents(db, proposal_id=created.id, settings=settings)

        if form.get("create_kanban_card") == "1":
            task_payload = TaskCreate(
                titulo=f"Proposta #{created.numero}/{created.revisao} - {created.client.razao_social if created.client else 'Cliente'}",
                descricao=f"Gerada automaticamente.\nObjeto: {created.objeto_texto}",
                status="aguardando_cliente",
                client_id=created.client_id,
                proposal_id=created.id,
                user_id=created.user_id,
                prazo=None,
            )
            board_service.create_task(db, task_payload)
    except (ValueError, FileNotFoundError) as exc:
        return RedirectResponse(
            url=_build_new_proposal_redirect_url(request, warning=str(exc), revision_from=base_proposal_id),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    detail_url = str(request.url_for("web_proposal_detail", proposal_id=created.id))
    if pdf_error:
        detail_url = f"{detail_url}?warning={quote_plus(pdf_error)}"
    return RedirectResponse(url=detail_url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/web/proposals/{proposal_id}", name="web_proposal_detail")
def proposal_detail_page(
    proposal_id: int,
    request: Request,
    warning: str | None = None,
    db: Session = Depends(get_db),
) -> object:
    proposal = proposal_service.get_proposal_with_details(db, proposal_id=proposal_id)
    if not proposal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return render_template(
        request,
        "proposal_detail.html",
        {
            "proposal": proposal,
            "docx_url": f"/output/{proposal.docx_path}" if proposal.docx_path else "",
            "pdf_url": f"/output/{proposal.pdf_path}" if proposal.pdf_path else "",
            "warning": warning or "",
        },
    )


@router.post("/web/proposals/{proposal_id}/duplicate", name="web_proposal_duplicate")
def proposal_duplicate_submit(proposal_id: int, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    source = proposal_service.get_proposal_with_details(db, proposal_id)
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    payload = _proposal_to_payload(source)
    created = proposal_service.create_proposal(db, payload=payload, mode="new")
    _, pdf_error = proposal_service.generate_documents(db, proposal_id=created.id, settings=settings)
    detail_url = str(request.url_for("web_proposal_detail", proposal_id=created.id))
    if pdf_error:
        detail_url = f"{detail_url}?warning={quote_plus(pdf_error)}"
    return RedirectResponse(url=detail_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/web/proposals/{proposal_id}/revision", name="web_proposal_revision")
def proposal_revision_submit(proposal_id: int, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    source = proposal_service.get_proposal_with_details(db, proposal_id)
    if not source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    target_url = f"{request.url_for('web_proposal_new')}?revision_from={source.id}"
    return RedirectResponse(url=target_url, status_code=status.HTTP_303_SEE_OTHER)
