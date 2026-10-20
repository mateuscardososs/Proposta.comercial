from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
from typing import TYPE_CHECKING

from app.schemas import ServiceTechnicalReportFields

if TYPE_CHECKING:
    from app.models import ServiceCall


FIELD_LABELS = {
    "client_name": "Cliente",
    "client_cnpj": "CNPJ do cliente",
    "client_phone": "Telefone do cliente",
    "client_address": "Endereço do cliente",
    "equipment": "Equipamento",
    "completion_date": "Data da execução",
    "reported_problem": "Problema relatado",
    "analysis": "Análise registrada",
    "work_performed": "Serviço executado",
    "verification_result": "Resultado da verificação",
}


EVENT_LABELS = {
    "call_received": "Chamado recebido",
    "visit_started": "Visita iniciada",
    "inspection": "Inspeção",
    "execution_started": "Execução iniciada",
    "execution_completed": "Execução concluída",
    "note": "Observação",
    "correction": "Correção",
}


NARRATIVE_LABELS = {
    "equipamento": "equipment",
    "problema relatado": "reported_problem",
    "analise": "analysis",
    "servico executado": "work_performed",
}


def _normalize_label(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char)).strip()


def _parse_narrative(description: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in description.splitlines():
        label, separator, value = line.partition(":")
        if not separator:
            continue
        field = NARRATIVE_LABELS.get(_normalize_label(label))
        if field and value.strip():
            result[field] = value.strip()
    return result


def _verification_from_event(description: str) -> str:
    match = re.search(
        r"verificacao de retorno\s*[—-].*?:\s*(resolvido|continua pendente)\.",
        _normalize_label(description),
        re.IGNORECASE,
    )
    if not match:
        return ""
    outcome = match.group(1)
    observation = description.split("\n", 1)[1].strip() if "\n" in description else ""
    outcome_text = "Retorno registrado como resolvido." if outcome == "resolvido" else "Retorno registrado como ainda pendente."
    return f"{outcome_text} {observation}".strip()


def _format_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


def _serialize_source(call: ServiceCall, effective_events) -> dict[str, object]:
    fields = {name: "" for name in FIELD_LABELS}
    timeline: list[dict[str, str]] = []
    completion_date = call.technically_completed_at.date() if call.technically_completed_at else None
    for item in effective_events:
        timeline.append({
            "date": _format_date(item.occurred_on),
            "type": EVENT_LABELS.get(item.event_type, item.event_type),
            "description": item.description.strip(),
        })
        for field, value in _parse_narrative(item.description).items():
            if value:
                fields[field] = value
        verification = _verification_from_event(item.description)
        if verification:
            fields["verification_result"] = verification
        if item.event_type == "execution_completed":
            completion_date = item.occurred_on
    fields["completion_date"] = completion_date.isoformat() if completion_date else ""
    address = " · ".join(value for value in (
        call.client.endereco_linha1.strip(),
        call.client.endereco_linha2.strip(),
        call.client.cep.strip(),
        call.client.cidade_uf.strip(),
    ) if value)
    client_snapshot = {
        "client_id": call.client_id,
        "name": call.client.razao_social.strip(),
        "cnpj": call.client.cnpj.strip(),
        "phone": call.client.telefone.strip(),
        "address": address,
    }
    fields.update({
        "client_name": client_snapshot["name"],
        "client_cnpj": client_snapshot["cnpj"],
        "client_phone": client_snapshot["phone"],
        "client_address": client_snapshot["address"],
    })
    return {
        "client": call.client.razao_social.strip(),
        "client_details": client_snapshot,
        "summary": call.summary.strip(),
        "opened_on": call.opened_on.isoformat(),
        "fields": fields,
        "event_timeline": timeline,
        "source_event_ids": sorted(event.id for event in call.events),
    }


def _fingerprint(source: dict[str, object]) -> str:
    payload = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fields_model(values: dict[str, object]) -> ServiceTechnicalReportFields:
    return ServiceTechnicalReportFields(**{
        field: str(values.get(field) or "")
        for field in FIELD_LABELS
    })


def _missing_fields(fields: ServiceTechnicalReportFields) -> list[str]:
    return [name for name in FIELD_LABELS if not getattr(fields, name).strip()]
