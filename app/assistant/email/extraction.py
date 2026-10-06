from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from app.assistant.dates import normalize_text
from app.assistant.email.contracts import EmailCategory, EmailMessageRecord

_DATE = r"(\d{1,2}/\d{1,2}/\d{4})"
_MONEY = re.compile(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{1,2})?|[0-9]+(?:,[0-9]{1,2})?)", re.IGNORECASE)
_DUE = re.compile(rf"\b(?:vencimento|venc\.?|vence|vencer[aá]?)\s*(?:em|:|dia)?\s*{_DATE}", re.IGNORECASE)
_ISSUE = re.compile(rf"\b(?:emitid[ao]s?\s+em|emiss[aã]o\s+em|data\s+de\s+emiss[aã]o\s*:?)\s*{_DATE}", re.IGNORECASE)
_QUOTE_DEADLINE = re.compile(rf"\b(?:prazo\s+(?:de\s+resposta|para\s+responder)|responder\s+at[eé])\s*(?:at[eé]|em|:)?\s*{_DATE}", re.IGNORECASE)
_PARTY = re.compile(r"\b(fornecedor|empresa|cliente)\s*[:\-]?\s*([^,;.\n]{2,80})", re.IGNORECASE)
_INVOICE = re.compile(
    r"\b(?:nota\s+fiscal|nf-e|nfe)\s*(?:n[ºo°.]?\s*)?(?:n[uú]mero\s*)?(?:[:#-]\s*)?([A-Z0-9][A-Z0-9./-]{2,39})",
    re.IGNORECASE,
)
_INVOICE_FALSE_POSITIVES = {"recebida", "recebido", "anexa", "anexada", "enviada", "enviado", "emitida", "emitido"}


def extract_operational_fields(
    message: EmailMessageRecord,
    category: EmailCategory,
) -> dict[str, object]:
    """Extract only explicit, structured values; never retain source-body fragments."""
    source = f"{message.subject}\n{message.text}"
    evidence: list[str] = []
    uncertainty: list[str] = []
    missing: list[str] = []

    party_matches = list(_PARTY.finditer(source))
    party_name: str | None = None
    party_role: str | None = None
    parties = {
        (" ".join(normalize_text(name).split()), name, label.casefold())
        for label, raw_name in (match.groups() for match in party_matches)
        if (name := _clean_name(raw_name))
    }
    if parties:
        longest = max(parties, key=lambda item: len(item[0].split()))
        longest_tokens = set(longest[0].split())
        if all(set(item[0].split()).issubset(longest_tokens) for item in parties):
            party_name = longest[1]
            party_role = "supplier" if category in {"accounts_payable", "invoice_received", "vendor_quotation"} or longest[2] == "fornecedor" else "client"
            evidence.append("supplier_label" if party_role == "supplier" else "client_label")
        else:
            uncertainty.append("Mais de uma empresa foi citada; a contraparte não foi escolhida automaticamente.")

    amount_matches = list(_MONEY.finditer(source))
    amount: str | None = None
    if len(amount_matches) == 1:
        try:
            parsed_amount = Decimal(amount_matches[0].group(1).replace(".", "").replace(",", "."))
            if parsed_amount > 0:
                amount = format(parsed_amount.quantize(Decimal("0.01")), ".2f")
                evidence.append("currency_amount")
        except InvalidOperation:
            uncertainty.append("O valor monetário não pôde ser interpretado com segurança.")
    elif len(amount_matches) > 1:
        uncertainty.append("Mais de um valor monetário explícito; escolha o valor correto na revisão.")

    due_matches = list(_DUE.finditer(source))
    if category == "customer_quote_request":
        due_matches = list(_QUOTE_DEADLINE.finditer(source))
    due_date = _one_date(due_matches, evidence, uncertainty, "payment_due_date" if category != "customer_quote_request" else "quote_response_deadline")

    issue_matches = list(_ISSUE.finditer(source))
    issue_date = _one_date(issue_matches, evidence, uncertainty, "issue_date")

    invoice_matches = [
        match.group(1).strip("./-")
        for match in _INVOICE.finditer(source)
        if match.group(1).casefold() not in _INVOICE_FALSE_POSITIVES
    ]
    invoice_number: str | None = None
    if len(set(invoice_matches)) == 1:
        invoice_number = invoice_matches[0][:40]
        evidence.append("invoice_number")
    elif len(set(invoice_matches)) > 1:
        uncertainty.append("Mais de um número de nota foi identificado; nenhum foi escolhido.")

    if category == "customer_quote_request":
        if party_name is None:
            missing.append("cliente/empresa")
        if due_date is None:
            missing.append("prazo de resposta")
        if party_role is not None:
            party_role = "client"
    elif category in {"accounts_payable", "invoice_received", "vendor_quotation"}:
        if party_name is None:
            missing.append("fornecedor")
        if amount is None:
            missing.append("valor")
        if due_date is None:
            missing.append("vencimento")
        if category != "vendor_quotation" and issue_date is None:
            missing.append("data de emissão")
        if category != "vendor_quotation" and invoice_number is None:
            missing.append("número da nota")
        if category != "customer_quote_request":
            party_role = "supplier"

    return {
        "party_name": party_name,
        "party_role": party_role,
        "amount": amount,
        "due_date": due_date.isoformat() if due_date else None,
        "issue_date": issue_date.isoformat() if issue_date else None,
        "invoice_number": invoice_number,
        "missing_fields": list(dict.fromkeys(missing)),
        "uncertainty": list(dict.fromkeys(uncertainty)),
        "evidence": list(dict.fromkeys(evidence)),
    }


def _one_date(matches: list[re.Match[str]], evidence: list[str], uncertainty: list[str], evidence_key: str) -> date | None:
    parsed: set[date] = set()
    for match in matches:
        day, month, year = (int(part) for part in match.group(1).split("/"))
        try:
            parsed.add(date(year, month, day))
        except ValueError:
            uncertainty.append("Uma data explícita está inválida e precisa de revisão.")
    if len(parsed) == 1:
        evidence.append(evidence_key)
        return next(iter(parsed))
    if len(parsed) > 1:
        uncertainty.append("Mais de uma data aplicável foi encontrada; nenhuma foi escolhida.")
    return None


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.strip().split()).strip(" :-")
    cleaned = re.split(
        r"\s+(?:at[eé]|vencimento|vence|solicita(?:mos)?|solicitou|informa(?:mos)?|para pagamento)\b",
        cleaned,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" :-")
    if not cleaned or cleaned.casefold() in {"a identificar", "não informado", "nao informado"}:
        return ""
    return cleaned[:80]
