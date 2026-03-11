from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from app.config import Settings
from app.models import Client, Proposal, ProposalItem, ProposalScheduleItem, User
from app.schemas import ProposalCreate, ProposalItemCreate, ScheduleItemCreate
from app.services import document_service, numbering_service, pdf_service, storage_service, suggestion_service
from app.utils.currency import quantize_2, to_decimal


def _calc_item_totals(items_payload: list) -> tuple[list[dict[str, Decimal | str]], Decimal]:
    items_data: list[dict[str, Decimal | str]] = []
    total_items = Decimal("0.00")
    for item in items_payload:
        descricao = str(item.descricao).strip()
        if not descricao:
            continue
        qtd = quantize_2(item.qtd)
        valor_unit = quantize_2(item.valor_unit)
        total = quantize_2(qtd * valor_unit)
        total_items += total
        items_data.append(
            {
                "descricao": descricao,
                "unidade": item.unidade.strip() or "UN",
                "qtd": qtd,
                "valor_unit": valor_unit,
                "total": total,
            }
        )
    return items_data, quantize_2(total_items)


def _calc_logistics(
    km_ida: Decimal,
    km_volta: Decimal,
    km_valor: Decimal,
    alim_refeicoes: int,
    alim_valor: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    km_total = quantize_2(km_ida + km_volta)
    desloc_total = quantize_2(km_total * km_valor)
    alim_total = quantize_2(to_decimal(alim_refeicoes) * alim_valor)
    return km_total, desloc_total, alim_total


def _normalize_schedule_items(schedule_payload: list[ScheduleItemCreate]) -> list[dict[str, str]]:
    schedule_data: list[dict[str, str]] = []
    for item in schedule_payload:
        dia_label = str(item.dia_label).strip()
        descricao = str(item.descricao).strip()
        horas_servico = str(item.horas_servico).strip()
        if not dia_label and not descricao and not horas_servico:
            continue
        schedule_data.append(
            {
                "dia_label": dia_label,
                "descricao": descricao,
                "horas_servico": horas_servico,
            }
        )
    return schedule_data


def get_proposal_with_details(db: Session, proposal_id: int) -> Proposal | None:
    return (
        db.query(Proposal)
        .options(
            joinedload(Proposal.client),
            joinedload(Proposal.user),
            joinedload(Proposal.items),
            joinedload(Proposal.schedule_items),
        )
        .filter(Proposal.id == proposal_id)
        .first()
    )


def _validate_payload_references(db: Session, payload: ProposalCreate) -> None:
    client_exists = db.query(Client.id).filter(Client.id == payload.client_id).first()
    if not client_exists:
        raise ValueError("Client not found")

    user_exists = db.query(User.id).filter(User.id == payload.user_id, User.ativo.is_(True)).first()
    if not user_exists:
        raise ValueError("Active user not found")


def get_recent_proposals_by_client(db: Session, client_id: int, limit: int = 10) -> list[Proposal]:
    return (
        db.query(Proposal)
        .options(joinedload(Proposal.user))
        .filter(Proposal.client_id == client_id)
        .order_by(Proposal.data_geracao.desc(), Proposal.id.desc())
        .limit(limit)
        .all()
    )


def _copy_proposal_items(source: Proposal) -> list[ProposalItemCreate]:
    return [
        ProposalItemCreate(
            descricao=item.descricao,
            unidade=item.unidade,
            qtd=item.qtd,
            valor_unit=item.valor_unit,
        )
        for item in source.items
    ]


def _copy_schedule_items(source: Proposal) -> list[ScheduleItemCreate]:
    return [
        ScheduleItemCreate(
            dia_label=item.dia_label,
            descricao=item.descricao,
            horas_servico=item.horas_servico,
        )
        for item in source.schedule_items
    ]


def _build_clone_payload(source: Proposal, user_id: int | None = None) -> ProposalCreate:
    return ProposalCreate(
        client_id=source.client_id,
        user_id=user_id or source.user_id,
        atencao=source.atencao,
        ref_cliente=source.ref_cliente,
        objeto_tipo=source.objeto_tipo,
        objeto_texto=source.objeto_texto,
        canal=source.canal,
        contato_nome=source.contato_nome,
        contato_datahora=source.contato_datahora,
        equipamento_nome=source.equipamento_nome,
        equipamento_texto=source.equipamento_texto,
        local_servico=source.local_servico,
        km_ida=source.km_ida,
        km_volta=source.km_volta,
        km_valor=source.km_valor,
        alim_tecnicos=source.alim_tecnicos,
        alim_refeicoes=source.alim_refeicoes,
        alim_valor=source.alim_valor,
        condicao_pagamento_dias=source.condicao_pagamento_dias,
        imposto_percentual=source.imposto_percentual,
        itens=_copy_proposal_items(source),
        schedule_items=_copy_schedule_items(source),
    )


def create_proposal(db: Session, payload: ProposalCreate, mode: str = "new", base_proposal_id: int | None = None) -> Proposal:
    if mode not in {"new", "revision"}:
        raise ValueError("mode must be 'new' or 'revision'")

    _validate_payload_references(db, payload)

    base_proposal = None
    if mode == "revision":
        if not base_proposal_id:
            raise ValueError("base_proposal_id is required for revision mode")
        base_proposal = get_proposal_with_details(db, base_proposal_id)
        if not base_proposal:
            raise ValueError("base proposal not found")
        numero = base_proposal.numero
        revisao = numbering_service.get_next_revision_for_number(db, numero=numero)
    else:
        numero = numbering_service.get_next_proposal_number(db)
        revisao = "00"

    items_data, total_items = _calc_item_totals(payload.itens)
    schedule_data = _normalize_schedule_items(payload.schedule_items)

    km_ida = quantize_2(payload.km_ida)
    km_volta = quantize_2(payload.km_volta)
    km_valor = quantize_2(payload.km_valor)
    alim_valor = quantize_2(payload.alim_valor)
    imposto_percentual = quantize_2(payload.imposto_percentual)
    condicao_pagamento_dias = max(int(payload.condicao_pagamento_dias), 0)

    km_total, desloc_total, alim_total = _calc_logistics(
        km_ida=km_ida,
        km_volta=km_volta,
        km_valor=km_valor,
        alim_refeicoes=payload.alim_refeicoes,
        alim_valor=alim_valor,
    )
    valor_total = quantize_2(total_items + desloc_total + alim_total)

    proposal = Proposal(
        numero=numero,
        revisao=revisao,
        data_geracao=date.today(),
        client_id=payload.client_id,
        user_id=payload.user_id,
        atencao=payload.atencao,
        ref_cliente=payload.ref_cliente,
        objeto_tipo=payload.objeto_tipo,
        objeto_texto=payload.objeto_texto,
        canal=payload.canal,
        contato_nome=payload.contato_nome,
        contato_datahora=payload.contato_datahora,
        equipamento_nome=payload.equipamento_nome,
        equipamento_texto=payload.equipamento_texto,
        local_servico=payload.local_servico,
        km_ida=km_ida,
        km_volta=km_volta,
        km_total=km_total,
        km_valor=km_valor,
        desloc_total=desloc_total,
        alim_tecnicos=payload.alim_tecnicos,
        alim_refeicoes=payload.alim_refeicoes,
        alim_valor=alim_valor,
        alim_total=alim_total,
        condicao_pagamento_dias=condicao_pagamento_dias,
        imposto_percentual=imposto_percentual,
        valor_total=valor_total,
    )
    db.add(proposal)
    db.flush()

    for index, item_data in enumerate(items_data, start=1):
        db.add(
            ProposalItem(
                proposal_id=proposal.id,
                ordem=index,
                descricao=str(item_data["descricao"]),
                unidade=str(item_data["unidade"]),
                qtd=item_data["qtd"],
                valor_unit=item_data["valor_unit"],
                total=item_data["total"],
            )
        )

    for index, schedule in enumerate(schedule_data, start=1):
        db.add(
            ProposalScheduleItem(
                proposal_id=proposal.id,
                ordem=index,
                dia_label=schedule["dia_label"],
                descricao=schedule["descricao"],
                horas_servico=schedule["horas_servico"],
            )
        )

    db.commit()
    return get_proposal_with_details(db, proposal.id)  # type: ignore[return-value]


def clone_proposal(db: Session, proposal_id: int, user_id: int | None = None) -> Proposal:
    source = get_proposal_with_details(db, proposal_id)
    if not source:
        raise ValueError("source proposal not found")
    payload = _build_clone_payload(source=source, user_id=user_id)
    return create_proposal(db, payload, mode="new")


def duplicate_proposal(db: Session, proposal_id: int, user_id: int | None = None) -> Proposal:
    return clone_proposal(db, proposal_id=proposal_id, user_id=user_id)


def generate_documents(db: Session, proposal_id: int, settings: Settings) -> tuple[Proposal, str | None]:
    proposal = get_proposal_with_details(db, proposal_id)
    if not proposal:
        raise ValueError("proposal not found")

    docx_path, pdf_path = storage_service.build_document_paths(
        base_output=settings.output_dir,
        proposal_date=proposal.data_geracao,
        client_name=proposal.client.razao_social,
        numero=proposal.numero,
        revisao=proposal.revisao,
    )

    context = document_service.build_template_context(proposal)
    document_service.render_docx_from_template(
        template_path=settings.template_doc_path,
        context=context,
        output_path=docx_path,
    )

    pdf_error = None
    try:
        pdf_service.convert_docx_to_pdf(
            docx_path=docx_path,
            pdf_path=pdf_path,
            libreoffice_cmd=settings.libreoffice_cmd,
        )
    except RuntimeError as exc:
        pdf_error = str(exc)

    proposal.docx_path = storage_service.to_output_relative(docx_path, settings.output_dir)
    proposal.pdf_path = storage_service.to_output_relative(pdf_path, settings.output_dir) if pdf_path.exists() else ""
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal, pdf_error


def get_last_proposal_by_client(db: Session, client_id: int) -> Proposal | None:
    return suggestion_service.get_last_proposal_for_client(db, client_id)
