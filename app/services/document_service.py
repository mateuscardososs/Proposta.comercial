from __future__ import annotations

from pathlib import Path

from docxtpl import DocxTemplate

from app.models import Proposal
from app.utils.currency import format_brl, format_decimal_br
from app.utils.dates import format_date_br
from app.utils.formatters import build_client_block


OBJETO_LABELS = {
    "manutencao_calibracao": "Manutencao e calibracao",
    "troca_pecas": "Troca de pecas",
    "outro": "Outro",
}


def _resolve_objeto_texto(proposal: Proposal) -> str:
    if proposal.objeto_tipo == "outro":
        return proposal.objeto_texto or "Outro servico"
    if proposal.objeto_texto.strip():
        return proposal.objeto_texto
    return OBJETO_LABELS.get(proposal.objeto_tipo, proposal.objeto_tipo)


def _format_horas_servico(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if "hora" in text.lower():
        return text
    return f"{text} horas de servico"


def _split_name_and_role(raw: str) -> tuple[str, str]:
    value = raw.strip()
    for separator in (" / ", "/", " - ", " – ", " — "):
        if separator in value:
            left, right = value.split(separator, 1)
            left = left.strip()
            right = right.strip()
            if left and right:
                return left, right
    return value, ""


def _resolve_client_responsavel(proposal: Proposal) -> tuple[str, str]:
    for candidate in (
        proposal.contato_nome,
        proposal.atencao,
        proposal.client.contato_padrao,
    ):
        text = str(candidate or "").strip()
        if text:
            return _split_name_and_role(text)
    return "", ""


def build_template_context(proposal: Proposal) -> dict[str, object]:
    item_rows = [
        {
            "descricao": item.descricao,
            "unidade": item.unidade,
            "qtd": format_decimal_br(item.qtd),
            "valor_unit": format_brl(item.valor_unit),
            "total": format_brl(item.total),
        }
        for item in proposal.items
    ]
    cronograma_rows = [
        {
            "dia": etapa.dia_label,
            "descricao": etapa.descricao,
            "horas": _format_horas_servico(etapa.horas_servico),
        }
        for etapa in proposal.schedule_items
    ]
    responsavel_nome, responsavel_cargo = _resolve_client_responsavel(proposal)

    return {
        "NUMERO": proposal.numero,
        "REV": proposal.revisao,
        "DATA": format_date_br(proposal.data_geracao),
        "CLIENTE_RAZAO": proposal.client.razao_social,
        "ATENCAO": proposal.atencao or proposal.client.contato_padrao,
        "RESPONSAVEL_NOME": responsavel_nome,
        "RESPONSAVEL_CARGO": responsavel_cargo,
        "REF_CLIENTE": proposal.ref_cliente,
        "OBJETO_TEXTO": _resolve_objeto_texto(proposal),
        "CANAL": proposal.canal,
        "CONTATO_NOME": proposal.contato_nome,
        "CONTATO_DATAHORA": proposal.contato_datahora,
        "CLIENTE_BLOCO": build_client_block(proposal.client),
        "EQUIPAMENTO_NOME": proposal.equipamento_nome,
        "EQUIPAMENTO_TEXTO": proposal.equipamento_texto,
        "LOCAL_SERVICO": proposal.local_servico,
        "KM_TOTAL": format_decimal_br(proposal.km_total),
        "KM_VALOR": format_brl(proposal.km_valor),
        "DESLOC_TOTAL": format_brl(proposal.desloc_total),
        "ALIM_TECNICOS": proposal.alim_tecnicos,
        "ALIM_REFEICOES": proposal.alim_refeicoes,
        "ALIM_VALOR": format_brl(proposal.alim_valor),
        "ALIM_TOTAL": format_brl(proposal.alim_total),
        "CONDICAO_PAGAMENTO": f"{proposal.condicao_pagamento_dias} dias",
        "IMPOSTO": f"{format_decimal_br(proposal.imposto_percentual)}%",
        "VALOR_TOTAL": format_brl(proposal.valor_total),
        "ITENS": item_rows,
        "CRONOGRAMA": cronograma_rows,
    }


def render_docx_from_template(template_path: Path, context: dict[str, object], output_path: Path) -> Path:
    if not template_path.exists():
        raise FileNotFoundError(f"Word template not found: {template_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = DocxTemplate(str(template_path))
    document.render(context)
    document.save(str(output_path))
    return output_path
