from __future__ import annotations

from datetime import datetime
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.assistant.email import classification as _email_classification
from app.assistant.email.contracts import EmailMessageRecord
from app.assistant.email.extraction import extract_operational_fields
from app.config import get_settings
from app.db import get_db
from app.models import (
    Client,
    ClientCampaignContact,
    EmailActionDraft,
    EmailSyncState,
    InboxEmail,
    Proposal,
    ServiceCall,
    User,
)
from app.routers import proposal_form
from app.routers.users import hash_password
from app.schemas import (
    TaskCreate,
    UserCreate,
)
from app.services import (
    board_service,
    dashboard_service,
    proposal_service,
    suggestion_service,
)
from app.services.daily_schedule_service import build_daily_schedule
from app.services.email_review_service import ensure_email_action_draft
from app.services.message_workbench_service import get_message_workbench
from app.services import message_workbench_service as _message_workbench_service
from app.services.promotion_campaign_service import promotion_form_token
from app.services.today_service import get_today_agenda
from app.utils.currency import format_brl
from app.utils.dates import format_date_br

router = APIRouter(tags=["pages"])
settings = get_settings()

# Preserve historical module-level imports without duplicating implementation.
ProposalCreate = proposal_form.ProposalCreate
ProposalItemCreate = proposal_form.ProposalItemCreate
ScheduleItemCreate = proposal_form.ScheduleItemCreate
OPERATIONAL_CATEGORIES = _email_classification.OPERATIONAL_CATEGORIES
EmailTaskLink = _message_workbench_service.EmailTaskLink
and_ = _message_workbench_service.and_
not_ = _message_workbench_service.not_
or_ = _message_workbench_service.or_
decimal_from_str = proposal_form.decimal_from_str


def render_template(request: Request, template_name: str, context: dict, *, status_code: int = 200) -> object:
    templates = request.app.state.templates
    base_context = {
        "request": request,
        "format_brl": format_brl,
        "format_date_br": format_date_br,
    }
    base_context.update(context)
    return templates.TemplateResponse(template_name, base_context, status_code=status_code)


def _default_form_data() -> dict[str, object]:
    return proposal_form.default_form_data(default_km_value=settings.default_km_value)


# Keep historical helper imports available to routes and callers.
_proposal_to_payload = proposal_service._build_clone_payload
_prefill_from_last = proposal_form.prefill_from_last


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
    today = datetime.now(ZoneInfo(settings.assistant_timezone)).date()
    summary = dashboard_service.get_dashboard_summary(db, today)
    agenda = get_today_agenda(
        db,
        today=today,
        lookahead_days=settings.today_lookahead_days,
        timezone=settings.assistant_timezone,
    )
    suggested_schedule = build_daily_schedule(
        db,
        today=today,
        now=datetime.now(ZoneInfo(settings.assistant_timezone)),
        timezone=settings.assistant_timezone,
        task_plan=agenda.task_plan,
    )
    today_sections = {
        "attention": [item for item in agenda.items if item.rank <= 1][:6],
        "agenda": [item for item in agenda.items if item.source_type == "task"],
        "services": [item for item in agenda.items if item.source_type == "service"],
        "finance": [item for item in agenda.items if item.source_type == "finance"],
    }
    return render_template(
        request,
        "index.html",
        {
            "summary": summary,
            "agenda": agenda,
            "suggested_schedule": suggested_schedule,
            "today_sections": today_sections,
            "full_width": True,
            "title": "Hoje",
        },
    )


@router.get("/web/mensagens", name="web_messages")
def messages_page(request: Request, db: Session = Depends(get_db)) -> object:
    workbench = get_message_workbench(
        db, provider=settings.email_provider, mailbox_key=settings.email_sync_mailbox_key,
    )
    state = workbench["sync_state"]
    operational_messages = workbench["operational_messages"]
    informational_messages = workbench["informational_messages"]
    review_messages = workbench["review_messages"]
    action_drafts_by_email = workbench["action_drafts_by_email"]
    message_summary = workbench["message_summary"]
    if settings.email_provider == "synthetic":
        provider_configured = True
    elif settings.email_provider == "imap_yahoo":
        provider_configured = bool(settings.email_imap_username and settings.email_imap_app_password.get_secret_value())
    else:
        provider_configured = False
    return render_template(
        request,
        "messages.html",
        {
            "title": "E-mails e mensagens",
            "message_groups": [
                {
                    "key": "operational",
                    "title": "Operacionais",
                    "panel_id": "messages-operational",
                    "messages": operational_messages,
                    "count": message_summary["operational"],
                    "empty_text": "Nenhuma mensagem operacional classificada no momento.",
                },
                {
                    "key": "informational",
                    "title": "Informativos/outros",
                    "panel_id": "messages-informational",
                    "messages": informational_messages,
                    "count": message_summary["informational"],
                    "empty_text": "Nenhum informativo ou outro item classificado.",
                },
                {
                    "key": "review",
                    "title": "Revisar",
                    "panel_id": "messages-review",
                    "messages": review_messages,
                    "count": message_summary["review"],
                    "empty_text": "Nenhum item aguardando revisão.",
                },
            ],
            "message_count_total": sum(
                message_summary[key] for key in ("operational", "informational", "review")
            ),
            "category_labels": {
                "customer_quote_request": "Orçamento solicitado por cliente",
                "vendor_quotation": "Cotação de fornecedor",
                "purchase_order": "Pedido/ordem de compra",
                "invoice_request": "Solicitação de nota fiscal",
                "invoice_received": "Nota fiscal recebida",
                "accounts_payable": "Conta a pagar",
                "accounts_receivable": "Cobrança/conta a receber",
                "payment_proof": "Comprovante de pagamento",
                "service_request": "Chamado/serviço técnico",
                "pending_reply": "Possível resposta pendente",
                "informational": "Informativo/outros",
                "other_review": "Revisar classificação",
            },
            "action_suggestions": {
                "customer_quote_request": "Preparar tarefa para avaliar o pedido de orçamento, mediante confirmação.",
                "vendor_quotation": "Conferir a cotação recebida do fornecedor; não cria tarefa automaticamente.",
                "purchase_order": "Conferir o pedido/ordem de compra e confirmar antes de criar tarefa.",
                "invoice_request": "Conferir a solicitação; emissão/envio de nota não está disponível.",
                "invoice_received": "Conferir a nota e validar se corresponde a uma conta a pagar.",
                "accounts_payable": "Revisar os dados e confirmar antes de criar lançamento a pagar.",
                "accounts_receivable": "Classificação para revisão; não cria lançamento financeiro.",
                "payment_proof": "Conferir comprovante; não baixa nem altera pagamento.",
                "service_request": "Conferir o chamado; criar tarefa somente após confirmação.",
                "pending_reply": "Verificar manualmente se é necessária uma resposta.",
            },
            "action_drafts_by_email": action_drafts_by_email,
            "message_summary": message_summary,
            "sync_state": state,
            "sync_enabled": settings.email_sync_enabled,
            "sync_interval_seconds": settings.email_sync_interval_seconds,
            "provider_configured": provider_configured,
            "full_width": True,
        },
    )


@router.post("/web/mensagens/sync-state", name="web_messages_sync_state")
async def messages_sync_state(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    form = await request.form()
    action = str(form.get("action", ""))
    if action not in {"pause", "resume"}:
        raise HTTPException(status_code=400, detail="Ação de sincronização inválida.")
    state = (
        db.query(EmailSyncState)
        .filter_by(
            provider=settings.email_provider,
            mailbox_key=settings.email_sync_mailbox_key,
        )
        .one_or_none()
    )
    if state is None:
        state = EmailSyncState(
            provider=settings.email_provider,
            mailbox_key=settings.email_sync_mailbox_key,
        )
        db.add(state)
    state.paused = action == "pause"
    db.commit()
    return RedirectResponse(url=request.url_for("web_messages"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/web/mensagens/{message_id}/review", name="web_message_review")
async def message_review(message_id: int, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    form = await request.form()
    category = str(form.get("category", ""))
    allowed = {
        "customer_quote_request",
        "vendor_quotation",
        "purchase_order",
        "invoice_request",
        "invoice_received",
        "accounts_payable",
        "accounts_receivable",
        "payment_proof",
        "service_request",
        "pending_reply",
        "informational",
        "other_review",
    }
    message = db.get(InboxEmail, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Mensagem não encontrada.")
    if category not in allowed:
        raise HTTPException(status_code=400, detail="Categoria inválida.")
    active_draft = (
        db.query(EmailActionDraft)
        .filter(
            EmailActionDraft.inbox_email_id == message.id,
            EmailActionDraft.status.in_(("confirmed", "linked")),
        )
        .first()
    )
    if active_draft:
        raise HTTPException(status_code=409, detail="A categoria não pode mudar após a ação vinculada.")
    for draft in (
        db.query(EmailActionDraft)
        .filter_by(inbox_email_id=message.id, status="pending")
        .all()
    ):
        draft.status = "cancelled"
    message.category = category
    message.confidence_band = "high"
    message.destination = (
        "task"
        if category in {"customer_quote_request", "purchase_order", "service_request"}
        else "classification_only" if category == "informational" else "review"
    )
    record = EmailMessageRecord(
        reference=message.reference,
        thread_reference=message.thread_reference,
        folder_role="inbox",
        sender=message.sender,
        recipients=(),
        subject=message.subject,
        received_at=message.received_at.replace(tzinfo=ZoneInfo(settings.assistant_timezone)),
        seen=message.seen,
        text=message.summary,
    )
    fields = extract_operational_fields(record, category)
    if message.extracted_fields is None:
        fields["uncertainty"] = [
            *list(fields.get("uncertainty", [])),
            "O corpo completo não está retido; a prévia usa apenas o resumo já armazenado.",
        ]
    # Re-extract against the stored summary only; the full email body is never persisted.
    message.extracted_fields = fields
    message.classification_reason = (message.classification_reason + "; categoria revisada manualmente")[:2000]
    message.review_status = "reviewed"
    draft = ensure_email_action_draft(db, message, reopen_cancelled=True)
    if draft is not None and draft.status == "pending":
        message.review_status = "pending"
    db.commit()
    return RedirectResponse(url=request.url_for("web_messages"), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/web/clients", name="web_clients")
def clients_page(request: Request, db: Session = Depends(get_db)) -> object:
    clients = db.query(Client).order_by(Client.razao_social.asc()).all()
    proposal_counts = dict(db.query(Proposal.client_id, func.count(Proposal.id)).group_by(Proposal.client_id).all())
    service_counts = dict(db.query(ServiceCall.client_id, func.count(ServiceCall.id)).group_by(ServiceCall.client_id).all())
    return render_template(
        request,
        "clients.html",
        {"clients": clients, "proposal_counts": proposal_counts, "service_counts": service_counts},
    )


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
    proposals = db.query(Proposal).filter(Proposal.client_id == client_id).order_by(Proposal.data_geracao.desc(), Proposal.id.desc()).limit(10).all()
    services = db.query(ServiceCall).filter(ServiceCall.client_id == client_id).order_by(ServiceCall.opened_on.desc(), ServiceCall.id.desc()).limit(10).all()
    return render_template(
        request,
        "client_form.html",
        {
            "client": client,
            "action_url": f"/web/clients/{client_id}/edit",
            "proposals": proposals,
            "services": services,
            "campaign_contacts": db.query(ClientCampaignContact)
            .filter_by(client_id=client_id)
            .order_by(ClientCampaignContact.email.asc())
            .all(),
            "campaign_form_token": promotion_form_token(f"client-contacts:{client_id}"),
        },
    )


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
    try:
        payload = UserCreate(
            nome=str(form.get("nome", "")).strip(),
            cargo=str(form.get("cargo", "")).strip(),
            email=str(form.get("email", "")).strip(),
            senha=str(form.get("senha", "")),
            ativo=form.get("ativo") == "on",
        )
    except ValidationError:
        return render_template(
            request,
            "user_form.html",
            {"error": "A senha precisa ter pelo menos 12 caracteres."},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
    proposals = db.query(Proposal).options(joinedload(Proposal.client), joinedload(Proposal.user)).order_by(Proposal.data_geracao.desc(), Proposal.id.desc()).all()
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

    try:
        payload = proposal_form.parse_proposal_form(form, client_id=client_id, user_id=user_id)
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
