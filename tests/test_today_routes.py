from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.models import EmailSyncState, InboxEmail


def test_today_is_home_and_shell_has_keyboard_navigation(db):
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Ordem recomendada" in response.text
    assert 'href="#mainContent"' in response.text
    assert 'aria-label="Navegação principal"' in response.text
    assert 'aria-controls="siteNav"' in response.text
    assert (
        'aria-label="Breadcrumb"' not in response.text
    )  # home has no redundant breadcrumb


def test_messages_page_explains_sync_status_and_never_offers_email_mutations(db):
    with TestClient(app) as client:
        response = client.get("/web/mensagens")

    assert response.status_code == 200
    assert "Uma falha é diferente de uma caixa vazia" in response.text
    assert "não altera flags" in response.text
    assert "Enviar" not in response.text
    assert "Excluir" not in response.text


def test_messages_pause_and_category_review_only_change_local_projection(db):
    settings = get_settings()
    sync_state = EmailSyncState(
        provider=settings.email_provider, mailbox_key=settings.email_sync_mailbox_key
    )
    email = InboxEmail(
        provider=settings.email_provider,
        mailbox_key=settings.email_sync_mailbox_key,
        reference="synthetic-route-message",
        thread_reference="",
        sender="Sintético",
        subject="Mensagem de teste",
        received_at=datetime(2026, 10, 2, 10, tzinfo=ZoneInfo("America/Recife")),
        seen=False,
        summary="Resumo de teste",
        category="other_review",
        confidence_band="low",
        destination="review",
        classification_reason="Teste",
        priority="normal",
        review_status="pending",
        last_seen_at=datetime(2026, 10, 2, 10, tzinfo=ZoneInfo("America/Recife")),
    )
    db.add_all([sync_state, email])
    db.commit()

    with TestClient(app, follow_redirects=False) as client:
        pause = client.post("/web/mensagens/sync-state", data={"action": "pause"})
        review = client.post(
            f"/web/mensagens/{email.id}/review", data={"category": "informational"}
        )

    db.refresh(sync_state)
    db.refresh(email)
    assert pause.status_code == 303
    assert review.status_code == 303
    assert sync_state.paused is True
    assert email.category == "informational"
    assert email.review_status == "reviewed"
