from datetime import date

from app.models import Client, EmailTaskLink, ServiceCall, ServiceWorkflowStep, Task
from app.services.today_service import get_today_agenda


def test_today_agenda_is_read_only_transparent_and_deterministic(db):
    client = Client(
        razao_social="Cliente Sintético",
        cnpj="",
        endereco_linha1="",
        endereco_linha2="",
        cep="",
        cidade_uf="",
        pais="Brasil",
        caixa_postal="",
        telefone="",
        site="",
        contato_padrao="",
    )
    db.add(client)
    db.flush()
    overdue = Task(
        titulo="Relatório pendente",
        descricao="",
        status="a_fazer",
        client_id=client.id,
        prazo=date(2026, 10, 1),
        ordem=0,
    )
    today = Task(
        titulo="Ligar para cliente",
        descricao="",
        status="em_andamento",
        client_id=client.id,
        prazo=date(2026, 10, 2),
        ordem=0,
    )
    service = ServiceCall(
        client_id=client.id,
        summary="Inspeção",
        opened_on=date(2026, 10, 1),
        execution_status="in_progress",
        administrative_status="open",
    )
    db.add_all([overdue, today, service])
    db.commit()

    agenda = get_today_agenda(db, today=date(2026, 10, 2), lookahead_days=7)

    assert [item.title for item in agenda.items[:2]] == [
        "Relatório pendente",
        "Ligar para cliente",
    ]
    assert "atrasada" in agenda.items[0].reason.casefold()
    assert any(item.source_type == "service" for item in agenda.items)
    assert agenda.summary.overdue == 1
    assert db.query(Task).filter(Task.status == "a_fazer").one().status == "a_fazer"


def test_completed_execution_remains_visible_when_administrative_step_is_pending(db):
    client = Client(razao_social="Cliente de teste")
    db.add(client)
    db.flush()
    call = ServiceCall(
        client_id=client.id,
        summary="Calibração concluída",
        opened_on=date(2026, 10, 1),
        execution_status="completed",
        administrative_status="open",
    )
    db.add(call)
    db.flush()
    db.add(
        ServiceWorkflowStep(
            service_call_id=call.id, step_type="report", status="pending"
        )
    )
    db.commit()

    agenda = get_today_agenda(db, today=date(2026, 10, 2), lookahead_days=7)

    item = next(item for item in agenda.items if item.source_type == "service")
    assert "Execução técnica concluída" in item.reason
    assert "report está pending" in item.reason


def test_email_origin_task_is_in_today_without_deadline_and_marked_as_source(db):
    task = Task(titulo="Conferir orçamento recebido", status="a_fazer", ordem=0)
    db.add(task)
    db.flush()
    db.add(
        EmailTaskLink(
            provider="synthetic",
            mailbox_key="today",
            reference="source-1",
            action_type="email:customer_quote_request",
            task_id=task.id,
            task_title_snapshot=task.titulo,
        )
    )
    db.commit()

    agenda = get_today_agenda(db, today=date(2026, 10, 2))

    assert len(agenda.items) == 1
    assert agenda.items[0].email_origin is True
