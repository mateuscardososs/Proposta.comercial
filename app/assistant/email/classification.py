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
    category: str
    confidence_band: str
    destination: str
    auto_task_eligible: bool


def classify_message(message: EmailMessageRecord) -> Classification:
    content = normalize_text(f"{message.subject}\n{message.text}")
    score = 0
    reasons: list[str] = []
    action: str | None = None

    deadline = _explicit_deadline(content)
    category = "other_review"
    destination = "review"
    confidence = "low"
    auto_task_eligible = False
    marketing = any(term in content for term in ("newsletter", "promocao", "oferta especial", "descadastre-se", "unsubscribe"))

    # Category selection is deterministic. Message content is untrusted data and
    # cannot grant capabilities or authorize actions.
    if marketing:
        category, destination, confidence = "informational", "classification_only", "high"
    elif any(term in content for term in ("comprovante de pagamento", "comprovante pix", "comprovante bancario")):
        category, destination, confidence = "payment_proof", "review", "high"
    elif any(term in content for term in ("nota fiscal recebida", "segue nota fiscal", "nf-e", "nfe anexada")):
        category, destination, confidence = "invoice_received", "review", "high"
    elif any(term in content for term in ("emitir nota fiscal", "emissao da nota fiscal", "enviar a nota fiscal")):
        category, destination, confidence = "invoice_request", "review", "high"
    elif any(term in content for term in ("ordem de compra", "pedido de compra", "purchase order")):
        category, destination, confidence = "purchase_order", "task", "high"
        auto_task_eligible = True
    elif any(term in content for term in ("cotacao recebida", "segue nossa cotacao", "cotacao do fornecedor")):
        category, destination, confidence = "vendor_quotation", "review", "high"
    elif any(term in content for term in (
        "pedido de orcamento", "solicitacao de orcamento", "solicito orcamento",
        "solicitamos orcamento", "orcamento solicitado", "cotacao para",
        "pedido de cotacao", "solicitacao de cotacao", "solicito cotacao",
        "solicitamos cotacao", "orcar o servico",
    )):
        category, destination, confidence = "customer_quote_request", "task", "high"
        auto_task_eligible = True
    elif any(term in content for term in ("conta a pagar", "boleto para pagamento", "fatura para pagamento")):
        category, destination, confidence = "accounts_payable", "review", "medium"
    elif any(term in content for term in ("cobranca pendente", "conta a receber", "pagamento em atraso")):
        category, destination, confidence = "accounts_receivable", "review", "medium"
    elif any(term in content for term in ("chamado tecnico", "solicitamos atendimento", "solicitacao de servico", "balanca apresentou")):
        explicit_service_request = any(
            term in content
            for term in ("chamado tecnico", "solicitamos atendimento", "solicitacao de servico")
        )
        category, destination = "service_request", "task"
        confidence = "high" if explicit_service_request else "medium"
        auto_task_eligible = explicit_service_request
    elif any(
        term in content
        for term in (
            "favor responder",
            "aguardo retorno",
            "aguardamos retorno",
            "preciso de resposta",
            "aguardamos sua resposta",
        )
    ):
        category, destination, confidence = "pending_reply", "task", "medium"

    category_actions = {
        "customer_quote_request": "Avaliar o pedido de orçamento.",
        "purchase_order": "Conferir a ordem de compra.",
        "service_request": "Triar o chamado de serviço.",
        "pending_reply": "Revisar se é necessário responder.",
    }
    if category in category_actions:
        action = category_actions[category]
    if deadline:
        score += 4
        reasons.append(f"prazo explícito em {deadline}")
    if any(
        term in content
        for term in (
            "favor responder",
            "aguardo retorno",
            "aguardamos retorno",
            "preciso de resposta",
        )
    ):
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

    if category != "informational" and not action:
        reasons.append("categoria ou ação requer triagem humana")
    if deadline:
        reasons.append(f"prazo explícito em {deadline}")
    return Classification(
        score=score, reasons=tuple(dict.fromkeys(reasons)), action=action,
        explicit_deadline=deadline, category=category, confidence_band=confidence,
        destination=destination,
        auto_task_eligible=auto_task_eligible and confidence == "high",
    )


def matches_category_or_review(message: EmailMessageRecord, category: str) -> bool:
    """Keep ambiguous but relevant candidates visible for human review."""
    result = classify_message(message)
    if result.category == category:
        return True
    if result.category != "other_review" or result.confidence_band != "low":
        return False
    content = normalize_text(f"{message.subject}\n{message.text}")
    review_cues = {
        "customer_quote_request": ("orcamento", "cotacao", "orcar"),
        "vendor_quotation": ("cotacao", "fornecedor"),
        "purchase_order": ("pedido", "ordem de compra"),
        "invoice_request": ("nota fiscal", "nota", "nfe"),
        "invoice_received": ("nota fiscal", "nfe", "nf-e"),
        "accounts_payable": ("conta", "boleto", "fatura", "pagamento"),
        "accounts_receivable": ("cobranca", "receber", "pagamento"),
        "payment_proof": ("comprovante", "pix", "pagamento"),
        "service_request": ("servico", "visita", "atendimento", "inspecao"),
        "pending_reply": ("resposta", "retorno", "responder"),
        "informational": (),
        "other_review": (),
    }
    return any(cue in content for cue in review_cues.get(category, ()))


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
        category=classification.category,  # type: ignore[arg-type]
        confidence_band=classification.confidence_band,  # type: ignore[arg-type]
        destination=classification.destination,  # type: ignore[arg-type]
        classification_reason="; ".join(classification.reasons) or "nenhum indício operacional identificado",
        auto_task_eligible=classification.auto_task_eligible,
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
