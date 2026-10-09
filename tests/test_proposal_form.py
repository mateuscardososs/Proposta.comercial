"""Characterization of proposal form parsing and route orchestration."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.datastructures import FormData

from app.routers import pages
from app.schemas import ProposalCreate, ProposalItemCreate, ScheduleItemCreate
from app.services import proposal_service


@pytest.fixture(autouse=True)
def reset_database():
    """These isolated route tests require no database or schema operations."""
    yield


class FormRequest:
    def __init__(self, values):
        self.values = FormData(values)

    async def form(self):
        return self.values

    def url_for(self, name, **params):
        if name == "web_proposal_new":
            return "http://test/web/proposals/new"
        assert name == "web_proposal_detail"
        return f"http://test/web/proposals/{params['proposal_id']}"


@pytest.fixture
def flow(monkeypatch):
    events = []
    created = SimpleNamespace(
        id=41, numero=12, revisao="01", client_id=3, user_id=7,
        client=SimpleNamespace(razao_social="Cliente sintético"), objeto_texto="Objeto",
    )

    def create(db, **kwargs):
        events.append(("create", kwargs))
        return created

    def generate(db, **kwargs):
        events.append(("documents", kwargs))
        return created, "PDF indisponível"

    def card(db, payload):
        events.append(("card", payload))

    monkeypatch.setattr(proposal_service, "create_proposal", create)
    monkeypatch.setattr(proposal_service, "generate_documents", generate)
    monkeypatch.setattr(pages.board_service, "create_task", card)
    return events


def submit(values):
    return asyncio.run(pages.proposal_new_submit(FormRequest(values), db=object()))


def test_brazilian_items_keep_original_indexes_and_short_lists(flow, monkeypatch):
    monkeypatch.setattr(pages.settings, "default_km_value", Decimal("9.99"))
    response = submit([
        ("client_id", "3"), ("user_id", "7"), ("atencao", "  Atenção  "),
        ("item_descricao", "  "), ("item_descricao", " Serviço "),
        ("item_descricao", "Peça"), ("item_descricao", "Outro"),
        ("item_unidade", "ignorada"), ("item_unidade", "  "),
        ("item_qtd", "99"), ("item_qtd", "1,5"), ("item_qtd", ""),
        ("item_valor_unit", "99"), ("item_valor_unit", "1.234,56"),
        ("schedule_dia_label", ""), ("schedule_dia_label", " Dia 2 "),
        ("schedule_dia_label", ""), ("schedule_dia_label", ""),
        ("schedule_descricao", ""), ("schedule_descricao", " Trabalho "),
        ("schedule_descricao", " Apenas descrição "),
        ("schedule_horas_servico", ""), ("schedule_horas_servico", " 8h "),
    ])
    assert response.status_code == 303
    assert [event[0] for event in flow] == ["create", "documents"]
    payload = flow[0][1]["payload"]
    assert payload.atencao == "Atenção"
    assert payload.km_valor == Decimal("2.95")
    assert pages._default_form_data()["km_valor"] == "9.99"
    assert [item.model_dump() for item in payload.itens] == [
        {"descricao": "Serviço", "unidade": "UN", "qtd": Decimal("1.5"), "valor_unit": Decimal("1234.56")},
        {"descricao": "Peça", "unidade": "UN", "qtd": Decimal(0), "valor_unit": Decimal(0)},
        {"descricao": "Outro", "unidade": "UN", "qtd": Decimal(0), "valor_unit": Decimal(0)},
    ]
    assert [item.model_dump() for item in payload.schedule_items] == [
        {"dia_label": "Dia 2", "descricao": "Trabalho", "horas_servico": "8h"},
        {"dia_label": "", "descricao": "Apenas descrição", "horas_servico": ""},
    ]
    assert parse_qs(urlsplit(response.headers["location"]).query) == {"warning": ["PDF indisponível"]}


@pytest.mark.parametrize(("values", "warning", "revision"), [
    ([("mode", "revision"), ("base_proposal_id", "-1")], "Proposta base invalido.", None),
    ([("mode", "revision"), ("base_proposal_id", "0")], "Proposta base invalido.", None),
    ([("mode", "revision"), ("base_proposal_id", "abc")], "Proposta base invalido.", None),
    ([("client_id", "0"), ("user_id", "7")], "Cliente invalido.", None),
    ([("client_id", "3"), ("user_id", "")], "Responsavel invalido.", None),
    ([("mode", "revision"), ("base_proposal_id", "9"), ("client_id", "x")], "Cliente invalido.", "9"),
    ([("client_id", "3"), ("user_id", "7"), ("km_ida", "inválido")],
     "Valor numerico invalido: inválido", None),
])
def test_invalid_ids_and_parsing_redirect_before_service_calls(flow, values, warning, revision):
    response = submit(values)
    assert response.status_code == 303
    query = {"warning": [warning]}
    if revision:
        query["revision_from"] = [revision]
    assert urlsplit(response.headers["location"]).path == "/web/proposals/new"
    assert parse_qs(urlsplit(response.headers["location"]).query) == query
    assert flow == []


@pytest.mark.parametrize(("mode", "expected_mode", "base"), [
    (" REVISION ", "revision", 9), ("unknown", "new", None),
])
def test_revision_mode_and_optional_card_order(flow, mode, expected_mode, base):
    response = submit([
        ("client_id", "3"), ("user_id", "7"), ("mode", mode),
        ("base_proposal_id", "9"), ("create_kanban_card", "1"),
    ])
    assert response.status_code == 303
    assert [event[0] for event in flow] == ["create", "documents", "card"]
    assert flow[0][1]["mode"] == expected_mode
    assert flow[0][1]["base_proposal_id"] == base
    card = flow[-1][1]
    assert card.titulo == "Proposta #12/01 - Cliente sintético"
    assert card.descricao == "Gerada automaticamente.\nObjeto: Objeto"
    assert (card.status, card.proposal_id, card.client_id, card.user_id) == (
        "aguardando_cliente", 41, 3, 7,
    )


def source_proposal():
    payload = ProposalCreate(
        client_id=3, user_id=7, atencao=" atenção ", ref_cliente="REF",
        objeto_tipo="outro", objeto_texto="Objeto", canal="Telefone",
        contato_nome="Contato sintético", contato_datahora="2026-10-07 10:30",
        equipamento_nome="Balança sintética", equipamento_texto="Equipamento de teste",
        local_servico="Local sintético", km_ida=Decimal("12.50"),
        km_volta=Decimal("13.50"), km_valor=Decimal("3.50"),
        alim_tecnicos=2, alim_refeicoes=3, alim_valor=Decimal("40.50"),
        condicao_pagamento_dias=15, imposto_percentual=Decimal("5.50"),
        itens=[ProposalItemCreate(
            descricao=" Item ", unidade="H", qtd=Decimal("1.50"), valor_unit=Decimal("120.50"),
        )],
        schedule_items=[ScheduleItemCreate(
            dia_label="Dia 1", descricao="Atividade sintética", horas_servico="8h",
        )],
    )
    values = payload.model_dump()
    values["items"] = payload.itens
    values["schedule_items"] = payload.schedule_items
    return SimpleNamespace(**values)


@pytest.mark.parametrize("user_id", [None, 0, 8])
def test_existing_clone_builder_equals_pages_conversion(user_id):
    source = source_proposal()
    # Expected fields come from synthetic input, not either builder under test.
    expected = {
        name: value for name, value in vars(source).items()
        if name not in {"items", "schedule_items"}
    }
    expected["user_id"] = 8 if user_id == 8 else 7
    expected["schedule_items"] = [{
        "dia_label": "Dia 1", "descricao": "Atividade sintética", "horas_servico": "8h",
    }]
    assert pages._proposal_to_payload(source, user_id).model_dump() == expected
    assert proposal_service._build_clone_payload(source, user_id).model_dump() == expected


def test_prefill_preserves_values_and_empty_collection_fallback():
    source = source_proposal()
    fallback = pages._default_form_data()
    prefill = pages._prefill_from_last(source, fallback)
    assert prefill["atencao"] == " atenção "
    assert prefill["km_valor"] == "3.50"
    assert prefill["itens"][0]["qtd"] == "1.50"
    assert fallback["client_id"] == ""
    source.items = []
    source.schedule_items = []
    prefill = pages._prefill_from_last(source, fallback)
    assert prefill["itens"] is fallback["itens"]
    assert prefill["schedule_items"] is fallback["schedule_items"]


def test_duplicate_still_creates_then_generates(flow, monkeypatch):
    source = source_proposal()
    monkeypatch.setattr(proposal_service, "get_proposal_with_details", lambda *args: source)
    response = pages.proposal_duplicate_submit(2, FormRequest([]), db=object())
    assert response.status_code == 303
    assert [event[0] for event in flow] == ["create", "documents"]
    assert flow[0][1]["mode"] == "new"
