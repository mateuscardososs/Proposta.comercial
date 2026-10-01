from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.assistant.dates import normalize_text
from app.assistant.email.contracts import EmailMessageRecord, EmailMessageResult


@dataclass(frozen=True)
class Classification:
    score: int
    reasons: tuple[str, ...]
    action: str | None
    explicit_deadline: str | None


def classify_message(message: EmailMessageRecord) -> Classification:
    content = normalize_text(f"{message.subject}\n{message.text}")
    score = 0
    reasons: list[str] = []
    action: str | None = None

    deadline = _explicit_deadline(content)
    if deadline:
        score += 4
        reasons.append(f"prazo explícito em {deadline}")
    if any(term in content for term in ("favor responder", "aguardo retorno", "preciso de resposta")):
        score += 3
        reasons.append("solicita resposta")
        action = "Responder ao remetente."
    if any(term in content for term in ("orcamento", "proposta comercial", "cotacao")):
        score += 2
        reasons.append("pedido de orçamento ou proposta")
        action = action or "Avaliar o pedido comercial."
    if any(term in content for term in ("autorizo", "autorizacao", "aprovado")):
        score += 3
        reasons.append("contém autorização")
        action = action or "Conferir a autorização recebida."
    if any(term in content for term in ("servico", "inspecao", "manutencao")) and deadline:
        score += 2
        reasons.append("serviço associado a prazo")
        action = action or "Avaliar o serviço solicitado."
    if any(term in content for term in ("cobranca", "vencido", "fatura")):
        score += 2
        reasons.append("assunto de cobrança")
        action = action or "Revisar a cobrança."
    marketing = any(
        term in content
        for term in ("newsletter", "promocao", "oferta especial", "descadastre-se", "unsubscribe")
    )
    if marketing:
        score -= 5
        reasons = ["conteúdo promocional sem pedido operacional identificado"]
        action = None
    if not message.seen and not marketing:
        score += 1
        reasons.append("não lido no servidor")

    return Classification(score=score, reasons=tuple(reasons), action=action, explicit_deadline=deadline)


def to_result(
    message: EmailMessageRecord,
    *,
    awaiting_reply: str = "unknown",
    limitations: list[str] | None = None,
) -> EmailMessageResult:
    classification = classify_message(message)
    priority = (
        "critical" if classification.score >= 7 else
        "high" if classification.score >= 4 else
        "normal" if classification.score >= 1 else
        "low"
    )
    clean_text = " ".join(message.text.split())
    summary = clean_text[:280].rstrip()
    if len(clean_text) > 280:
        summary += "…"
    if not summary:
        summary = message.subject
    return EmailMessageResult(
        reference=message.reference,
        sender=message.sender,
        subject=message.subject,
        received_at=message.received_at,
        seen=message.seen,
        summary=summary,
        priority=priority,
        priority_reason="; ".join(classification.reasons) or "nenhum indício de prioridade identificado",
        action_suggested=classification.action,
        explicit_deadline=classification.explicit_deadline,
        awaiting_reply=awaiting_reply,  # type: ignore[arg-type]
        evidence=list(classification.reasons),
        limitations=limitations or [],
    )


def _explicit_deadline(content: str) -> str | None:
    match = re.search(r"\b([0-3]?\d)/([01]?\d)/(20\d{2})\b", content)
    if not match:
        return None
    day, month, year = (int(value) for value in match.groups())
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    return parsed.strftime("%d/%m/%Y")

