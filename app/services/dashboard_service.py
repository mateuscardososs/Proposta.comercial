from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, case, func
from sqlalchemy.orm import Session

from app.models import Lancamento, Proposal, Task


ZERO = Decimal("0.00")
TWOPLACES = Decimal("0.01")


@dataclass(frozen=True)
class DashboardSummary:
    receber_pendente: Decimal
    receber_vencido: Decimal
    pagar_pendente: Decimal
    pagar_vencido: Decimal
    tarefas_atrasadas: int
    tarefas_a_fazer: int
    tarefas_em_andamento: int
    propostas_mes_quantidade: int
    propostas_mes_valor: Decimal
    mes_inicio: date
    mes_fim_exclusivo: date


def _month_bounds(reference_date: date) -> tuple[date, date]:
    month_start = reference_date.replace(day=1)
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    return month_start, next_month


def _money(value: object) -> Decimal:
    return Decimal(str(value or ZERO)).quantize(TWOPLACES)


def get_dashboard_summary(
    db: Session,
    reference_date: date | None = None,
) -> DashboardSummary:
    today_value = reference_date or date.today()
    month_start, next_month = _month_bounds(today_value)

    financial = db.query(
        func.coalesce(
            func.sum(
                case(
                    (Lancamento.tipo == "receber", Lancamento.valor),
                    else_=0,
                )
            ),
            0,
        ),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            Lancamento.tipo == "receber",
                            Lancamento.data_vencimento < today_value,
                        ),
                        Lancamento.valor,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
        func.coalesce(
            func.sum(
                case(
                    (Lancamento.tipo == "pagar", Lancamento.valor),
                    else_=0,
                )
            ),
            0,
        ),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            Lancamento.tipo == "pagar",
                            Lancamento.data_vencimento < today_value,
                        ),
                        Lancamento.valor,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
    ).filter(Lancamento.status == "pendente").one()

    tasks = db.query(
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            Task.status != "concluido",
                            Task.prazo.is_not(None),
                            Task.prazo < today_value,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
        func.coalesce(
            func.sum(case((Task.status == "a_fazer", 1), else_=0)),
            0,
        ),
        func.coalesce(
            func.sum(case((Task.status == "em_andamento", 1), else_=0)),
            0,
        ),
    ).one()

    proposals = db.query(
        func.count(Proposal.id),
        func.coalesce(func.sum(Proposal.valor_total), 0),
    ).filter(
        Proposal.data_geracao >= month_start,
        Proposal.data_geracao < next_month,
    ).one()

    return DashboardSummary(
        receber_pendente=_money(financial[0]),
        receber_vencido=_money(financial[1]),
        pagar_pendente=_money(financial[2]),
        pagar_vencido=_money(financial[3]),
        tarefas_atrasadas=int(tasks[0] or 0),
        tarefas_a_fazer=int(tasks[1] or 0),
        tarefas_em_andamento=int(tasks[2] or 0),
        propostas_mes_quantidade=int(proposals[0] or 0),
        propostas_mes_valor=_money(proposals[1]),
        mes_inicio=month_start,
        mes_fim_exclusivo=next_month,
    )
