"""Characterize deterministic intents through the historical service aliases."""

import pytest

from app.assistant.contracts import EmailQueryCommand, TaskQueryCommand
from app.assistant.service import AssistantService


@pytest.mark.parametrize(
    ("method", "positive", "negative"),
    [
        ("_direct_document_query", "Qual o valor na proposta?", "Gere uma proposta"),
        ("_direct_board_query", "Mostre minhas tarefas abertas", "Bom dia"),
        (
            "_direct_daily_brief_request",
            "Bom dia, o que preciso fazer hoje?",
            "Liste tarefas",
        ),
        (
            "_direct_service_return_query",
            "Quais serviços precisam de retorno?",
            "Retorno do cliente",
        ),
        (
            "_direct_service_report_request",
            "Prepare relatório técnico",
            "Crie tarefa de relatório técnico",
        ),
        (
            "_direct_service_report_correction",
            "Corrigir o endereço",
            "Prepare relatório técnico",
        ),
        (
            "_direct_schedule_save_request",
            "Salve minha agenda",
            "Organize minha agenda",
        ),
        ("_message_mentions_date", "Sem prazo", "Quando entregar?"),
    ],
)
def test_boolean_intent_positive_and_negative(method, positive, negative):
    detector = getattr(AssistantService, method)
    assert detector(positive) is True
    assert detector(negative) is False


@pytest.mark.parametrize(
    ("message", "updates"),
    [
        ("O que chegou hoje?", {"period": "today"}),
        ("O que chegou nesta semana?", {}),
        ("O que eu ainda não li?", {"unread_only": True}),
        ("Quem está esperando minha resposta?", {"awaiting_reply": True}),
        ("Quais e-mails urgentes hoje?", {"period": "today"}),
        ("Quais e-mails urgente hoje?", {"period": "today", "attention_only": True}),
        ("Recebi cotação do fornecedor?", {"category": "vendor_quotation"}),
        ("Recebi orçamento?", {"category": "customer_quote_request"}),
        ("Chegou ordem de compra?", {"category": "purchase_order"}),
        ("Quais e-mails pedem emitir nota fiscal?", {"category": "invoice_request"}),
        ("Recebi nota fiscal recebida?", {"category": "invoice_received"}),
        ("Quais e-mails com boleto?", {"category": "accounts_payable"}),
        ("Quais e-mails de cobrança?", {"category": "accounts_receivable"}),
        ("Recebi comprovante pix?", {"category": "payment_proof"}),
        ("Recebi pedido de atendimento?", {"category": "service_request"}),
        ("Quais tarefas mencionam e-mails?", {}),
    ],
)
def test_email_intent_complete_arguments(message, updates):
    expected = (
        EmailQueryCommand(period="week", **updates)
        if "period" not in updates
        else EmailQueryCommand(**updates)
    )
    assert (
        AssistantService._direct_email_query(message).model_dump()
        == expected.model_dump()
    )


@pytest.mark.parametrize(
    "message",
    [
        "Olá",
        "Liste tarefas urgentes",
        "O que chegou hoje na oficina?",
        "Recebi peças hoje",
        "Salvar e-mail",
        "E-mails não lidos",
    ],
)
def test_email_intent_negative_and_existing_vocabulary_limits(message):
    assert AssistantService._direct_email_query(message) is None


@pytest.mark.parametrize(
    "message",
    [
        "Amanhã",
        "dia seguinte",
        "nesta semana",
        "sexta",
        "em 12 dias",
        "daqui a 3 dias",
        "10/12",
        "2026-10-08",
    ],
)
def test_supported_date_expressions(message):
    assert AssistantService._message_mentions_date(message) is True


def test_daily_brief_and_board_detectors_overlap():
    assert AssistantService._direct_daily_brief_request("Organize minha agenda") is True
    assert AssistantService._direct_board_query("Organize minha agenda") is True


def test_correction_and_date_match_existing_broad_substrings():
    assert (
        AssistantService._direct_service_report_correction("Corrija o endereço")
        is False
    )
    assert (
        AssistantService._direct_service_report_correction("Ajuste a cadeira") is True
    )
    assert AssistantService._message_mentions_date("Segunda via do documento") is True
    assert AssistantService._direct_schedule_save_request("Registrar agenda") is False


def test_task_grounding_preserves_identity_or_copies_all_arguments():
    command = TaskQueryCommand(
        client="Cliente",
        responsible="Ana",
        overdue_only=True,
        due_before="hoje",
        include_completed=True,
        limit=7,
    )
    original = command.model_dump()
    assert AssistantService._ground_task_query("Liste tarefas", command) is command
    grounded = AssistantService._ground_task_query("O que fazer primeiro?", command)
    assert grounded is not command
    assert grounded.model_dump() == {**original, "priorities": True}
    assert command.model_dump() == original
    assert AssistantService._ground_task_query("Prioridade", grounded) is grounded


def test_email_grounding_preserves_identity_or_copies_all_arguments():
    command = EmailQueryCommand(
        period="custom",
        start_date="2026-10-01",
        end_date="2026-10-02",
        sender="cliente@example.test",
        attention_only=True,
        reference="ref",
        category="purchase_order",
        limit=7,
    )
    original = command.model_dump()
    assert AssistantService._ground_email_query("Olá", command) is command
    grounded = AssistantService._ground_email_query(
        "Resuma os e-mails desta semana que não li esperando minha resposta hoje",
        command,
    )
    assert grounded is not command
    assert grounded.model_dump() == {
        **original,
        "period": "week",
        "attention_only": False,
        "unread_only": True,
        "awaiting_reply": True,
    }
    assert command.model_dump() == original


def test_email_grounding_today_keeps_attention_for_non_listing():
    command = EmailQueryCommand(attention_only=True)
    assert (
        AssistantService._ground_email_query("Urgentes hoje", command).model_dump()
        == command.model_dump()
    )
