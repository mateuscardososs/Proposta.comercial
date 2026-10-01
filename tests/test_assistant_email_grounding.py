from __future__ import annotations

import httpx
import pytest

from app.assistant.contracts import ConversationCommand
from app.assistant.ollama import _validate_conversation_grounding
from app.assistant.provider import ProviderToolResult


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
            latest_assistant=history,
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
        latest_assistant=history,
        current_message="Por que o primeiro é importante?",
    )
    assert accepted.message.startswith("No resultado anterior")


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
