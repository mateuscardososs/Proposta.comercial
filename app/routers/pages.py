from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.assistant.email import classification as _email_classification
from app.assistant.email.contracts import EmailMessageRecord
from app.assistant.email.extraction import extract_operational_fields
from app.config import get_settings
from app.db import get_db
from app.models import (
    EmailActionDraft,
    EmailSyncState,
    InboxEmail,
    User,
)
from app.routers import proposal_form, web_clients, web_proposals, web_rendering
from app.routers.users import hash_password
from app.routers.web_rendering import render_template
from app.schemas import (
    UserCreate,
)
from app.services import (
    dashboard_service,
)
from app.services import message_workbench_service as _message_workbench_service
from app.services.daily_schedule_service import build_daily_schedule
from app.services.email_review_service import ensure_email_action_draft
from app.services.message_workbench_service import get_message_workbench
from app.services.today_service import get_today_agenda

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
board_service = web_proposals.board_service
proposal_service = web_proposals.proposal_service
suggestion_service = web_proposals.suggestion_service
format_brl = web_rendering.format_brl
format_date_br = web_rendering.format_date_br
clients_page = web_clients.clients_page
client_new_page = web_clients.client_new_page
client_new_submit = web_clients.client_new_submit
client_detail_page = web_clients.client_detail_page
client_edit_submit = web_clients.client_edit_submit
_default_form_data = web_proposals._default_form_data
_proposal_to_payload = web_proposals._proposal_to_payload
_prefill_from_last = web_proposals._prefill_from_last
_build_new_proposal_redirect_url = web_proposals._build_new_proposal_redirect_url
_required_positive_int = web_proposals._required_positive_int
proposals_page = web_proposals.proposals_page
import_proposals_page = web_proposals.import_proposals_page
proposal_new_page = web_proposals.proposal_new_page
proposal_new_submit = web_proposals.proposal_new_submit
proposal_detail_page = web_proposals.proposal_detail_page
proposal_duplicate_submit = web_proposals.proposal_duplicate_submit
proposal_revision_submit = web_proposals.proposal_revision_submit


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


router.include_router(web_clients.router)


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


router.include_router(web_proposals.router)
