from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.email_review_service import EmailReviewService

router = APIRouter(tags=["email-review"])


@router.post("/web/mensagens/action-drafts/{draft_id}/confirm")
async def confirm_email_action_draft(
    draft_id: int,
    request: Request,
    db: Session = Depends(get_db),  # noqa: B008 - dependency injection do FastAPI
) -> RedirectResponse:
    form = await request.form()
    try:
        EmailReviewService(db).confirm_draft(draft_id, form)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return RedirectResponse(url=request.url_for("web_messages"), status_code=status.HTTP_303_SEE_OTHER)


@router.post("/web/mensagens/action-drafts/{draft_id}/cancel")
def cancel_email_action_draft(
    draft_id: int,
    request: Request,
    db: Session = Depends(get_db),  # noqa: B008 - dependency injection do FastAPI
) -> RedirectResponse:
    try:
        EmailReviewService(db).cancel_draft(draft_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return RedirectResponse(url=request.url_for("web_messages"), status_code=status.HTTP_303_SEE_OTHER)
