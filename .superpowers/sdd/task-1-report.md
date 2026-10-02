# Tarefa 1 — modelos, DTOs, historico imutavel e migracao aditiva

Data: 2026-10-02  
Estado: implementada e verificada em SQLite isolado  
HEAD observado durante o trabalho: `b727569` (`fix problem with email validation for local Yahoo accounts`). Nenhum commit, push ou deploy foi criado por este agente.

## Escopo entregue

- `app/models.py`: cinco tabelas aditivas (`service_calls`, `service_events`, `service_workflow_steps`, `service_workflow_transitions`, `service_task_links`), defaults, relacionamentos sem cascata destrutiva no historico, FKs restritivas, FKs compostas e restricoes de unicidade/check.
- `app/schemas.py`: literais de estados e tipos, DTOs de evento, correcao, consulta, etapa e lembrete com limites e validacao de correcao.
- `app/db.py`: `PRAGMA foreign_keys=ON` e `PRAGMA recursive_triggers=ON` nas conexoes SQLite SQLAlchemy abertas apos registro do listener; instalacao idempotente de triggers SQLite, declaracao de funcao/triggers PostgreSQL, instalacao no caminho de inicializacao `ensure_schema_compatibility()` apos `create_all`, e guarda ORM `before_flush` para alteracao/exclusao de historico persistido.
- `tests/test_assistant_schema_compatibility.py`: esquema anterior sem as cinco tabelas, sentinelas de cliente, tarefa, proposta e lancamento, criacao aditiva, instalacao dupla das guardas e verificacao de preservacao.
- `tests/test_service_record_service.py`: estados iniciais do chamado e das cinco etapas, validacao de DTOs.
- `tests/test_service_history_immutability.py`: pragmas SQLite, relacionamentos e FKs historicas, FK composta de transicao, SQL direto contra UPDATE/DELETE/INSERT OR REPLACE e exclusao de registros referenciados, guarda ORM.

## Ciclo RED/GREEN

1. RED inicial: `.venv/bin/pytest tests/test_assistant_schema_compatibility.py tests/test_service_record_service.py tests/test_service_history_immutability.py -q` parou antes da coleta (`ModuleNotFoundError: No module named 'app'`). O executavel requer `PYTHONPATH=.` neste checkout; isso nao foi contado como RED funcional.
2. RED funcional: `PYTHONPATH=. .venv/bin/pytest tests/test_assistant_schema_compatibility.py tests/test_service_record_service.py tests/test_service_history_immutability.py -q` produziu tres erros de coleta esperados: `ServiceCall` e `ensure_service_history_guards_for_engine` ainda nao existiam.
3. GREEN: o mesmo comando com `PYTHONPATH=.` passou com `8 passed`.
4. Regressao focada: `PYTHONPATH=. .venv/bin/pytest tests/test_assistant_schema_compatibility.py tests/test_service_record_service.py tests/test_service_history_immutability.py tests/test_lancamento_model.py tests/test_proposal_origin.py -q` passou com `19 passed, 110 warnings` em 0,72 s.
5. `git diff --check`: passou, sem saida.

Os avisos sao `DeprecationWarning` de `datetime.utcnow()` nos defaults SQLAlchemy existentes e nos novos modelos que seguem o mesmo padrao do projeto. Nenhum erro ou falha de teste ocorreu na rodada final.

## Self-review

- As conexoes SQLite abertas por `Engine` SQLAlchemy apos o registro do listener em `app.db` recebem as duas pragmas; o teste usa um `Engine` independente para confirmar isso. A garantia nao inclui `sqlite3.connect` direto nem conexoes abertas antes do listener.
- `ServiceEvent.assistant_action_id` e unico e nao nulo. O evento expoe a chave candidata `(id, service_call_id, assistant_action_id)`. A transicao referencia essa chave e a etapa `(service_call_id, step_type)` por FKs compostas; `previous_status <> new_status` e obrigatorio.
- O historico possui triggers de bloqueio de UPDATE/DELETE e FKs `RESTRICT`; o ORM bloqueia alteracoes e exclusoes antes do flush. Os testes executam SQL direto e confirmam que os dados originais permanecem.
- A criacao das cinco etapas `unknown` por um chamado registrado pertence ao servico de dominio da Tarefa 2. Aqui foram estabelecidos os defaults e validada a persistencia direta das cinco linhas; nenhuma regra de negocio de criacao foi antecipada nesta tarefa.
- Tabelas existentes nao tiveram colunas alteradas. Nenhum banco operacional, processo nas portas 8000/8011 ou Yahoo foi acessado.

## Preocupacoes e limites

- A funcao e os triggers PostgreSQL estao declarados no codigo, mas nao foram executados contra uma instancia PostgreSQL isolada; esta tarefa nao afirma essa validacao.
- Os testes de historico usam SQLite temporario e instalam explicitamente as guardas apos `create_all`. Chamadas diretas a `Base.metadata.create_all` feitas fora do startup devem tambem chamar `ensure_service_history_guards_for_engine` antes de aceitar gravacoes historicas.
- A integridade de cadeia linear e do mesmo chamado para correcoes sera validada pelo servico de dominio da Tarefa 2; esta tarefa fornece unicidade de `supersedes_event_id` e FKs restritivas.

## Correcoes apos revisao

- RED: `PYTHONPATH=. .venv/bin/pytest tests/test_service_history_immutability.py -q` mostrou `recursive_triggers=0` e dois testes `INSERT OR REPLACE` com `DID NOT RAISE`: tanto um `ServiceEvent` sem transicao quanto uma `ServiceWorkflowTransition` existente podiam ser substituidos sem disparar o trigger de DELETE.
- GREEN: o listener de conexao SQLite passou a executar `PRAGMA recursive_triggers=ON` junto de `foreign_keys=ON`. `PYTHONPATH=. .venv/bin/pytest tests/test_service_history_immutability.py -q` resultou em `6 passed, 78 warnings`; o SQL de substituicao agora falha com `service history is immutable` e os valores originais permanecem.
- O caso de transicao com chamado divergente agora usa um novo evento/acao sem transicao anterior para a etapa. Ele verifica explicitamente `FOREIGN KEY constraint failed`, eliminando a possibilidade de a restricao unica `(assistant_action_id, step_type)` ser a causa da falha. O caso de acao divergente tambem verifica a mensagem de FK.
- Regressao proporcional: `PYTHONPATH=. .venv/bin/pytest tests/test_assistant_schema_compatibility.py tests/test_service_record_service.py tests/test_service_history_immutability.py tests/test_lancamento_model.py tests/test_proposal_origin.py -q` resultou em `21 passed, 140 warnings` em 0,83 s. `git diff --check` passou.
- Os warnings continuam sendo `DeprecationWarning` de `datetime.utcnow()` nos defaults SQLAlchemy; PostgreSQL permanece apenas declarado, sem teste contra instancia isolada. Nenhum commit, push ou deploy foi feito por este agente.
