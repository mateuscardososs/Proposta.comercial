from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.assistant.dates import normalize_text
from app.assistant.email.contracts import EmailMessageRecord, EmailMessageResult
from app.assistant.email.extraction import extract_operational_fields


@dataclass(frozen=True)
class Classification:
    score: int
    priority: str
    reasons: tuple[str, ...]
    action: str | None
    explicit_deadline: str | None
    category: str
    confidence_band: str
    destination: str
    auto_task_eligible: bool


OPERATIONAL_CATEGORIES = frozenset(
    {
        "customer_quote_request",
        "vendor_quotation",
        "purchase_order",
        "invoice_request",
        "invoice_received",
        "accounts_payable",
        "accounts_receivable",
        "payment_proof",
        "service_request",
        "pending_reply",
    }
)

AUTO_TASK_CATEGORIES = frozenset(
    {"customer_quote_request", "purchase_order", "service_request"}
)
REPLY_REQUEST_PHRASES = (
    "favor responder",
    "aguardo retorno",
    "aguardamos retorno",
    "preciso de resposta",
    "aguardamos sua resposta",
    "favor nos retornar",
    "aguardo sua resposta",
)


def message_queue(category: str, confidence_band: str) -> str:
    """Keep clearly irrelevant mail apart from operational work and uncertain items."""
    if category == "informational":
        return "informational"
    if category in OPERATIONAL_CATEGORIES and confidence_band in {"medium", "high"}:
        return "operational"
    return "review"


def result_order_key(message: EmailMessageResult) -> tuple[int, int, float]:
    bucket_rank = {"operational": 0, "review": 1, "informational": 2}
    priority_rank = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    return (
        bucket_rank[message_queue(message.category, message.confidence_band)],
        priority_rank[message.priority],
        -message.received_at.timestamp(),
    )


def requests_reply(message: EmailMessageRecord) -> bool:
    """Detect an explicit request for a reply independently of its main category."""
    content = normalize_text(f"{message.subject}\n{message.text}")
    return _first_match(content, REPLY_REQUEST_PHRASES) is not None


def classify_message(message: EmailMessageRecord) -> Classification:
    content = normalize_text(f"{message.subject}\n{message.text}")
    deadline = _explicit_deadline(content)
    category, destination, confidence, evidence = _classify_category(content)
    action = _category_action(category)
    reasons = [evidence]

    urgency = _first_match(
        content,
        (
            "prioridade maxima",
            "com urgencia",
            "urgente",
            "imediatamente",
            "ate hoje",
            "ate amanha",
            "ate sexta",
            "vence hoje",
            "vence amanha",
            "vencimento hoje",
            "vencimento amanha",
            "data limite",
            "prazo final",
        ),
    )
    impact = _first_match(
        content,
        (
            "producao parada",
            "producao interrompida",
            "linha parada",
            "balanca parada",
            "balanca sem funcionar",
            "equipamento parado",
            "equipamento sem funcionar",
            "equipamento fora de operacao",
            "equipamento indisponivel",
            "balanca indisponivel",
        ),
    )
    explicit_priority_signal = bool(deadline or urgency or impact)
    if category not in OPERATIONAL_CATEGORIES:
        explicit_priority_signal = False
    if deadline:
        reasons.append(f"prazo explícito em {deadline}")
    elif urgency:
        reasons.append(f"urgência explícita no texto: {urgency}")
    if impact:
        reasons.append(f"impacto operacional explícito no texto: {impact}")

    priority = "high" if explicit_priority_signal else (
        "normal" if category in OPERATIONAL_CATEGORIES else "low"
    )
    score = 4 if priority == "high" else (1 if priority == "normal" else 0)
    if category in {"other_review", "informational"} and action is None:
        action = None
    auto_task_eligible = (
        category in AUTO_TASK_CATEGORIES
        and confidence == "high"
        and destination == "task"
    )
    return Classification(
        score=score, priority=priority, reasons=tuple(dict.fromkeys(reasons)), action=action,
        explicit_deadline=deadline, category=category, confidence_band=confidence,
        destination=destination,
        auto_task_eligible=auto_task_eligible,
    )


def _classify_category(content: str) -> tuple[str, str, str, str]:
    """Classify only from explicit subject/body markers; untrusted text grants no action."""
    rules: tuple[tuple[str, tuple[str, ...], str, str, str], ...] = (
        (
            "payment_proof",
            ("comprovante de pagamento", "comprovante pix", "comprovante bancario", "pagamento confirmado"),
            "review",
            "high",
            "comprovante ou confirmação de pagamento",
        ),
        (
            "invoice_request",
            ("solicito emissao de nota fiscal", "solicitamos emissao de nota fiscal", "solicitacao para emissao da nota fiscal", "solicitacao de enviar nota fiscal", "solicita emissao de nota fiscal", "emitir nota fiscal", "emissao da nota fiscal", "enviar a nota fiscal", "solicito a nota fiscal", "solicitamos a nota fiscal"),
            "review",
            "high",
            "pedido explícito de emissão ou envio de nota fiscal",
        ),
        (
            "invoice_received",
            ("nota fiscal recebida", "recebemos a nota fiscal", "recebi a nota fiscal", "segue nota fiscal", "segue a nota fiscal", "anexo nota fiscal", "nf-e anexada", "nfe anexada", "encaminho nf-e", "encaminho nfe"),
            "review",
            "high",
            "nota fiscal recebida ou anexada",
        ),
        (
            "purchase_order",
            ("ordem de compra", "pedido de compra", "purchase order", "ordem de compra emitida"),
            "task",
            "high",
            "pedido ou ordem de compra explícita",
        ),
        (
            "vendor_quotation",
            ("cotacao recebida", "cotacao recebida do fornecedor", "orcamento recebido do fornecedor", "segue nossa cotacao", "segue a cotacao do fornecedor", "cotacao do fornecedor", "fornecedor enviou cotacao", "encaminho cotacao solicitada", "segue nosso orcamento"),
            "review",
            "high",
            "cotação enviada por fornecedor",
        ),
        (
            "customer_quote_request",
            ("pedido de orcamento", "solicitacao de orcamento", "solicito orcamento", "solicitamos orcamento", "favor enviar orcamento", "precisamos de orcamento", "orcamento para o servico", "pedido de cotacao", "solicitacao de cotacao", "solicito cotacao", "solicitamos cotacao", "favor cotar", "orcar o servico"),
            "task",
            "high",
            "pedido de orçamento/cotação feito pelo cliente",
        ),
        (
            "accounts_payable",
            ("conta a pagar", "boleto para pagamento", "boleto vence", "fatura para pagamento", "fatura do fornecedor", "pagamento ao fornecedor", "vencimento do boleto"),
            "review",
            "medium",
            "cobrança, boleto ou conta a pagar de fornecedor",
        ),
        (
            "accounts_receivable",
            ("conta a receber", "cobranca pendente", "cobranca ao cliente", "cobrar do cliente", "pagamento em atraso", "valor a receber"),
            "review",
            "medium",
            "cobrança ou valor a receber",
        ),
        (
            "service_request",
            ("chamado tecnico", "solicitamos atendimento", "solicito atendimento", "solicitacao de servico", "solicito visita tecnica", "solicitamos visita tecnica", "servico tecnico solicitado"),
            "task",
            "high",
            "solicitação explícita de atendimento ou serviço técnico",
        ),
        (
            "pending_reply",
            ("favor responder", "aguardo retorno", "aguardamos retorno", "preciso de resposta", "aguardamos sua resposta", "favor nos retornar", "aguardo sua resposta"),
            "task",
            "high",
            "pedido explícito de resposta/retorno",
        ),
    )
    marketing = _first_match(
        content,
        ("newsletter", "promocao", "oferta especial", "desconto exclusivo", "descadastre-se", "unsubscribe", "campanha promocional"),
    )
    if marketing:
        operational_signal = next(
            (
                match
                for _, phrases, _, _, _ in rules
                if (match := _first_match(content, phrases))
            ),
            None,
        )
        if operational_signal:
            return (
                "other_review",
                "review",
                "low",
                f"Sinais promocionais e operacionais coexistem (marcadores: {marketing}; {operational_signal}); revisar sem criação automática.",
            )
        return (
            "informational",
            "classification_only",
            "high",
            f"Conteúdo promocional (sinal: {marketing}); sem ação operacional explícita.",
        )

    for category, phrases, destination, confidence, description in rules:
        if match := _first_match(content, phrases):
            return category, destination, confidence, f"Evidência: {description} (sinal: {match})."

    technical_issue = _first_match(
        content,
        ("balanca apresentou", "balanca parada", "balanca indisponivel", "falha na balanca", "equipamento apresentou falha", "manutencao preventiva"),
    )
    if technical_issue:
        return (
            "service_request",
            "task",
            "medium",
            f"Possível necessidade de serviço técnico, ainda sem pedido explícito (sinal: {technical_issue}); revisar.",
        )

    non_operational = _first_match(
        content,
        (
            "pedido de casamento", "convite para casamento", "feliz aniversario",
            "viagem em familia", "fotos do fim de semana", "convite para festa",
            "aviso automatico", "notificacao automatica", "nao responda", "do not reply",
        ),
    )
    if non_operational:
        return "informational", "classification_only", "high", f"Conteúdo informativo/pessoal sem ação comercial (sinal: {non_operational})."

    operational_ambiguity = _first_match(
        content,
        (
            "orcamento", "cotacao", "proposta", "ordem de compra", "pedido de compra",
            "boleto", "fatura", "conta a pagar", "pagamento", "cobranca", "nota fiscal",
            "nf-e", "nfe", "comprovante", "balanca", "calibracao", "manutencao",
            "servico", "atendimento", "visita tecnica", "inspecao", "resposta", "retorno",
        ),
    )
    generic_action = _first_match(
        content,
        ("poderia enviar", "favor enviar", "aguardo", "preciso de", "solicitado", "solicitacao", "pedido"),
    )
    if operational_ambiguity or generic_action:
        marker = operational_ambiguity or generic_action
        return (
            "other_review",
            "review",
            "low",
            f"Indício sem contexto suficiente para classificar ou agir (sinal: {marker}); revisar.",
        )

    return (
        "informational",
        "classification_only",
        "medium",
        "Nenhum marcador operacional identificado no assunto ou no resumo disponível; separado em Informativos/outros.",
    )


def _category_action(category: str) -> str | None:
    return {
        "customer_quote_request": "Avaliar o pedido de orçamento.",
        "vendor_quotation": "Conferir a cotação recebida do fornecedor.",
        "purchase_order": "Conferir a ordem de compra.",
        "invoice_request": "Conferir a solicitação de nota fiscal.",
        "invoice_received": "Conferir a nota fiscal recebida.",
        "accounts_payable": "Conferir a conta a pagar.",
        "accounts_receivable": "Conferir a cobrança ou conta a receber.",
        "payment_proof": "Conferir o comprovante de pagamento.",
        "service_request": "Triar o chamado de serviço.",
        "pending_reply": "Verificar se é necessário responder.",
    }.get(category)


def _first_match(content: str, phrases: tuple[str, ...]) -> str | None:
    return next((phrase for phrase in phrases if phrase in content), None)


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
        priority=classification.priority,  # type: ignore[arg-type]
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
        extracted_fields=extract_operational_fields(message, classification.category),
    )


def _explicit_deadline(content: str) -> str | None:
    match = re.search(r"\b([0-3]?\d)/([01]?\d)/(20\d{2})\b", content)
    if not match:
        return None
    context = content[max(0, match.start() - 24) : match.end() + 16]
    if not re.search(r"\b(ate|prazo|vencimento|vence|vencer|data limite)\b", context):
        return None
    day, month, year = (int(value) for value in match.groups())
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    return parsed.strftime("%d/%m/%Y")
