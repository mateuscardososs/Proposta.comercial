from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.assistant.contracts import (
    AssistantConfirmationRequest,
    AssistantHistory,
    AssistantMessageRequest,
    AssistantReply,
)
from app.assistant.ollama import OllamaProvider
from app.assistant.provider import AssistantProvider
from app.assistant.service import AssistantService
from app.config import get_settings
from app.db import get_db
from app.routers.pages import render_template


router = APIRouter(tags=["assistant"])


def get_assistant_provider() -> AssistantProvider:
    settings = get_settings()
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        connect_timeout=settings.ollama_connect_timeout,
        read_timeout=settings.ollama_read_timeout,
    )


def _service(db: Session, provider: AssistantProvider | None = None) -> AssistantService:
    settings = get_settings()
    return AssistantService(
        db,
        provider,
        timezone=settings.assistant_timezone,
        context_messages=settings.assistant_context_messages,
    )


@router.get("/web/assistente", name="web_assistant")
def assistant_page(request: Request) -> object:
    return render_template(
        request,
        "assistant.html",
        {"title": "Assistente operacional", "full_width": True},
    )


@router.post("/api/assistant/messages", response_model=AssistantReply)
def assistant_message(
    payload: AssistantMessageRequest,
    db: Session = Depends(get_db),
    provider: AssistantProvider = Depends(get_assistant_provider),
) -> AssistantReply:
    try:
        return _service(db, provider).handle_message(
            message=payload.message,
            request_id=payload.request_id,
            conversation_id=payload.conversation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/api/assistant/conversations/{conversation_id}",
    response_model=AssistantHistory,
)
def assistant_history(
    conversation_id: int,
    db: Session = Depends(get_db),
) -> AssistantHistory:
    try:
        messages = _service(db).get_history(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return AssistantHistory(conversation_id=conversation_id, messages=messages)


@router.post("/api/assistant/actions/{action_id}/confirm", response_model=AssistantReply)
def assistant_confirm(
    action_id: int,
    payload: AssistantConfirmationRequest,
    db: Session = Depends(get_db),
) -> AssistantReply:
    try:
        return _service(db).confirm_action(action_id, payload.confirmation_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/api/assistant/actions/{action_id}/cancel", response_model=AssistantReply)
def assistant_cancel(
    action_id: int,
    payload: AssistantConfirmationRequest,
    db: Session = Depends(get_db),
) -> AssistantReply:
    try:
        return _service(db).cancel_action(action_id, payload.confirmation_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
