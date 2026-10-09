from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.db import get_db
from app.models import Client, Proposal, User
from app.routers import proposal_form
from app.routers.web_rendering import render_template
from app.schemas import TaskCreate
from app.services import board_service, proposal_service, suggestion_service

router = APIRouter()
settings = get_settings()


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
