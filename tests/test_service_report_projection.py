from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from app.services import service_report_service as report


def event(event_id, kind, description, day=2):
    return SimpleNamespace(id=event_id, event_type=kind, description=description,
                           occurred_on=date(2026, 10, day))


def call(events, completed=datetime(2026, 10, 3, 23, 59, tzinfo=UTC)):
    return SimpleNamespace(
        client_id=7, summary=" Chamado sintético ", opened_on=date(2026, 10, 1),
        technically_completed_at=completed, events=events,
        client=SimpleNamespace(razao_social=" Cliente ", cnpj=" 123 ", telefone=" 456 ",
                               endereco_linha1=" Rua A ", endereco_linha2=" ",
                               cep=" 789 ", cidade_uf=" Cidade/UF "),
    )


def test_labels_narrative_repetition_and_unknown_lines():
    assert report._normalize_label("  ÁNÁLISE Ç Ã  ") == "analise c a"
    assert report._parse_narrative(
        "\nEQUIPAMENTO: Balança\nAnálise: inicial\nsem separador\n"
        "Análise: final: detalhada\nAnálise:   \nDesconhecido: ignorado\n"
        "Serviço executado: ajuste\nProblema relatado: erro\n"
    ) == {"equipment": "Balança", "analysis": "final: detalhada",
          "work_performed": "ajuste", "reported_problem": "erro"}


@pytest.mark.parametrize(("description", "expected"), [
    ("Verificação de retorno — visita: resolvido.\n  Testado.  ",
     "Retorno registrado como resolvido. Testado."),
    ("VERIFICAÇÃO DE RETORNO - visita: continua pendente.",
     "Retorno registrado como ainda pendente."),
    ("Verificação sem resultado\nObservação", ""),
])
def test_verification(description, expected):
    assert report._verification_from_event(description) == expected


def test_source_literal_timeline_precedence_and_all_ids():
    first = event(9, "inspection", " Equipamento: antigo\nAnálise: inicial ", 4)
    last = event(3, "execution_completed", "Equipamento: atual\nServiço executado: ajuste", 2)
    correction = event(12, "correction", "correção omitida")
    source = report._serialize_source(call([correction, first, last]), [first, last])
    assert source == {
        "client": "Cliente", "client_details": {
            "client_id": 7, "name": "Cliente", "cnpj": "123", "phone": "456",
            "address": "Rua A · 789 · Cidade/UF"},
        "summary": "Chamado sintético", "opened_on": "2026-10-01",
        "fields": {"client_name": "Cliente", "client_cnpj": "123",
                   "client_phone": "456", "client_address": "Rua A · 789 · Cidade/UF",
                   "equipment": "atual", "completion_date": "2026-10-02",
                   "reported_problem": "", "analysis": "inicial",
                   "work_performed": "ajuste", "verification_result": ""},
        "event_timeline": [
            {"date": "04/10/2026", "type": "Inspeção",
             "description": "Equipamento: antigo\nAnálise: inicial"},
            {"date": "02/10/2026", "type": "Execução concluída",
             "description": "Equipamento: atual\nServiço executado: ajuste"}],
        "source_event_ids": [3, 9, 12],
    }


def test_inspection_does_not_set_completion_and_unknown_event_label():
    inspection = event(1, "custom", " Análise: verificada ", 8)
    assert report._serialize_source(call([inspection], None), [inspection])["fields"]["completion_date"] == ""
    source = report._serialize_source(call([inspection]), [inspection])
    assert source["fields"]["completion_date"] == "2026-10-03"
    assert source["event_timeline"] == [{"date": "08/10/2026", "type": "custom",
                                          "description": "Análise: verificada"}]
    assert report._format_date(None) == ""
    assert report._format_date(date(2026, 10, 3)) == "03/10/2026"


def test_fields_conversion_unknown_values_and_missing_order():
    fields = report._fields_model({"client_name": " Cliente ", "equipment": 42,
                                   "analysis": None, "ignored": "value"})
    assert fields.model_dump() == {
        "client_name": " Cliente ", "client_cnpj": "", "client_phone": "",
        "client_address": "", "equipment": "42", "completion_date": "",
        "reported_problem": "", "analysis": "", "work_performed": "",
        "verification_result": ""}
    assert report._missing_fields(fields) == [
        "client_cnpj", "client_phone", "client_address", "completion_date",
        "reported_problem", "analysis", "work_performed", "verification_result"]
    assert report._missing_fields(report._fields_model({"client_name": "  "}))[0] == "client_name"


def test_fingerprint_key_order_facts_and_new_event():
    assert report._fingerprint({"b": 2, "a": "á"}) == report._fingerprint({"a": "á", "b": 2})
    source = report._serialize_source(call([]), [])
    original = report._fingerprint(source)
    assert len(original) == 64
    assert report._fingerprint({**source, "summary": "Outro fato"}) != original
    assert report._fingerprint({**source, "source_event_ids": [1]}) != original


def test_projection_aliases_share_objects():
    from app.services import service_report_projection as projection

    for name in (
        "FIELD_LABELS", "EVENT_LABELS", "NARRATIVE_LABELS", "_normalize_label",
        "_parse_narrative", "_verification_from_event", "_format_date",
        "_serialize_source", "_fingerprint", "_fields_model", "_missing_fields",
    ):
        assert getattr(report, name) is getattr(projection, name)
