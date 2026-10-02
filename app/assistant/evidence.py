from __future__ import annotations

import re
from collections.abc import Sequence

from app.assistant.dates import normalize_text
from app.assistant.provider import ProviderToolResult


def references_prior_email_context(message: str) -> bool:
    """Return whether the request explicitly points at previously shown email data."""

    normalized = normalize_text(message)
    return bool(
        re.search(
            r"\b(?:este|esta|esse|essa|aquele|aquela)\s+(?:e[- ]?mail|mensagem)\b|"
            r"\b(?:o|a)\s+(?:primeir[oa]|segund[oa]|terceir[oa])\b|"
            r"\b(?:primeir[oa]|segund[oa]|terceir[oa])\s+(?:e[- ]?mail|mensagem)\b|"
            r"\b(?:quem (?:enviou|mandou)|qual (?:o )?remetente|leia mais|"
            r"por que (?:esse|essa|este|esta|ele|ela)|responder (?:esse|essa|este|esta))\b",
            normalized,
        )
    )


def validate_execution_claims(
    message: str,
    *,
    tool_results: Sequence[ProviderToolResult],
    allow_historical_email_claim: bool = False,
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
    if email_claim and email_result is None and not allow_historical_email_claim:
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
    if email_result is not None:
        candidate_count = email_result.payload.get("candidate_count")
        claims_empty_period = bool(
            re.search(
                r"\b(?:nao (?:encontrei|ha|tem)|nenhuma|zero)\b.{0,45}"
                r"\b(?:e[- ]?mails?|mensage(?:m|ns))\b",
                normalized,
            )
        )
        explains_filter = any(
            term in normalized
            for term in (
                "filtro",
                "correspondeu",
                "prioritaria",
                "prioritario",
                "urgente",
                "aguardando resposta",
            )
        )
        if (
            isinstance(candidate_count, int)
            and candidate_count > 0
            and claims_empty_period
            and not explains_filter
        ):
            raise ValueError(
                "A resposta descreveu o periodo como vazio, mas a consulta encontrou mensagens antes dos filtros."
            )

    service_query_claim = _positive_claim(
        normalized,
        (
            r"\b(?:conferi|consultei|verifiquei|revisei|busquei)\b.{0,80}\b(?:servicos?|chamados?|atendimentos?)\b",
            r"\b(?:encontrei|localizei)\b.{0,60}\b(?:servicos?|chamados?|atendimentos?)\b",
        ),
    )
    service_absence_claim = bool(
        re.search(
            r"\b(?:nao encontrei|nao localizei|nao ha|nao consta|nao foram encontrados?|"
            r"nenhum|nenhuma|zero)\b.{0,60}\b(?:servicos?|chamados?|atendimentos?)\b|"
            r"\b(?:servicos?|chamados?|atendimentos?)\b.{0,50}\b"
            r"(?:nao foram encontrados?|nao foram localizados?|nao ha|inexistentes?)\b",
            normalized,
        )
    )
    service_result = evidence.get("consultar_servicos")
    if (service_query_claim or service_absence_claim) and service_result is None:
        raise ValueError("A resposta alegou consulta de servico sem evidencia desta solicitacao.")
    if (service_query_claim or service_absence_claim) and service_result is not None and service_result.state == "failed":
        raise ValueError("Uma consulta de servico que falhou nao pode ser descrita como bem-sucedida.")
    if service_absence_claim and service_result is not None:
        count = service_result.payload.get("count")
        if isinstance(count, int) and count > 0:
            raise ValueError("A resposta descreveu a consulta de servicos como vazia, mas foram encontrados registros.")

    service_registration_claim = _positive_claim(
        normalized,
        (
            r"\b(?:registrei|cadastrei|salvei|criei|lancei)\b.{0,70}\b(?:servicos?|chamados?|atendimentos?|visitas?|inspecoes?|eventos?)\b",
            r"\b(?:servicos?|chamados?|atendimentos?|visitas?|inspecoes?|eventos?)\b"
            r".{0,50}\b(?:foi|foram)\s+(?:registrad[oa]s?|cadastrad[oa]s?|salv[oa]s?|criad[oa]s?|lancad[oa]s?)\b",
            r"\b(?:servicos?|chamados?|atendimentos?|execucoes?)\b"
            r".{0,45}\b(?:foi|foram)\s+(?:concluid[oa]s?|finalizad[oa]s?)\b",
            r"\b(?:conclui|finalizei)\b.{0,70}\b(?:servicos?|chamados?|atendimentos?|execucoes?)\b",
        ),
    )
    if service_registration_claim:
        raise ValueError("A resposta alegou registro de servico sem resultado confirmado.")

    unsupported_action_patterns = (
        r"\b(?:marquei|registrei|lancei)\b.{0,50}\b(?:conta|pagamento|financeiro)\b",
        r"\b(?:emiti|gerei)\b.{0,50}\b(?:nota fiscal|nf ?e)\b",
        r"\b(?:enviei|encaminhei)\b.{0,50}\b(?:e[- ]?mail|mensagem)\b",
        r"\b(?:alterei|atualizei|salvei)\b.{0,50}\b(?:documento|relatorio|proposta)\b",
        r"\b(?:executei)\b.{0,50}\b(?:servico|atendimento)\b",
        r"\b(?:conferi|consultei|verifiquei|revisei)\b.{0,50}\b(?:financeiro|cobrancas?|documentos?|relatorios?)\b",
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
