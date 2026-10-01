from __future__ import annotations

import httpx
import pytest
from datetime import date

from app.assistant.contracts import ConversationCommand
from app.assistant.ollama import OllamaProvider, _validate_conversation_grounding
from app.assistant.provider import ProviderMessage, ProviderToolResult


@pytest.mark.parametrize(
    "claim",
    [
        "Conferi os e-mails e não chegou nada.",
        "Verifiquei sua caixa e encontrei duas mensagens.",
        "Li os e-mails de hoje.",
    ],
)
def test_email_consultation_claim_requires_current_evidence(claim):
    with pytest.raises(ValueError, match="e-mail.*evidencia"):
        _validate_conversation_grounding(
            ConversationCommand(message=claim),
            tool_results=(),
            current_message="Quais e-mails chegaram hoje?",
        )


def test_successful_email_tool_result_allows_consultation_claim():
    command = ConversationCommand(message="Consultei os e-mails de hoje e encontrei uma mensagem.")

    result = _validate_conversation_grounding(
        command,
        tool_results=(
            ProviderToolResult(
                tool="consultar_emails",
                evidence_id="email:req-1",
                state="success",
                payload={"count": 1},
            ),
        ),
        current_message="Quais e-mails chegaram hoje?",
    )

    assert result == command


def test_failed_email_tool_result_cannot_be_described_as_successful_consultation():
    with pytest.raises(ValueError, match="bem-sucedida"):
        _validate_conversation_grounding(
            ConversationCommand(message="Consultei os e-mails e encontrei uma mensagem."),
            tool_results=(
                ProviderToolResult(
                    tool="consultar_emails",
                    evidence_id="email:req-2",
                    state="failed",
                    payload={"count": 0},
                ),
            ),
            current_message="Quais e-mails chegaram hoje?",
        )


def test_email_result_count_cannot_be_invented():
    with pytest.raises(ValueError, match="quantidade"):
        _validate_conversation_grounding(
            ConversationCommand(message="Encontrei três e-mails hoje."),
            tool_results=(
                ProviderToolResult(
                    tool="consultar_emails",
                    evidence_id="email:req-3",
                    state="success",
                    payload={"count": 1, "messages": [{"reference": "one"}]},
                ),
            ),
            current_message="Quais e-mails chegaram hoje?",
        )


def test_historical_email_facts_must_be_labeled_as_previous_result():
    history = (
        "Mostrei duas mensagens.\nMensagens exibidas nesta resposta: "
        "[{'position': 1, 'sender': 'Marina - Alfa Indústria', "
        "'subject': 'Autorização e prazo', 'reason': 'prazo 02/10/2026'}]"
    )
    with pytest.raises(ValueError, match="resultado anterior"):
        _validate_conversation_grounding(
            ConversationCommand(
                message="O primeiro e-mail é importante e foi enviado por Marina - Alfa Indústria."
            ),
            tool_results=(),
            latest_email_evidence=history,
            current_message="Por que o primeiro é importante?",
        )

    accepted = _validate_conversation_grounding(
        ConversationCommand(
            message=(
                "No resultado anterior, o primeiro e-mail foi enviado por Marina - Alfa Indústria "
                "e traz prazo em 02/10/2026."
            )
        ),
        tool_results=(),
        latest_email_evidence=history,
        current_message="Por que o primeiro é importante?",
    )
    assert accepted.message.startswith("No resultado anterior")


def test_email_history_does_not_contaminate_an_unrelated_change_of_subject():
    command = ConversationCommand(message="Por nada! Posso ajudar em outro assunto.")

    accepted = _validate_conversation_grounding(
        command,
        tool_results=(),
        latest_email_evidence=(
            "Mensagens exibidas nesta resposta: "
            "[{'position': 1, 'sender': 'Marina', 'subject': 'Prazo'}]"
        ),
        current_message="Obrigado.",
    )

    assert accepted == command


@pytest.mark.parametrize(
    "message",
    [
        "O e-mail foi enviado por João da Empresa Inventada.",
        'O assunto é "Contrato aprovado".',
        "O valor informado é R$ 9.999,00.",
    ],
)
def test_email_response_cannot_invent_sender_subject_or_amount(message):
    with pytest.raises(ValueError, match="e-mail"):
        _validate_conversation_grounding(
            ConversationCommand(message=message),
            tool_results=(
                ProviderToolResult(
                    tool="consultar_emails",
                    evidence_id="email:grounded",
                    state="success",
                    payload={
                        "count": 1,
                        "messages": [
                            {
                                "reference": "syn-1",
                                "sender": "Marina - Alfa Indústria",
                                "subject": "Prazo de inspeção",
                                "summary": "Relatório até 02/10/2026.",
                                "priority": "high",
                            }
                        ],
                    },
                ),
            ),
            current_message="Resuma o e-mail.",
        )


@pytest.mark.parametrize(
    "claim",
    [
        "Marquei a conta como paga.",
        "Emiti a nota fiscal.",
        "Enviei o e-mail.",
        "Atualizei o documento.",
        "Registrei o serviço.",
        "Conferi os documentos e está tudo certo.",
        "Consultei o financeiro e não há cobrança.",
        "Verifiquei os serviços de hoje.",
    ],
)
def test_other_operational_claims_require_domain_evidence(claim):
    with pytest.raises(ValueError):
        _validate_conversation_grounding(
            ConversationCommand(message=claim),
            tool_results=(),
            current_message="Faça isso.",
        )


def test_large_bounded_email_result_fits_provider_envelope():
    captured = {}

    def handler(request):
        captured["size"] = len(request.content)
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "Resumo concluído."}},
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="local-test",
        connect_timeout=1,
        read_timeout=1,
        transport=httpx.MockTransport(handler),
    )
    item = {
        "reference": "r" * 160,
        "sender": "s" * 500,
        "subject": "t" * 500,
        "summary": "m" * 400,
        "priority": "high",
        "priority_reason": "p" * 300,
        "action_suggested": "a" * 200,
        "limitations": ["l" * 200],
    }
    result = ProviderToolResult(
        tool="consultar_emails",
        evidence_id="email:large",
        state="success",
        payload={"count": 3, "messages": [item, item, item]},
    )

    command = provider.interpret(
        [
            ProviderMessage(role="assistant", content="h" * 3000),
            ProviderMessage(role="user", content="Resuma."),
        ],
        today=date(2026, 10, 1),
        timezone="America/Recife",
        tool_results=(result,),
        allowed_tools={"responder_conversa"},
    )

    assert command.message == "Resumo concluído."
    assert captured["size"] < 12000
