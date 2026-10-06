from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.models import EmailSyncState, InboxEmail, Task


def test_today_is_home_and_shell_has_keyboard_navigation(db):
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Precisa de atenção" in response.text
    assert 'href="#mainContent"' in response.text
    assert 'aria-label="Navegação principal"' in response.text
    assert 'aria-controls="siteNav"' in response.text
    assert "data-app-shell" in response.text
    assert "data-sidebar" in response.text
    assert "data-sidebar-toggle" in response.text
    assert 'data-nav-group="operacao"' in response.text
    assert 'data-nav-group="comunicacao"' in response.text
    assert response.text.index('aria-label="E-mails e mensagens"') < response.text.index(
        'aria-label="Assistente"'
    )
    assert 'localStorage.getItem("adbalancas-nav-collapsed")' in response.text
    assert (
        'aria-label="Breadcrumb"' not in response.text
    )  # home has no redundant breadcrumb


def test_today_page_renders_complete_synthetic_task_plan_without_fake_time_blocks(db):
    today = datetime.now(ZoneInfo("America/Recife")).date()
    db.add_all(
        [
            Task(titulo="Tarefa atrasada sintética", status="a_fazer", prazo=today - timedelta(days=1), ordem=0),
            Task(titulo="Tarefa de hoje sintética", status="em_andamento", prazo=today, ordem=0),
            Task(titulo="Tarefa futura sintética", status="a_fazer", prazo=today + timedelta(days=2), ordem=0),
            Task(titulo="Tarefa sem prazo sintética", status="a_fazer", ordem=0),
            *[
                Task(titulo=f"Tarefa aberta extra {index}", status="a_fazer", ordem=index)
                for index in range(8)
            ],
        ]
    )
    db.commit()

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "Plano de tarefas para hoje" in response.text
    assert "Tarefa atrasada sintética" in response.text
    assert "Tarefa de hoje sintética" in response.text
    assert "Tarefa futura sintética" in response.text
    assert "Tarefa sem prazo sintética" in response.text
    assert "Tarefa aberta extra 7" in response.text
    assert "Sequência completa e somente de leitura" in response.text
    assert "dependências formais" in response.text


def test_messages_page_explains_sync_status_and_never_offers_email_mutations(db):
    with TestClient(app) as client:
        response = client.get("/web/mensagens")

    assert response.status_code == 200
    assert "Uma falha é diferente de uma caixa vazia" in response.text
    assert "não altera flags" in response.text
    assert "Enviar" not in response.text
    assert "Excluir" not in response.text


def test_messages_page_separates_operational_work_from_information_and_review(db):
    settings = get_settings()
    now = datetime(2026, 10, 2, 10, tzinfo=ZoneInfo("America/Recife"))
    common = {
        "provider": settings.email_provider,
        "mailbox_key": settings.email_sync_mailbox_key,
        "thread_reference": "synthetic-thread",
        "sender": "fixture@example.test",
        "seen": True,
        "received_at": now,
        "last_seen_at": now,
    }
    emails = [
        InboxEmail(
            **common,
            reference="synthetic-operational",
            subject="Pedido de orçamento",
            summary="Solicito orçamento para serviço técnico.",
            category="customer_quote_request",
            confidence_band="high",
            destination="task",
            classification_reason="Pedido de orçamento explícito.",
            priority="normal",
            review_status="classified",
        ),
        InboxEmail(
            **common,
            reference="synthetic-information",
            subject="Newsletter de promoção",
            summary="Oferta especial.",
            category="informational",
            confidence_band="high",
            destination="classification_only",
            classification_reason="Conteúdo promocional.",
            priority="low",
            review_status="classified",
        ),
        InboxEmail(
            **common,
            reference="synthetic-review",
            subject="Cotação",
            summary="Segue a cotação para avaliação.",
            category="other_review",
            confidence_band="low",
            destination="review",
            classification_reason="Contexto insuficiente.",
            priority="low",
            review_status="pending",
        ),
    ]
    db.add_all(emails)
    db.commit()

    with TestClient(app) as client:
        response = client.get("/web/mensagens")

    assert response.status_code == 200
    assert 'data-message-tab="operational"' in response.text
    assert 'aria-selected="true"' in response.text
    assert 'data-message-panel="informational"' in response.text
    assert 'data-message-panel="review"' in response.text
    assert 'id="messages-informational"' in response.text
    assert 'id="messages-review"' in response.text
    assert 'aria-labelledby="tab-informational" hidden' in response.text
    assert 'aria-labelledby="tab-review" hidden' in response.text
    assert "Operacionais" in response.text
    assert "Informativos/outros" in response.text
    assert "Revisar" in response.text
    assert 'data-message-row data-bucket="operational"' in response.text
    assert 'data-message-row data-bucket="informational"' in response.text
    assert 'data-message-row data-bucket="review"' in response.text
    operational_panel = response.text.split('id="messages-operational"', 1)[1].split(
        "</section>", 1
    )[0]
    assert "Pedido de orçamento" in operational_panel
    assert "Newsletter de promoção" not in operational_panel
    assert "Cotação" not in operational_panel


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
