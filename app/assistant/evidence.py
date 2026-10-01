from __future__ import annotations

import re
from collections.abc import Sequence

from app.assistant.dates import normalize_text
from app.assistant.provider import ProviderToolResult


def validate_execution_claims(
    message: str,
    *,
    tool_results: Sequence[ProviderToolResult],
) -> None:
    """Reject claims about system state or actions without request-scoped evidence."""

    normalized = normalize_text(message)
    evidence = {result.tool: result for result in tool_results}

    email_claim = _positive_claim(
        normalized,
        (
            r"\b(?:conferi|consultei|verifiquei|li|busquei|revisei)\b.{0,80}\b(?:e[- ]?mails?|caixa|mensagens?)\b",
            r"\b(?:encontrei|localizei)\b.{0,60}\b(?:e[- ]?mails?|mensagens?)\b",
        ),
    )
    email_result = evidence.get("consultar_emails")
    if email_claim and email_result is None:
        raise ValueError("A resposta alegou consulta de e-mail sem evidencia desta solicitacao.")
    if email_claim and email_result is not None and email_result.state == "failed":
        raise ValueError("Uma consulta de e-mail que falhou nao pode ser descrita como bem-sucedida.")
    if email_claim and email_result is not None:
        count = email_result.payload.get("count")
        number_words = {
            "zero": 0,
            "um": 1,
            "uma": 1,
            "dois": 2,
            "duas": 2,
            "tres": 3,
            "quatro": 4,
            "cinco": 5,
        }
        claimed_counts = [
            int(value) if value.isdigit() else number_words[value]
            for value in re.findall(
                r"\b(\d+|zero|um|uma|dois|duas|tres|quatro|cinco)\s+(?:e[- ]?mails?|mensagens?)\b",
                normalized,
            )
        ]
        if isinstance(count, int) and any(value != count for value in claimed_counts):
            raise ValueError("A resposta inventou a quantidade de e-mails consultados.")

    unsupported_action_patterns = (
        r"\b(?:marquei|registrei|lancei)\b.{0,50}\b(?:conta|pagamento|financeiro)\b",
        r"\b(?:emiti|gerei)\b.{0,50}\b(?:nota fiscal|nf ?e)\b",
        r"\b(?:enviei|encaminhei)\b.{0,50}\b(?:e[- ]?mail|mensagem)\b",
        r"\b(?:alterei|atualizei|salvei)\b.{0,50}\b(?:documento|relatorio|proposta)\b",
        r"\b(?:registrei|executei|conclui)\b.{0,50}\b(?:servico|atendimento)\b",
        r"\b(?:conferi|consultei|verifiquei|revisei)\b.{0,50}\b(?:financeiro|cobrancas?|documentos?|relatorios?|servicos?|atendimentos?)\b",
    )
    if _positive_claim(normalized, unsupported_action_patterns):
        raise ValueError("A resposta alegou uma operacao sem evidencia da ferramenta correspondente.")


def _positive_claim(normalized: str, patterns: Sequence[str]) -> bool:
    for pattern in patterns:
        for match in re.finditer(pattern, normalized):
            prefix = normalized[max(0, match.start() - 12) : match.start()]
            if not re.search(r"\bnao\s*$", prefix):
                return True
    return False
