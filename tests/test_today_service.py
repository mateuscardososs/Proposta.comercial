from datetime import date

from app.models import Client, EmailTaskLink, ServiceCall, ServiceWorkflowStep, Task
from app.services.today_service import get_task_day_plan, get_today_agenda


def test_task_day_plan_uses_required_order_and_explains_each_position(db):
    client = Client(razao_social="Cliente sintético da agenda")
    db.add(client)
    db.flush()
    tasks = [
        Task(titulo="Urgente atrasada", descricao="Urgente", status="a_fazer", prazo=date(2026, 9, 29), ordem=0),
        Task(titulo="Atrasada", status="a_fazer", prazo=date(2026, 9, 30), ordem=0, client_id=client.id),
        Task(titulo="Hoje", status="a_fazer", prazo=date(2026, 10, 2), ordem=0, client_id=client.id),
        Task(titulo="Hoje urgente", descricao="Prioridade alta", status="em_andamento", prazo=date(2026, 10, 2), ordem=1),
        Task(titulo="Urgente futura", descricao="Atendimento urgente", status="a_fazer", prazo=date(2026, 10, 4), ordem=0),
        Task(titulo="Documentação após serviço", status="servico_feito_falta_nota_pedido", ordem=0),
        Task(titulo="Execução iniciada", status="em_andamento", ordem=0),
        Task(titulo="Prazo futuro", status="a_fazer", prazo=date(2026, 10, 5), ordem=0),
        Task(titulo="Sem prazo e cliente pendente", status="a_fazer", client_name="Roca", client_link_status="unlinked", ordem=0),
        Task(titulo="Aguardando retorno", status="aguardando_cliente", ordem=0),
        Task(titulo="Concluída", status="concluido", prazo=date(2026, 9, 20), ordem=0),
    ]
    db.add_all(tasks)
    db.commit()
    before = [(task.id, task.status, task.prazo, task.client_id) for task in db.query(Task).all()]

    plan = get_task_day_plan(db, today=date(2026, 10, 2))

    assert [item.title for item in plan.items] == [
        "Urgente atrasada",
        "Atrasada",
        "Hoje urgente",
        "Hoje",
        "Urgente futura",
        "Documentação após serviço",
        "Execução iniciada",
        "Prazo futuro",
        "Sem prazo e cliente pendente",
        "Aguardando retorno",
    ]
    assert "atrasada" in plan.items[0].reason.casefold()
    assert plan.items[0].priority_label == "Urgente"
    assert "prazo explicitamente cadastrado para hoje" in plan.items[2].reason.casefold()
    assert plan.items[2].client_name is None
    assert plan.items[3].client_name == "Cliente sintético da agenda"
    assert "pendente" in plan.items[5].reason.casefold()
    assert "em andamento" in plan.items[6].status_label.casefold()
    assert plan.items[8].client_link_status == "pending_review"
    assert plan.items[8].client_name == "Roca"
    assert any(section.key == "no_deadline" for section in plan.sections)
    assert any(section.key == "waiting_customer" for section in plan.sections)
    assert plan.due_today_count == 2
    assert [(task.id, task.status, task.prazo, task.client_id) for task in db.query(Task).all()] == before


def test_task_day_plan_includes_every_open_task_beyond_fifty(db):
    db.add_all(
        Task(titulo=f"Tarefa aberta sintética {index}", status="a_fazer", ordem=index)
        for index in range(73)
    )
    db.commit()

    plan = get_task_day_plan(db, today=date(2026, 10, 2))

    assert plan.open_count == 73
    assert len(plan.items) == 73
    assert "Tarefa aberta sintética 72" in {item.title for item in plan.items}


def test_task_day_plan_empty_board_has_no_synthetic_items(db):
    plan = get_task_day_plan(db, today=date(2026, 10, 2))

    assert plan.items == ()
    assert plan.sections == ()
    assert plan.open_count == 0
    assert plan.due_today_count == 0


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
