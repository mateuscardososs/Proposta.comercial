# Tarefa 3 — Consulta web somente leitura

## Entrega

- `GET /web/services` lista chamados recentes com cliente, estados tecnico e administrativo, proxima pendencia e link para o detalhe.
- `GET /web/services/{service_call_id}` exibe as cinco etapas atuais, eventos originais e correcoes, transicoes administrativas completas (etapa, estado anterior e novo, observacao, evento e acao confirmada) e links para lembretes vinculados.
- O menu existente inclui `Servicos` com estado ativo. As paginas nao possuem formulario nem rota de escrita.
- A rota consulta o dominio por `list_service_calls`, `get_service_call` e `effective_service_events`; estados atuais sao lidos das projecoes persistidas.

## TDD

- RED: `PYTHONPATH=. .venv/bin/pytest tests/test_service_routes.py -q` — 2 falhas esperadas por HTTP 404 em `/web/services` e `/web/services/{id}`; o teste de ID inexistente passou.
- GREEN: `PYTHONPATH=. .venv/bin/pytest tests/test_service_routes.py tests/test_dashboard_routes.py tests/test_board_statuses.py -q` — **8 passed**, exit 0. Avisos de deprecacao preexistentes de FastAPI/Starlette/SQLAlchemy.
- `git diff --check` — exit 0.

Os testes de rota usam `tmp_path` com SQLite proprio e substituem `get_db` durante as requisicoes. Nenhum processo, porta, Yahoo ou banco operacional foi usado. Sem commit, push ou deploy.

## Revisao T3

- RED: `PYTHONPATH=. .venv/bin/pytest tests/test_service_routes.py -q` — lista com seis chamados executou 8 SELECTs e detalhe com tres lembretes executou 9 SELECTs; ambos falharam os limites de consultas.
- As duas consultas do dominio agora carregam os relacionamentos usados pelas paginas em lotes. A lista carrega cliente e etapas; o detalhe carrega cliente, etapas, eventos, transicoes, vinculos e tarefas.
- O teste de transicoes separa as seis celulas de cada linha e compara etapa, estado anterior, estado novo, observacao e IDs de acao/evento nas posicoes corretas. A linha nao pode passar por encontrar textos de outra transicao na pagina.
- GREEN final: `PYTHONPATH=. .venv/bin/pytest tests/test_service_routes.py tests/test_dashboard_routes.py tests/test_board_statuses.py tests/test_service_record_service.py -q --disable-warnings` — **32 passed**, exit 0. `git diff --check` — exit 0.
