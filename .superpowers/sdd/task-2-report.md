# Tarefa 2 — servico de dominio e invariantes

Estado: implementada localmente; revisao independente encontrou um problema de transacao e a correcao foi aplicada.

## Implementacao

- `app/services/service_record_service.py` contem consultas, registro de evento, correcao, projecao e criacao de lembretes pelo `board_service`.
- `tests/test_service_record_service.py` cobre cinco etapas, eventos, transicoes, idempotencia, correcao append-only, empate deterministico, projecoes, lembretes e rollback.
- Eventos efetivos sao ordenados por `(occurred_on, leaf_event_id)`. Transicoes administrativas sao aplicadas em ordem deterministica pelo ID crescente; a projecao atual e recomposta a partir do estado `unknown`.
- `commit=False` mantem as alteracoes dentro da transacao chamadora. Para SQLite, `_ensure_database_transaction` emite `BEGIN` real antes de `SAVEPOINT` quando o driver ainda nao iniciou transacao, evitando que `RELEASE SAVEPOINT` persista dados.

## Evidencia TDD

- GREEN inicial apos implementacao: `PYTHONPATH=. .venv/bin/pytest tests/test_service_record_service.py -q` — 21 passed.
- Reviewer reproduziu RED para tres caminhos: `register_event`, `correct_event` e `create_reminders` com `commit=False`, seguido de `rollback()` ainda deixavam dados persistidos em nova sessao.
- RED local adicionado: `PYTHONPATH=. .venv/bin/pytest tests/test_service_record_service.py -q -k 'commit_false'` — 3 failed com persistencia indevida observada.
- GREEN da correcao: mesmo comando — 3 passed, 21 deselected.
- A reproduçao acima revelou ainda o reset global de pytest tentando apagar tabelas com FKs historicas `RESTRICT`. `tests/conftest.py` passou a desligar temporariamente FKs apenas durante `drop_all` no arquivo SQLite de teste e reativa-las antes de criar o esquema e as guardas; nao altera conexoes operacionais. Validacao combinada posterior: `PYTHONPATH=. .venv/bin/pytest tests/test_service_record_service.py tests/test_service_history_immutability.py tests/test_assistant_schema_compatibility.py -q` — 32 passed.

## Limites

- Tarefa 2 aguarda re-review final depois da correcao de transacao.
- PostgreSQL nao foi executado; a validacao permanece pendente.
- Sem commit, push, deploy, acesso ao banco operacional, Yahoo ou alteracao de processos 8000/8011.
