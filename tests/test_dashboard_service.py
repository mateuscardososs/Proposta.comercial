from datetime import date
from decimal import Decimal

from sqlalchemy import event

from app.models import Client, Lancamento, Proposal, Task, User
from app.services import dashboard_service


def _add_proposal_references(db):
    client = Client(razao_social="Cliente Dashboard")
    user = User(
        nome="Responsável Dashboard",
        email="dashboard@example.com",
        senha_hash="hash",
    )
    db.add_all([client, user])
    db.flush()
    return client, user


def test_dashboard_summary_aggregates_existing_modules(db):
    client, user = _add_proposal_references(db)
    db.add_all(
        [
            Lancamento(
                tipo="receber",
                descricao="Receber vencido",
                valor=Decimal("100.00"),
                data_vencimento=date(2026, 8, 30),
                status="pendente",
            ),
            Lancamento(
                tipo="receber",
                descricao="Receber hoje",
                valor=Decimal("50.00"),
                data_vencimento=date(2026, 8, 31),
                status="pendente",
            ),
            Lancamento(
                tipo="receber",
                descricao="Receber futuro",
                valor=Decimal("200.00"),
                data_vencimento=date(2026, 9, 10),
                status="pendente",
            ),
            Lancamento(
                tipo="receber",
                descricao="Receber pago",
                valor=Decimal("999.00"),
                data_vencimento=date(2026, 8, 1),
                status="pago",
                data_pagamento=date(2026, 8, 2),
            ),
            Lancamento(
                tipo="pagar",
                descricao="Pagar vencido",
                valor=Decimal("70.00"),
                data_vencimento=date(2026, 8, 30),
                status="pendente",
            ),
            Lancamento(
                tipo="pagar",
                descricao="Pagar hoje",
                valor=Decimal("20.00"),
                data_vencimento=date(2026, 8, 31),
                status="pendente",
            ),
            Lancamento(
                tipo="pagar",
                descricao="Pagar futuro",
                valor=Decimal("30.00"),
                data_vencimento=date(2026, 9, 10),
                status="pendente",
            ),
            Lancamento(
                tipo="pagar",
                descricao="Pagar pago",
                valor=Decimal("888.00"),
                data_vencimento=date(2026, 8, 1),
                status="pago",
                data_pagamento=date(2026, 8, 2),
            ),
            Task(
                titulo="A fazer vencida",
                status="a_fazer",
                prazo=date(2026, 8, 30),
                ordem=0,
            ),
            Task(
                titulo="A fazer futura",
                status="a_fazer",
                prazo=date(2026, 9, 10),
                ordem=1,
            ),
            Task(
                titulo="Em andamento vencida",
                status="em_andamento",
                prazo=date(2026, 8, 30),
                ordem=0,
            ),
            Task(
                titulo="Serviço feito vencido",
                status="servico_feito_falta_nota_pedido",
                prazo=date(2026, 8, 30),
                ordem=0,
            ),
            Task(
                titulo="Aguardando cliente vencida",
                status="aguardando_cliente",
                prazo=date(2026, 8, 30),
                ordem=0,
            ),
            Task(
                titulo="Concluída vencida",
                status="concluido",
                prazo=date(2026, 8, 1),
                ordem=0,
            ),
            Task(
                titulo="Serviço sem prazo",
                status="servico_feito_falta_nota_pedido",
                prazo=None,
                ordem=1,
            ),
            Proposal(
                numero=101,
                revisao="00",
                client_id=client.id,
                user_id=user.id,
                data_geracao=date(2026, 8, 1),
                valor_total=Decimal("500.00"),
            ),
            Proposal(
                numero=102,
                revisao="00",
                client_id=client.id,
                user_id=user.id,
                data_geracao=date(2026, 8, 31),
                valor_total=Decimal("1000.00"),
            ),
            Proposal(
                numero=103,
                revisao="00",
                client_id=client.id,
                user_id=user.id,
                data_geracao=date(2026, 7, 31),
                valor_total=Decimal("9000.00"),
            ),
            Proposal(
                numero=104,
                revisao="00",
                client_id=client.id,
                user_id=user.id,
                data_geracao=date(2026, 9, 1),
                valor_total=Decimal("8000.00"),
            ),
        ]
    )
    db.commit()

    summary = dashboard_service.get_dashboard_summary(
        db,
        reference_date=date(2026, 8, 31),
    )

    assert summary.receber_pendente == Decimal("350.00")
    assert summary.receber_vencido == Decimal("100.00")
    assert summary.pagar_pendente == Decimal("120.00")
    assert summary.pagar_vencido == Decimal("70.00")
    assert summary.tarefas_atrasadas == 4
    assert summary.tarefas_a_fazer == 2
    assert summary.tarefas_em_andamento == 1
    assert summary.propostas_mes_quantidade == 2
    assert summary.propostas_mes_valor == Decimal("1500.00")
    assert summary.mes_inicio == date(2026, 8, 1)
    assert summary.mes_fim_exclusivo == date(2026, 9, 1)


def test_empty_database_returns_typed_zeroes(db):
    summary = dashboard_service.get_dashboard_summary(
        db,
        reference_date=date(2026, 8, 31),
    )

    assert summary.receber_pendente == Decimal("0.00")
    assert summary.receber_vencido == Decimal("0.00")
    assert summary.pagar_pendente == Decimal("0.00")
    assert summary.pagar_vencido == Decimal("0.00")
    assert summary.tarefas_atrasadas == 0
    assert summary.tarefas_a_fazer == 0
    assert summary.tarefas_em_andamento == 0
    assert summary.propostas_mes_quantidade == 0
    assert summary.propostas_mes_valor == Decimal("0.00")
    assert summary.mes_inicio == date(2026, 8, 1)
    assert summary.mes_fim_exclusivo == date(2026, 9, 1)


def test_december_uses_january_as_exclusive_upper_bound(db):
    summary = dashboard_service.get_dashboard_summary(
        db,
        reference_date=date(2026, 12, 15),
    )

    assert summary.mes_inicio == date(2026, 12, 1)
    assert summary.mes_fim_exclusivo == date(2027, 1, 1)


def test_dashboard_summary_executes_exactly_three_selects(db):
    selects: list[str] = []

    def capture_select(conn, cursor, statement, parameters, context, executemany):
        del conn, cursor, parameters, context, executemany
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture_select)
    try:
        dashboard_service.get_dashboard_summary(
            db,
            reference_date=date(2026, 8, 31),
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_select)

    assert len(selects) == 3
