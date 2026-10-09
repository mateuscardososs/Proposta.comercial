# Separação de rascunhos de tarefas e resolução de cadastros

> Etapas 10–11 da refatoração segura, com caracterização antes e revisão independente. Sem commits pelo agente.

**Objetivo:** retirar do orquestrador a preparação/correção de rascunhos de tarefas e a resolução de nomes, mantendo confirmação e execução operacional no mesmo fluxo.

**Arquitetura:** `AssistantTaskDraftAdapter` segue o padrão dos adapters de serviços/relatórios; recebe a mesma sessão e callbacks explícitos de resolução/token. `AssistantEntityResolver` concentra consulta e correspondência de cliente/responsável. Métodos históricos de `AssistantService` delegam sem mudar assinatura. Nenhum novo caminho de gravação de Task.

**Restrições:** preservar branch `refactor/safe-modularization`, commits externos e mudanças locais; nenhuma configuração privada, dado operacional, migração, schema, dependência, restart ou integração real. Não alterar login, regex, mensagens, limites, datas, regras de cliente/proposta ou status. Manter a mesma ordem de consultas, flush/rollback/commit e geração de tokens. Não remover arquivos/testes. Usar `apply_patch` e launcher seguro abaixo, com apenas uma suíte Python por vez.

## Etapa 10 — adapter de rascunho de tarefa

Arquivos: `app/assistant/service.py`, novo `app/assistant/task_drafts.py`, novo `tests/test_assistant_task_drafts.py`.

Interface do adapter:

```python
AssistantTaskDraftAdapter(db, *, token_hash, resolve_task_client, resolve_user)
adapter.prepare(conversation_id, request_id, command, today, *, existing_action=None)
adapter.correct(conversation_id, request_id, command, today)
adapter.confirmation_reply(action, confirmation_token)
adapter.record_clarification(conversation_id, request_id, command)
```

Mover os corpos de `_prepare_task`, `_correct_pending_task`, `_task_confirmation_reply` e `_record_clarification_action` literalmente, ajustando apenas nomes das chamadas internas. Resolvers e token hash permanecem callbacks; STATUS_LABELS usa o mesmo TASK_STATUS_LABELS compartilhado. O adapter pode fazer os mesmos flush/rollback do rascunho; não adicionar commit, Task, documento ou consulta de e-mail. Orquestrador conserva `_confirm_action_record`, `_cancel_action_record`, `_save_reply`, leases, cache/reconciliação e validação de token.

- [x] Antes da extração, caracterizar pelo serviço existente: responsável ambíguo mantém um rascunho em needs_clarification; correção usa o mesmo action/request; tokens antigos invalidam após correção; optional cliente ausente/ambíguo, remoções de cliente/responsável/prazo, duração; proposta inexistente/múltiplas revisões/cliente incompatível; nenhuma Task antes de confirmação.
- [x] Rodar novos testes e `test_assistant_service.py`, `test_assistant_provider_parity.py`, `test_assistant_routes.py`, `test_board_assistant_validation.py` antes.
- [x] Extrair somente os quatro métodos, criar adapter no init e wrappers históricos. Callback deve usar o mesmo objeto de sessão; sem importar AssistantService no adapter.
- [x] Rodar mesmo conjunto depois; AST dos demais métodos (exceto init) igual. Registrar recuperação após IntegrityError conforme original, sem corrigir política de token/conflito como parte da refatoração.
- [x] Ruff novo e E9/F existente, compile/diff, revisão independente. Nenhuma suíte completa pelo worker.

## Etapa 11 — resolução de cliente e responsável

Arquivos: `app/assistant/service.py`, novo `app/assistant/entity_resolution.py`, novo `tests/test_assistant_entity_resolution.py`.

Interface:

```python
AssistantEntityResolver(db)
resolver.client(name)
resolver.task_client(name)
resolver.user(name)
resolver.named(name, candidates, label, entity_name)
```

Mover `_resolve_client`, `_resolve_task_client`, `_resolve_user`, `_resolve_named` literalmente. Client não cadastrado é opcional para tarefas e mantém texto original; serviço continua recebendo o resolver estrito pelo wrapper atual. Responsáveis continuam filtrados por ativo. Preservar as diferenças entre matching estrito e de tarefas (inclusive empate exato), normalização, sentinelas, truncamento255 e oito opções na mensagem. Manter aliases de tipo/assinaturas históricos quando necessários. Não introduzir índice, SQL adicional, cadastro ou fuzzy matching novo.

- [x] Caracterizar antes: único/exato versus parcial, nomes com acento, dois clientes parecidos e dois iguais normalizados, cliente ausente com texto livre, sentinelas e nome longo, responsável ativo/inativo/ambíguo. Conferir identidade da entidade retornada e texto de pergunta, sem inventar IDs.
- [x] Rodar novos testes + os da etapa10, `test_assistant_service_records.py`, `test_assistant_service_report.py`, `test_assistant_provider_parity.py` antes.
- [x] Extrair, instanciar resolver no init e preservar wrappers usados pelos três adapters. Não mover transações e não fazer callbacks importarem o orquestrador.
- [x] Repetir conjunto; AST demais métodos igual, Ruff/compile/diff e revisão independente.

## Fechamento

- [x] Suíte completa isolada, JS, compilação, lint global comparativo e diff-check.
- [x] OpenAPI/DDL/auth hashes preservados e revisão consolidada das interações.
- [x] Documentação e ledger atualizados, distinguindo código validado de runtime ainda parado e defeitos anteriores.

Fechamento 09/10/2026: 130 e 125 testes focados antes/depois; suíte completa
836 passed, 13 skipped, 6857 warnings, 50.90s; 36 JS. Ruff global mantém 223
ocorrências preexistentes; lint novo/fatal e compile/diff passam. Hashes
OpenAPI/DDL/auth preservados, revisão consolidada Approved. RF-05 registrado
separadamente. Removida apenas uma assertion adjacente duplicada, sem remover
teste. 8013 continua sem listener; não iniciada por efeitos de startup.

Launcher obrigatório; adaptar apenas arquivos de teste:

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "TEST_FILES_HERE"]))'
```

Baseline812passed/13skipped,36JS,223achadosRuff. HEAD externo ba245e2 incorporou o fechamento das etapas anteriores; preservar. Não ativar 8013 porque startup ainda executa operações proibidas no banco/Yahoo.
