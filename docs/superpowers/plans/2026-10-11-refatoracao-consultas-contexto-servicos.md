# Consultas e contexto conversacional de serviços — plano

> Executar sequencialmente com subagent-driven-development e revisão por tarefa. Sem commits.

**Objetivo:** separar consultas e referências apresentadas ao usuário dos rascunhos e confirmações de registros de serviço.

**Arquitetura:** `service_queries.py` contém consulta/projeção/resposta; `service_conversation_context.py` lê metadados de apresentações anteriores. O adapter original delega mantendo assinaturas e sessão; preparação/correção/lembretes/confirmação continuam nele. Nenhuma regra nova.

**Tecnologias:** Python/FastAPI/SQLAlchemy/pytest existentes; nenhuma dependência nova.

**Bloqueio de execução:** a caracterização reforçada da tarefa17 inicializou o
engine antes do conftest e atingiu o SQLite local `propostas.db`. Ver incidente
em `docs/refatoracao-consultas-contexto-servicos.md`. Não executar tarefa18 nem
mais testes de banco até decidir a recuperação. Em qualquer execução futura,
definir explicitamente `DATABASE_URL` e diretórios temporários antes dos imports
e validar o alvo do engine antes de fixtures de reset.

## Restrições globais

- Branch refactor/promotion-contacts, HEAD externo86e524f; preservar mudanças e histórico. Etapas anteriores concluídas não serão repetidas.
- Sem configs privadas/dados operacionais/integrações reais; sem início/reinício de processos.
- Sem commit/push/merge, migração, alteração de schema/configuração, exclusão de arquivo/teste ou assert enfraquecido.
- Preservar schemas, mensagens, filtros, ordenação, limites, evidência, callbacks, datas, Session, confirmação e idempotência.
- Não mover confirmação, mutações, tokens de ação, _ask ou _clarification. Não alterar os corpos de prepare_event, prepare_correction, _correct_pending_event_draft, prepare_reminders, confirm ou success.
- Uma suíte Python por vez, banco isolado e registros sintéticos. Não transformar refatoração em correção de regra preexistente.

## Task17 — consulta e projeção de chamados

Arquivos: app/assistant/service_records.py; novo app/assistant/service_queries.py; novo tests/test_assistant_service_queries.py.

Interfaces:

```python
@dataclass(frozen=True)
class ServiceQueryExecution:
    reply: AssistantReply
    result: ProviderToolResult | None = None

def execute_service_query(db, conversation_id, command, resolve_client) -> ServiceQueryExecution:
    # corpo literal de execute_query, self.db→db e self.resolve_client→resolve_client
```

O adapter mantém execute_query(conversation_id, command), passando sua Session e callback atual a cada chamada. A classe original ServiceQueryExecution fica alias por identidade. Não criar outro provider/adaptador genérico.

- [ ] Caracterizar antes: cliente ambíguo exige esclarecimento e não consulta lista; filtro com cliente disponível, estado técnico/administrativo, pending_only/return_tasks_only/limit; vazio com state empty; chamados com etapas unknown/waiting_customer e eventos efetivos incluindo correção; últimos três eventos com truncamento240; retornos somente com vínculo de evento/sem etapa/incompletos. Texto e payload com títulos, prazos e ordem corretos. Não alterar chamados/tarefas/histórico nem criar ações.
- [ ] Rodar novo teste + tests/test_assistant_service_records.py, tests/test_assistant_provider_parity.py, tests/test_service_record_service.py, tests/test_assistant_daily_brief.py antes/depois.
- [ ] Mover DTO e corpo literalmente, preservar aliases e demais métodos AST. O serviço de domínio continua service_record_service, a ordem resolver→consulta→projeção→evidence_id é a mesma, sem consulta paralela/cache.
- [ ] Lint completo comparativo, fatal/compile/diff e revisão independente antes da tarefa18.

## Task18 — contexto de chamados/retornos apresentados

Arquivos: app/assistant/service_records.py; novo app/assistant/service_conversation_context.py; novo tests/test_service_conversation_context.py.

Interface `ServiceConversationContext(db)` com presented_call_ids(conversation_id), presented_return_task_ids(conversation_id), was_presented(conversation_id, call_id, source_message). Função pura ordinal(source). Adapter conserva wrappers e _ordinal estático por alias.

- [ ] Caracterizar antes pelo adapter: isolamento conversa/role, metadados com elementos não-dict e IDs não-int, referências explícitas com limite de número (não aceitar #12 como #1), ordinais primeiro a quinto/case/limite de palavra conforme original, janela30 nas duas listas e20 em was_presented. Referência explícita deve short-circuit sem SQL; demais leituras devem executar exatamente um SELECT cada e nenhum DML.
- [ ] Rodar novo teste + testes tarefa17, tests/test_assistant_service_records.py, tests/test_assistant_service_report.py, tests/test_service_history_immutability.py antes/depois.
- [ ] Mover quatro corpos literalmente; deduplicar SOMENTE expressão de busca de mensagens em `_rows(conversation_id, limit)` privado. Mesmos filtros/ordem/limites; chamada por leitura, sem pré-carregar, memoizar ou ampliar janela. Não normalizar tipos/metadados nem corrigir booleanos/regex/ordinais.
- [ ] Adapter recebe context com mesma Session no init, wrappers históricos delegam; nenhum import do adapter no módulo novo. AST demais métodos (exceto init/wrappers) igual. Comparar expressão SQL e custos com testes de leitura.
- [ ] Lint/fatal/compile/diff e revisão independente.

## Fechamento

- [ ] Revisão consolidada da branch, suíte Python completa isolada,36JS, lint global comparativo, compilação/diff e hashes OpenAPI/DDL/auth.
- [ ] Documentação/ledger, métricas sem prometer redução total, nenhum restart/publicação ou uso de dados reais.

Launcher seguro; alterar somente lista de arquivos:

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "-ra"]))'
```

Baseline anterior903/13Python,36JS,223Ruff em app/scripts/tests. A 8013 continua
parada; não contornar autenticação ou efeitos de startup nesta refatoração.
