"""Fixed whole-HTML baselines captured before extracting Jinja includes."""
from hashlib import sha256
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.main import app


@pytest.fixture(autouse=True)
def reset_database():
    """Rendering uses synthetic context and never needs schema operations."""
    yield


def render_case(case):
    authenticated = case != "shell_anonymous"
    request = Request({
        "type": "http", "scheme": "http", "server": ("test", 80),
        "path": "/web/proposals/new" if authenticated else "/",
        "query_string": b"", "headers": [], "app": app,
        "session": {"auth_user_id": 7, "csrf_token": 'synthetic<&"token'}
        if authenticated else {},
    })
    context = {"request": request, "title": "Proposta <sintética>",
               "full_width": case == "shell_anonymous"}
    template = "base.html"
    if case.startswith("proposal"):
        template = "proposal_form.html"
        revision = case == "proposal_revision"
        form_data = {
            "client_id": "3" if revision else "", "user_id": "7" if revision else "",
            "atencao": "Atenção & revisão" if revision else "", "ref_cliente": "REF-01",
            "objeto_tipo": "outro" if revision else "manutencao_calibracao",
            "objeto_texto": "Objeto <sintético>", "canal": "Email",
            "contato_nome": "Contato", "contato_datahora": "08/10/2026 10:00",
            "equipamento_nome": "Balança", "equipamento_texto": "Texto & detalhe",
            "local_servico": "Cidade/UF", "km_ida": "12.5", "km_volta": "12.5",
            "km_valor": "2.95", "alim_tecnicos": "2", "alim_refeicoes": "1",
            "alim_valor": "35", "condicao_pagamento_dias": "30", "imposto_percentual": "5",
            "itens": [{"descricao": "Serviço <A>", "unidade": "UN", "qtd": "2", "valor_unit": "125.50"},
                      {"descricao": "Peça & B", "unidade": "PC", "qtd": "1", "valor_unit": "50"}],
            "schedule_items": [{"dia_label": "Dia 1", "descricao": "Calibrar & revisar", "horas_servico": "8h"}],
        }
        context.update(
            form_data=form_data, create_mode="revision" if revision else "new",
            base_proposal_id=41 if revision else None,
            revision_source=SimpleNamespace(numero=12, revisao="01") if revision else None,
            warning="Aviso <sintético> & revisão" if revision else None,
            clients=[SimpleNamespace(id=3, razao_social="Cliente <sintético>")],
            users=[SimpleNamespace(id=7, nome="Pessoa & equipe", cargo="Engenharia"),
                   SimpleNamespace(id=8, nome="Outra pessoa", cargo="")],
        )
    return app.state.templates.get_template(template).render(context)


@pytest.mark.parametrize(("case", "expected"), [
    ("shell_anonymous", "d2cd6f42ba4b32ad43493b622263f5d4d89e766998a45bfa600836babef499a6"),
    ("shell_authenticated", "35fbc0c8ab9119db0284870c7123fd5564211a4b0ace0704a6525cd9902ecc44"),
    ("proposal_new", "92c479fa599b863d7c46281241abb02a1c8cd542bd87fd04ce204892c15330e3"),
    ("proposal_revision", "aefa614fa391d9b57f8f90ef50ee4336ea0a699e4ca45172baced1e230363f74"),
])
def test_integral_html_matches_pre_extraction_baseline(case, expected):
    assert sha256(render_case(case).encode("utf-8")).hexdigest() == expected
