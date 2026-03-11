from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Proposal


def get_next_proposal_number(db: Session) -> int:
    current_max = db.query(func.max(Proposal.numero)).scalar()
    return int(current_max or 0) + 1


def get_next_revision_for_number(db: Session, numero: int) -> str:
    revisoes = db.query(Proposal.revisao).filter(Proposal.numero == numero).all()
    if not revisoes:
        return "00"
    valid_revs = [int(rev[0]) for rev in revisoes if str(rev[0]).isdigit()]
    if not valid_revs:
        return "00"
    max_rev = max(valid_revs)
    return f"{max_rev + 1:02d}"
