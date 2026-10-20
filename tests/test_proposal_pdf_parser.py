"""Synthetic characterization of the historical commercial PDF interpreter."""

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.models import Client, Proposal, User
from app.routers import imports
from app.services import pdf_import_service as parser

WARNINGS = [
    "Could not confidently extract proposal object.",
    "No proposal items parsed from PDF.",
    "No schedule rows parsed from PDF.",
]


@pytest.mark.parametrize("text,message", [(" \n", "PDF text is empty."), ("Proposta\n123", "Could not extract client name.")])
def test_parse_errors(text, message):
    with pytest.raises(parser.PDFImportError) as caught:
        parser.parse_pdf_text(text)
    assert type(caught.value) is parser.PDFImportError
    assert str(caught.value) == message


@pytest.mark.parametrize("text,name", [
    ("Cliente: Empresa Sintética", "Empresa Sintética"),
    ("Razão social\nEmpresa Sintética", "Empresa Sintética"),
    ("Cliente - Empresa Sintética", "Empresa Sintética"),
    ("Proposta comercial\nEmpresa Sintética", "Empresa Sintética"),
])
def test_client_labels_and_fallback(text, name):
    parsed = parser.parse_pdf_text(text, "synthetic.pdf")
    assert parsed.to_preview() == {
        "filename": "synthetic.pdf", "client_name": name, "atencao": "", "objeto_texto": "",
        "condicao_pagamento_dias": 0, "imposto_percentual": "0.00",
        "schedule_rows": [], "items": [], "warnings": WARNINGS,
    }


@pytest.mark.parametrize("attention,expected", [("", "Maria Teste"), ("Empresa Sintética", "Maria Teste"), ("José Teste", "José Teste")])
def test_reference_contact(attention, expected):
    text = f"Cliente: Empresa Sintética\nAtenção: {attention}\nRef. cliente/projeto: Maria Teste"
    assert parser.parse_pdf_text(text).atencao == expected


@pytest.mark.parametrize("raw,default,expected", [
    ("R$ 1.234,56", "0.00", "1234.56"), ("1,234.56", "0.00", "1234.56"),
    ("-12,5", "0.00", "-12.5"), ("", "1.00", "1.00"), ("inválido", "2.00", "2.00"),
])
def test_decimal_formats_defaults_and_negative(raw, default, expected):
    assert parser._parse_decimal(raw, default) == Decimal(expected)


@pytest.mark.parametrize("lines,expected", [
    (["Serviço | 2 | 12,50 | 25,00"], [{"descricao": "Serviço", "unidade": "UN", "qtd": "2", "valor_unit": "12.50"}]),
    (["• Serviço 2 UN R$ 12,50 R$ 25,00"], [{"descricao": "Serviço", "unidade": "UN", "qtd": "2", "valor_unit": "12.50"}]),
    (["- Serviço", "* Outro"], [{"descricao": "Serviço", "unidade": "UN", "qtd": "1.00", "valor_unit": "0.00"}, {"descricao": "Outro", "unidade": "UN", "qtd": "1.00", "valor_unit": "0.00"}]),
])
def test_item_rows(lines, expected):
    assert [item.as_preview() for item in parser._parse_item_rows(lines)] == expected


@pytest.mark.parametrize("lines,expected", [
    (["• Instalar", "• Testar", "2 dias 8 horas"], [{"dia_label": "2 dias", "descricao": "Instalar; Testar", "horas_servico": "8 horas"}]),
    (["Dia 1 | Instalar | 8h", "Dia 2; Testar", "Dia 3: Revisar - 2,5 horas"], [{"dia_label": "Dia 1", "descricao": "Instalar", "horas_servico": "8h"}, {"dia_label": "Dia 2", "descricao": "Testar", "horas_servico": ""}, {"dia_label": "Dia 3", "descricao": "Revisar", "horas_servico": "2,5 horas"}]),
])
def test_schedule_rows(lines, expected):
    assert [row.as_preview() for row in parser._parse_schedule_rows(lines)] == expected


@pytest.mark.parametrize("suffix", ["Pagamento: 30 dias\nISS: 5,5%", "Condição de pagamento\n30 dias\nAlíquota\n5,5%"])
def test_complete_preview_and_payload(suffix):
    text = "Cliente: Empresa Sintética\nContato: Maria Teste\nObjeto: Manutenção\nCronograma\nDia 1 | Instalar | 8h\nItens\nServiço | 2 | 12,50 | 25,00\n" + suffix
    parsed = parser.parse_pdf_text(text, "synthetic.pdf")
    assert parsed.to_preview() == {
        "filename": "synthetic.pdf", "client_name": "Empresa Sintética", "atencao": "Maria Teste",
        "objeto_texto": "Manutenção", "condicao_pagamento_dias": 30, "imposto_percentual": "5.5",
        "schedule_rows": [{"dia_label": "Dia 1", "descricao": "Instalar", "horas_servico": "8h"}],
        "items": [{"descricao": "Serviço", "unidade": "UN", "qtd": "2", "valor_unit": "12.50"}], "warnings": [],
    }
    payload = parsed.to_proposal_payload(17, 23)
    assert (payload.client_id, payload.user_id, payload.contato_nome) == (17, 23, "Maria Teste")
    assert (payload.imposto_percentual, payload.itens[0].qtd, payload.itens[0].valor_unit) == (Decimal("5.5"), Decimal(2), Decimal("12.50"))
    assert payload.schedule_items[0].horas_servico == "8h"
    parsed.condicao_pagamento_dias = -3
    assert parsed.to_proposal_payload(17, 23).condicao_pagamento_dias == 0


def test_original_extractor_and_parser_patch_seams(monkeypatch):
    monkeypatch.setattr(parser, "_extract_text_pdfplumber", lambda _: "Cliente: Empresa Sintética")
    assert parser.parse_pdf_bytes(b"synthetic").client_name == "Empresa Sintética"
    sentinel = object()
    monkeypatch.setattr(parser, "parse_pdf_text", lambda **kwargs: sentinel)
    assert parser.parse_pdf_bytes(b"synthetic") is sentinel


def test_historical_exports_are_identical_to_pure_parser():
    from app.services import proposal_pdf_parser

    names = [
        "PDFImportError", "PDFNoTextError", "ParsedProposalItem", "ParsedScheduleRow",
        "ParsedProposalData", "_normalize_text", "_parse_decimal", "_find_label_value",
        "_find_first_candidate_client", "_extract_section", "_parse_schedule_rows",
        "_parse_item_rows", "_extract_payment_days", "_extract_tax_percent", "parse_pdf_text",
    ]
    for name in names:
        assert getattr(parser, name) is getattr(proposal_pdf_parser, name)
    assert issubclass(parser.PDFNoTextError, parser.PDFImportError)


def test_synthetic_http_preview_confirmation_and_errors(db, monkeypatch):
    # The extractor is simulated; only the existing router and persistence flow execute.
    monkeypatch.setattr(parser, "_extract_text_pdfplumber", lambda payload: "Cliente: Empresa Sintética\nObjeto: Manutenção" if payload == b"synthetic" else "")
    monkeypatch.setattr(parser, "_extract_text_pymupdf", lambda _: "")
    app = FastAPI()
    app.include_router(imports.router)
    app.dependency_overrides[get_db] = lambda: db
    user = User(nome="Usuário Sintético", email="synthetic@example.com", senha_hash="synthetic", ativo=True)
    db.add(user)
    db.commit()
    with TestClient(app) as client:
        def upload(payload=b"synthetic", **data):
            return client.post("/api/import-proposals", files=[("files", ("synthetic.pdf", payload, "application/pdf"))], data=data)
        preview = upload()
        assert preview.status_code == 200
        assert preview.json()["imported"] == 0
        assert preview.json()["results"][0]["message"] == "Preview parsed successfully."
        assert db.query(Client).count() == db.query(Proposal).count() == 0
        invalid = upload(confirm="true", user_id="99999")
        assert invalid.status_code == 400
        assert invalid.json() == {"detail": "Active user for import not found."}
        confirmed = upload(confirm="true", user_id=str(user.id))
        assert confirmed.status_code == 200
        assert confirmed.json()["imported"] == 1
        assert confirmed.json()["results"][0]["message"] == "Imported successfully."
        proposal = db.query(Proposal).one()
        assert proposal.user_id == user.id
        assert db.query(Client).one().razao_social == "Empresa Sintética"
        error = upload(b"scanned")
        assert error.json()["results"][0]["message"] == "PDF sem texto extraível."
        assert db.query(Client).count() == db.query(Proposal).count() == 1
