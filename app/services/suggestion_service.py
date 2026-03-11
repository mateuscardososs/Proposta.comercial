from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session, joinedload

from app.models import Proposal, ProposalItem


def get_last_proposal_for_client(db: Session, client_id: int) -> Proposal | None:
    return (
        db.query(Proposal)
        .options(
            joinedload(Proposal.client),
            joinedload(Proposal.user),
            joinedload(Proposal.items),
            joinedload(Proposal.schedule_items),
        )
        .filter(Proposal.client_id == client_id)
        .order_by(Proposal.data_geracao.desc(), Proposal.id.desc())
        .first()
    )


def suggest_last_item_value(db: Session, client_id: int, descricao: str) -> Decimal | None:
    match = (
        db.query(ProposalItem.valor_unit)
        .join(Proposal, ProposalItem.proposal_id == Proposal.id)
        .filter(Proposal.client_id == client_id, ProposalItem.descricao == descricao)
        .order_by(Proposal.data_geracao.desc(), Proposal.id.desc(), ProposalItem.id.desc())
        .first()
    )
    return match[0] if match else None
