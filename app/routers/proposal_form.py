"""Pure proposal form parsing and prefill preparation."""
from __future__ import annotations

from decimal import Decimal

from starlette.datastructures import FormData

from app.models import Proposal
from app.schemas import ProposalCreate, ProposalItemCreate, ScheduleItemCreate
from app.utils.formatters import decimal_from_str


def default_form_data(*, default_km_value: Decimal) -> dict[str, object]:
    return {
        "client_id": "",
        "user_id": "",
        "atencao": "",
        "ref_cliente": "",
        "objeto_tipo": "manutencao_calibracao",
        "objeto_texto": "",
        "canal": "",
        "contato_nome": "",
        "contato_datahora": "",
        "equipamento_nome": "",
        "equipamento_texto": "",
        "local_servico": "",
        "km_ida": "0",
        "km_volta": "0",
        "km_valor": str(default_km_value),
        "alim_tecnicos": "1",
        "alim_refeicoes": "0",
        "alim_valor": "0",
        "condicao_pagamento_dias": "0",
        "imposto_percentual": "0",
        "itens": [{"descricao": "", "unidade": "UN", "qtd": "1", "valor_unit": "0"}],
        "schedule_items": [{"dia_label": "", "descricao": "", "horas_servico": ""}],
    }


def prefill_from_last(last: Proposal, fallback: dict[str, object]) -> dict[str, object]:
    prefill = dict(fallback)
    prefill.update(
        {
            "client_id": str(last.client_id),
            "user_id": str(last.user_id),
            "atencao": last.atencao,
            "ref_cliente": last.ref_cliente,
            "objeto_tipo": last.objeto_tipo,
            "objeto_texto": last.objeto_texto,
            "canal": last.canal,
            "contato_nome": last.contato_nome,
            "contato_datahora": last.contato_datahora,
            "equipamento_nome": last.equipamento_nome,
            "equipamento_texto": last.equipamento_texto,
            "local_servico": last.local_servico,
            "km_ida": str(last.km_ida),
            "km_volta": str(last.km_volta),
            "km_valor": str(last.km_valor),
            "alim_tecnicos": str(last.alim_tecnicos),
            "alim_refeicoes": str(last.alim_refeicoes),
            "alim_valor": str(last.alim_valor),
            "condicao_pagamento_dias": str(last.condicao_pagamento_dias),
            "imposto_percentual": str(last.imposto_percentual),
            "itens": [
                {
                    "descricao": item.descricao,
                    "unidade": item.unidade,
                    "qtd": str(item.qtd),
                    "valor_unit": str(item.valor_unit),
                }
                for item in last.items
            ]
            or fallback["itens"],
            "schedule_items": [
                {
                    "dia_label": item.dia_label,
                    "descricao": item.descricao,
                    "horas_servico": item.horas_servico,
                }
                for item in last.schedule_items
            ]
            or fallback["schedule_items"],
        }
    )
    return prefill


def parse_proposal_form(form: FormData, *, client_id: int, user_id: int) -> ProposalCreate:
    items: list[ProposalItemCreate] = []
    schedule_items: list[ScheduleItemCreate] = []
    descricoes = form.getlist("item_descricao")
    unidades = form.getlist("item_unidade")
    qtds = form.getlist("item_qtd")
    valores = form.getlist("item_valor_unit")
    schedule_dias = form.getlist("schedule_dia_label")
    schedule_descricoes = form.getlist("schedule_descricao")
    schedule_horas = form.getlist("schedule_horas_servico")

    for index, descricao in enumerate(descricoes):
        if not str(descricao).strip():
            continue
        unidade = str(unidades[index]).strip() if index < len(unidades) else "UN"
        qtd_value = str(qtds[index]) if index < len(qtds) else "0"
        valor_value = str(valores[index]) if index < len(valores) else "0"
        items.append(
            ProposalItemCreate(
                descricao=str(descricao).strip(),
                unidade=unidade or "UN",
                qtd=decimal_from_str(qtd_value, default="0.00"),
                valor_unit=decimal_from_str(valor_value, default="0.00"),
            )
        )

    for index, dia_label in enumerate(schedule_dias):
        descricao = str(schedule_descricoes[index]).strip() if index < len(schedule_descricoes) else ""
        horas = str(schedule_horas[index]).strip() if index < len(schedule_horas) else ""
        dia = str(dia_label).strip()
        if not dia and not descricao and not horas:
            continue
        schedule_items.append(
            ScheduleItemCreate(
                dia_label=dia,
                descricao=descricao,
                horas_servico=horas,
            )
        )

    return ProposalCreate(
        client_id=client_id,
        user_id=user_id,
        atencao=str(form.get("atencao", "")).strip(),
        ref_cliente=str(form.get("ref_cliente", "")).strip(),
        objeto_tipo=str(form.get("objeto_tipo", "manutencao_calibracao")).strip(),
        objeto_texto=str(form.get("objeto_texto", "")).strip(),
        canal=str(form.get("canal", "")).strip(),
        contato_nome=str(form.get("contato_nome", "")).strip(),
        contato_datahora=str(form.get("contato_datahora", "")).strip(),
        equipamento_nome=str(form.get("equipamento_nome", "")).strip(),
        equipamento_texto=str(form.get("equipamento_texto", "")).strip(),
        local_servico=str(form.get("local_servico", "")).strip(),
        km_ida=decimal_from_str(str(form.get("km_ida", "0"))),
        km_volta=decimal_from_str(str(form.get("km_volta", "0"))),
        km_valor=decimal_from_str(str(form.get("km_valor", "2.95"))),
        alim_tecnicos=int(str(form.get("alim_tecnicos", "1")) or "1"),
        alim_refeicoes=int(str(form.get("alim_refeicoes", "0")) or "0"),
        alim_valor=decimal_from_str(str(form.get("alim_valor", "0"))),
        condicao_pagamento_dias=int(str(form.get("condicao_pagamento_dias", "0")) or "0"),
        imposto_percentual=decimal_from_str(str(form.get("imposto_percentual", "0"))),
        itens=items,
        schedule_items=schedule_items,
    )
