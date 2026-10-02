# Registro e acompanhamento de servicos — plano de implementacao

> **Para agentes executores:** SUB-SKILL OBRIGATORIA: usar `subagent-driven-development` (recomendado) ou `executing-plans` para executar este plano tarefa por tarefa. As etapas usam caixas de selecao para acompanhamento.

**Objetivo:** Registrar um chamado por atendimento, manter visitas e fatos como eventos append-only, separar conclusao tecnica de encerramento administrativo e integrar consulta, confirmacao e lembretes ao assistente de texto e voz.

**Arquitetura:** Cinco tabelas novas formam o agregado de servico sem modificar propostas, tarefas ou financeiro. Eventos e transicoes administrativas sao o historico imutavel; `ServiceCall` e `ServiceWorkflowStep` sao projecoes atuais reconstruiveis. `service_record_service` concentra as regras e transacoes; o assistente manipula somente comandos Pydantic e a interface web consulta o mesmo servico. Voz continua sendo uma entrada para o fluxo textual existente.

**Stack:** FastAPI, SQLAlchemy 2, Pydantic 2, Jinja2, JavaScript sem framework, pytest, testes Node, Ollama, faster-whisper e Piper.

## Restricoes globais

- Usar banco e diretorios de teste isolados; nao iniciar o novo codigo contra o banco operacional.
- Criar somente tabelas novas; nao transformar dados nem colunas existentes.
- Nao alterar criacao, revisao, clonagem ou geracao DOCX/PDF de propostas.
- Nao gerar documentos, emitir nota, alterar financeiro, escrever em e-mail ou criar lembretes sem confirmacao.
- Manter Yahoo somente leitura e preservar a aplicacao da porta 8000.
- Nao fazer commit, push ou deploy. Embora o fluxo padrao de planejamento sugira commits incrementais, a proibicao expressa do usuario prevalece.
- Usar `America/Recife` para datas conversacionais e mostrar a data absoluta no rascunho.
- Uma inspecao nunca conclui a execucao.
- Correcao persistida e append-only; o evento original nao e alterado nem excluido.
- Toda persistencia conversacional deve ser confirmada, idempotente e reconciliavel depois de timeout.
- Uma acao confirmada gera no maximo um `ServiceEvent` e pode gerar varias `ServiceWorkflowTransition`, uma por etapa alterada.
- `ServiceEvent` e `ServiceWorkflowTransition` nao admitem `UPDATE` ou `DELETE`; correcoes sempre acrescentam linhas e recompõem as projecoes.

## Mapa de arquivos

### Novos

- `app/services/service_record_service.py` — regras, consultas e transacoes do agregado de servico.
- `app/routers/services.py` — paginas somente leitura de lista e detalhe.
- `app/templates_web/services.html` — lista operacional de chamados.
- `app/templates_web/service_detail.html` — etapas, eventos e tarefas vinculadas.
- `app/assistant/service_records.py` — adaptacao entre comandos do assistente e o servico de dominio; resolucao de referencias e formatacao de evidencias.
- `tests/test_service_record_service.py` — regras de dominio e idempotencia de lembretes.
- `tests/test_service_history_immutability.py` — FKs restritivas, guardas ORM e triggers de banco.
- `tests/test_service_routes.py` — lista, detalhe e links.
- `tests/test_assistant_service_records.py` — rascunhos, confirmacao, correcao, consulta e protecoes.
- `tests/test_assistant_service_ollama_live.py` — casos controlados com o modelo local, executados somente por opt-in.
- `scripts/seed_assistant_service_validation.py` — clientes e chamados sinteticos em banco explicitamente isolado.
- `docs/assistente/validacao-servicos-local.md` — evidencias automatizadas e reais da execucao.

### Modificados

- `app/models.py` — cinco modelos aditivos e relacionamentos.
- `app/db.py` — instalacao idempotente das guardas de imutabilidade em SQLite e PostgreSQL.
- `app/schemas.py` — literais e DTOs do dominio.
- `app/assistant/contracts.py` — quatro comandos estruturados e campos de resposta.
- `app/assistant/provider.py` — resultados de consulta e acoes pendentes de servico.
- `app/assistant/ollama.py` — ferramentas, contrato compacto e grounding.
- `app/assistant/capabilities.py` — leitura e escrita confirmada de servicos.
- `app/assistant/evidence.py` — afirmacoes de consulta e gravacao condicionadas a evidencia.
- `app/assistant/service.py` — roteamento e ciclo generico de rascunho/confirmacao/cancelamento.
- `app/routers/assistant.py` — injecao das capacidades, sem rota de escrita paralela.
- `app/main.py` — inclusao do router somente leitura.
- `app/templates_web/base.html` — item “Servicos” no menu existente.
- `app/static/assistant_chat.js` — link para chamado e multiplos lembretes.
- `tests/js/assistant_chat.test.mjs` — renderizacao dos novos links.
- `tests/test_assistant_schema_compatibility.py` — migracao aditiva preservando dados sentinela.
- `tests/test_assistant_contracts.py` — validacao dos comandos.
- `tests/test_assistant_voice_routes.py` e `tests/js/assistant_voice.test.mjs` — regressao do caminho voz → mensagem.
- `scripts/run_assistant_8011_yahoo.sh` — diretorios isolados para a validacao de servicos, sem imprimir credenciais.
- `docs/assistente/execucao.md` — configuracao, limites e roteiro manual.

---

### Tarefa 1: Modelos, DTOs, historico imutavel e migracao aditiva

**Arquivos:**

- Modificar: `app/models.py`
- Modificar: `app/schemas.py`
- Modificar: `app/db.py`
- Modificar: `tests/test_assistant_schema_compatibility.py`
- Criar: `tests/test_service_record_service.py`
- Criar: `tests/test_service_history_immutability.py`

**Interfaces produzidas:**

```python
ServiceExecutionStatus = Literal["not_started", "in_progress", "completed"]
ServiceAdministrativeStatus = Literal["open", "closed"]
ServiceEventType = Literal[
    "call_received", "visit_started", "inspection",
    "execution_started", "execution_completed", "note", "correction",
]
CorrectableServiceEventType = Literal[
    "call_received", "visit_started", "inspection",
    "execution_started", "execution_completed", "note",
]
ServiceStepType = Literal["report", "proposal", "proposal_sent", "invoice", "receipt"]
ServiceStepStatus = Literal["unknown", "not_applicable", "pending", "waiting_customer", "completed"]

class ServiceStepChange(BaseModel):
    step_type: ServiceStepType
    status: ServiceStepStatus
    note: str = Field(default="", max_length=1000)

class ServiceEventCreate(BaseModel):
    client_id: int = Field(ge=1)
    service_call_id: int | None = Field(default=None, ge=1)
    force_new_call: bool = False
    summary: str = Field(min_length=1, max_length=500)
    event_type: ServiceEventType
    occurred_on: date
    description: str = Field(min_length=1, max_length=4000)
    step_changes: list[ServiceStepChange] = Field(default_factory=list, max_length=5)

class ServiceEventCorrectionCreate(BaseModel):
    service_call_id: int = Field(ge=1)
    supersedes_event_id: int = Field(ge=1)
    occurred_on: date
    reason: str = Field(min_length=1, max_length=1000)
    corrected_event_type: CorrectableServiceEventType | None = None
    corrected_occurred_on: date | None = None
    corrected_description: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def require_corrected_field(self) -> "ServiceEventCorrectionCreate":
        if not any((self.corrected_event_type, self.corrected_occurred_on, self.corrected_description)):
            raise ValueError("Informe ao menos um campo corrigido.")
        return self

class ServiceCallQuery(BaseModel):
    client_id: int | None = Field(default=None, ge=1)
    execution_status: ServiceExecutionStatus | None = None
    administrative_status: ServiceAdministrativeStatus | None = None
    pending_only: bool = False
    limit: int = Field(default=20, ge=1, le=50)

class ServiceReminderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    status: TaskStatus = "a_fazer"
    due_date: date | None = None
    user_id: int | None = Field(default=None, ge=1)
    step_type: ServiceStepType | None = None
```

Os modelos SQLAlchemy serao `ServiceCall`, `ServiceEvent`, `ServiceWorkflowStep`, `ServiceWorkflowTransition` e `ServiceTaskLink`. `ServiceEvent` tera campos opcionais `corrected_event_type`, `corrected_occurred_on` e `corrected_description`, validos somente quando `event_type="correction"`. `ServiceEvent.assistant_action_id` sera `NOT NULL` e unico, garantindo um evento por acao confirmada. `supersedes_event_id` sera unico e restritivo, formando cadeias de correcao sem ramificacoes. O evento tambem declarara a chave candidata composta `(id, service_call_id, assistant_action_id)` usada para validar os vinculos das transicoes.

`ServiceWorkflowStep` tera `UniqueConstraint("service_call_id", "step_type")`. `ServiceWorkflowTransition` tera `service_call_id`, `step_type`, `previous_status`, `new_status`, `observation`, `service_event_id`, `assistant_action_id` e `created_at`. Uma FK composta `(service_call_id, step_type)` aponta para a linha unica de `ServiceWorkflowStep`; outra FK composta `(service_event_id, service_call_id, assistant_action_id)` aponta para a chave candidata de `ServiceEvent`, impedindo combinar evento, chamado e acao divergentes. Todas usam `RESTRICT`. `UniqueConstraint("assistant_action_id", "step_type")` impede duplicacao por replay, e `CheckConstraint("previous_status <> new_status")` impede transicoes sem efeito. `ServiceTaskLink` tera `UniqueConstraint("task_id")` e `assistant_action_id` para reconciliar o lote.

- [ ] **Etapa 1: Escrever os testes de esquema e dos defaults**

Adicionar testes que constroem o esquema anterior sem as cinco novas tabelas, gravam um `Client`, uma `Task`, uma `Proposal` e um `Lancamento`, executam `Base.metadata.create_all(engine)`, instalam as guardas e verificam:

```python
SERVICE_TABLES = {
    "service_calls", "service_events", "service_workflow_steps",
    "service_workflow_transitions", "service_task_links"
}
assert SERVICE_TABLES.issubset(set(inspect(engine).get_table_names()))
assert session.scalar(select(Task.titulo)) == "Dado operacional preservado"
assert session.scalar(select(Client.razao_social)) == "Cliente preservado"
```

Em `tests/test_service_record_service.py`, criar um chamado diretamente e verificar os cinco passos `unknown`, além dos estados técnico e administrativo iniciais. Em `tests/test_service_history_immutability.py`, verificar que os relacionamentos de eventos/transicoes nao possuem `delete-orphan` nem `delete`, que suas FKs historicas declaram `RESTRICT`/`NO ACTION` e que o banco rejeita uma transicao cujo chamado ou acao nao corresponda ao evento informado.

- [ ] **Etapa 2: Executar os testes e confirmar a falha esperada**

Executar:

```bash
.venv/bin/pytest tests/test_assistant_schema_compatibility.py tests/test_service_record_service.py tests/test_service_history_immutability.py -q
```

Esperado: falha de importacao dos novos modelos, ausencia das tabelas ou ausencia das guardas.

- [ ] **Etapa 3: Adicionar DTOs e modelos**

Adicionar as cinco tabelas sem alterar colunas existentes. `ServiceCall.events` e `ServiceCall.workflow_transitions` nao usam `delete-orphan` nem `delete`; usam `save-update, merge` e `passive_deletes=True`. As FKs de `ServiceEvent` e `ServiceWorkflowTransition` para chamado, evento anterior, etapa e `AssistantAction` usam `ondelete="RESTRICT"` ou o `NO ACTION` equivalente. `ServiceTaskLink.task_id` pode usar `SET NULL` para preservar o vinculo auditavel quando uma tarefa for removida; nenhuma FK historica usa `CASCADE`. A configuracao de conexao SQLite deve manter `PRAGMA foreign_keys=ON`, com teste que falha explicitamente se a pragma estiver desabilitada.

Ao criar um chamado pelo servico de dominio, inserir exatamente uma linha para cada tipo de etapa, todas inicialmente `unknown`.

- [ ] **Etapa 4: Instalar guardas de imutabilidade no banco**

Adicionar `ensure_service_history_guards_for_engine(target_engine)` em `app/db.py` e chama-la depois de `Base.metadata.create_all`. A funcao deve ser idempotente e criar:

- SQLite: triggers `service_events_reject_update`, `service_events_reject_delete`, `service_workflow_transitions_reject_update` e `service_workflow_transitions_reject_delete`, todos com `RAISE(ABORT, 'service history is immutable')`;
- PostgreSQL: funcao `reject_service_history_mutation()` e triggers `BEFORE UPDATE OR DELETE` equivalentes nas duas tabelas.

Adicionar tambem uma guarda `Session.before_flush` que rejeita `ServiceEvent` ou `ServiceWorkflowTransition` em `session.deleted` ou com atributos persistidos alterados. A mensagem da aplicacao deve ser clara, mas os triggers sao a protecao contra SQL direto.

- [ ] **Etapa 5: Validar imutabilidade e FKs diretamente no banco**

Em SQLite isolado, afirmar primeiro `PRAGMA foreign_keys=ON`, criar um chamado com evento e transicao e executar SQL direto. `UPDATE service_events`, `DELETE FROM service_events`, `UPDATE service_workflow_transitions`, `DELETE FROM service_workflow_transitions`, `DELETE FROM service_calls`, exclusao da `ServiceWorkflowStep` referenciada e exclusao da `AssistantAction` confirmada devem levantar `DBAPIError`/`IntegrityError` e deixar todas as contagens e valores intactos. Quando um PostgreSQL isolado estiver disponivel, repetir o mesmo contrato contra o container; ausencia desse teste deve ser documentada, nao inferida a partir de SQLite.

- [ ] **Etapa 6: Executar testes focados**

```bash
.venv/bin/pytest tests/test_assistant_schema_compatibility.py tests/test_service_record_service.py tests/test_service_history_immutability.py -q
```

Esperado: testes de esquema, defaults, restricoes e triggers passam; nenhum banco fora do fixture de pytest e aberto.

---

### Tarefa 2: Servico de dominio e invariantes

**Arquivos:**

- Criar: `app/services/service_record_service.py`
- Expandir: `tests/test_service_record_service.py`

**Consome:** `ServiceEventCreate`, `ServiceEventCorrectionCreate`, `ServiceCallQuery`, `TaskCreate` e os cinco modelos da Tarefa 1.

**Produz:**

```python
@dataclass(frozen=True)
class ServiceMutationResult:
    service_call: ServiceCall
    event: ServiceEvent
    transitions: Sequence[ServiceWorkflowTransition]

@dataclass(frozen=True)
class EffectiveServiceEvent:
    source_event_id: int
    leaf_event_id: int
    event_type: CorrectableServiceEventType
    occurred_on: date
    description: str
```

Assinaturas publicas: `list_service_calls(db: Session, query: ServiceCallQuery) -> list[ServiceCall]`, `get_service_call(db: Session, service_call_id: int) -> ServiceCall | None`, `find_open_calls_for_client(db: Session, client_id: int) -> list[ServiceCall]`, `effective_service_events(events: Sequence[ServiceEvent]) -> list[EffectiveServiceEvent]`, `rebuild_current_projection(db: Session, service_call: ServiceCall) -> None`, `register_event(db, payload, *, conversation_id, assistant_action_id, commit=True) -> ServiceMutationResult`, `correct_event(db, payload, *, conversation_id, assistant_action_id, commit=True) -> ServiceMutationResult` e `create_reminders(db, *, service_call_id, assistant_action_id, reminders, commit=True) -> list[Task]`.

- [ ] **Etapa 1: Escrever testes das transicoes**

Cobrir nominalmente `test_inspection_does_not_complete_execution`, `test_execution_started_marks_in_progress`, `test_explicit_execution_completed_marks_only_technical_completion`, `test_report_pending_keeps_administration_open`, `test_proposal_not_applicable_does_not_force_order`, `test_administration_closes_only_when_execution_and_all_steps_are_terminal`, `test_unknown_to_pending_to_waiting_customer_records_two_transitions`, `test_one_action_changes_multiple_steps_with_one_event`, `test_duplicate_assistant_action_reconciles_event_and_transitions`, `test_correction_completed_to_inspection_reprojects_to_in_progress`, `test_correction_completed_to_inspection_without_start_reprojects_to_not_started`, `test_description_only_correction_keeps_completed_projection`, `test_correction_chain_rejects_branch`, `test_correction_preserves_original_event` e `test_reminders_use_board_service_and_link_tasks_once`.

O teste de inspecao deve afirmar `execution_status == "not_started"`. O teste de conclusao deve afirmar `execution_status == "completed"` e `administrative_status == "open"` enquanto houver qualquer passo nao terminal.

- [ ] **Etapa 2: Confirmar testes vermelhos**

```bash
.venv/bin/pytest tests/test_service_record_service.py -q
```

Esperado: falhas por funcoes ausentes.

- [ ] **Etapa 3: Implementar as invariantes**

`register_event` deve:

1. validar cliente e chamado;
2. recusar `service_call_id` de outro cliente;
3. criar chamado apenas quando `service_call_id is None`;
4. impedir novo chamado e associacao simultaneos;
5. criar exatamente um evento para `assistant_action_id`;
6. para cada `step_change`, bloquear a linha `ServiceWorkflowStep`, ler o estado anterior, rejeitar no-op e criar uma `ServiceWorkflowTransition` ligada ao mesmo evento e acao;
7. permitir que a mesma acao gere varias transicoes, mas no maximo uma por `step_type`;
8. atualizar as projecoes das etapas somente depois de todas as transicoes serem validas;
9. chamar `rebuild_current_projection` em vez de alterar `execution_status` por atribuicao incremental;
10. recalcular `administrative_status` como `closed` apenas quando a projecao tecnica estiver concluida e os cinco passos forem `completed` ou `not_applicable`;
11. gravar acao, evento, transicoes e projecoes numa unica transacao.

`effective_service_events` percorre cadeias lineares de `supersedes_event_id`, exige que cada correcao aponte para a folha atual do mesmo chamado e aplica os campos corrigidos cumulativamente. A folha efetiva nunca tem tipo `correction`. `rebuild_current_projection` ordena os fatos efetivos por `(occurred_on, leaf_event_id)`, encontra o ultimo entre `execution_started` e `execution_completed` e define `execution_status`/`technically_completed_at`; sem fato de execucao usa `not_started`. Depois recalcula `administrative_status`.

`correct_event` cria `event_type="correction"`, preenche `supersedes_event_id`, chama a recomposicao completa e nao executa `UPDATE` no evento original. Corrigir uma conclusao para inspecao deve remover a conclusao da projecao: o resultado e `in_progress` se um inicio anterior continuar efetivo, ou `not_started` caso contrario. Uma correcao somente de descricao preserva o tipo e o estado tecnico. `create_reminders` chama `board_service.create_task` com `commit=False`, cria os vinculos e faz um unico commit.

- [ ] **Etapa 4: Verificar dominio e rollback**

Adicionar um teste que injeta falha depois da primeira de varias transicoes e afirma rollback do evento, de todas as transicoes e das projecoes. Adicionar outro que falha depois do primeiro lembrete e afirma zero novas tarefas/vinculos. Executar:

```bash
.venv/bin/pytest tests/test_service_record_service.py -q
```

Esperado: todos passam.

---

### Tarefa 3: Consulta web somente leitura

**Arquivos:**

- Criar: `app/routers/services.py`
- Criar: `app/templates_web/services.html`
- Criar: `app/templates_web/service_detail.html`
- Criar: `tests/test_service_routes.py`
- Modificar: `app/main.py`
- Modificar: `app/templates_web/base.html`

**Rotas produzidas:**

```text
GET /web/services                    nome: web_services
GET /web/services/{service_call_id}  nome: web_service_detail
```

- [ ] **Etapa 1: Escrever testes de pagina**

Criar clientes e dois chamados sinteticos. Verificar `200`, nomes de cliente, rotulos separados “Execucao tecnica” e “Situacao administrativa”, cinco etapas, ordem cronologica dos eventos e historico das transicoes administrativas com etapa, estado anterior, estado novo, observacao e acao confirmada. Verificar `404` para ID inexistente e link `/web/board/{task_id}/edit` para lembrete vinculado.

- [ ] **Etapa 2: Confirmar falha por rotas ausentes**

```bash
.venv/bin/pytest tests/test_service_routes.py -q
```

Esperado: `404` nas novas rotas.

- [ ] **Etapa 3: Implementar router e templates**

As rotas chamam apenas `list_service_calls` e `get_service_call`. Os templates estendem `base.html`, reutilizam `.page-header`, `.panel`, `.badge`, `.table-wrap` e as cores existentes. Nao incluir formularios, botoes de alteracao ou JavaScript mutavel.

Na pagina de detalhe, o estado atual de cada etapa vem de `ServiceWorkflowStep`; o historico auditavel vem de `ServiceWorkflowTransition`. A interface nao deve reconstruir o historico comparando apenas os estados atuais nem ocultar transicoes anteriores.

Adicionar “Servicos” ao menu junto de “Quadro” e “Assistente”, com estado ativo para `/web/services`.

- [ ] **Etapa 4: Executar testes de rotas e paginas existentes**

```bash
.venv/bin/pytest tests/test_service_routes.py tests/test_dashboard_routes.py tests/test_board_statuses.py -q
```

Esperado: todos passam.

---

### Tarefa 4: Contratos do assistente, capacidades e evidencia

**Arquivos:**

- Modificar: `app/assistant/contracts.py`
- Modificar: `app/assistant/provider.py`
- Modificar: `app/assistant/ollama.py`
- Modificar: `app/assistant/capabilities.py`
- Modificar: `app/assistant/evidence.py`
- Modificar: `tests/test_assistant_contracts.py`
- Criar/expandir: `tests/test_assistant_service_records.py`

**Comandos produzidos:**

```python
class ServiceQueryCommand(BaseModel):
    tool: Literal["consultar_servicos"] = "consultar_servicos"
    client: str | None = Field(default=None, max_length=255)
    execution_status: ServiceExecutionStatus | None = None
    administrative_status: ServiceAdministrativeStatus | None = None
    pending_only: bool = False
    limit: int = Field(default=20, ge=1, le=50)

class ServiceEventDraftCommand(BaseModel):
    tool: Literal["registrar_evento_servico"] = "registrar_evento_servico"
    client: str | None = Field(default=None, max_length=255)
    service_call_id: int | None = Field(default=None, ge=1)
    force_new_call: bool = False
    summary: str | None = Field(default=None, max_length=500)
    event_type: ServiceEventType | None = None
    occurred_on: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=4000)
    execution_completed_explicitly: bool = False
    step_changes: list[ServiceStepChange] = Field(default_factory=list, max_length=5)

class ServiceDraftCorrectionCommand(BaseModel):
    tool: Literal["corrigir_registro_servico"] = "corrigir_registro_servico"
    event_id: int | None = Field(default=None, ge=1)
    occurred_on: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=4000)
    event_type: ServiceEventType | None = None
    client: str | None = Field(default=None, max_length=255)
    cancel_step_changes: bool = False

class ServiceReminderDraftCommand(BaseModel):
    tool: Literal["criar_lembretes_servico"] = "criar_lembretes_servico"
    service_call_id: int | None = Field(default=None, ge=1)
    reminders: list[ServiceReminderItemCommand] = Field(min_length=1, max_length=5)
```

`ServiceReminderItemCommand` contem `title`, `description`, `status`, `due_date` como expressao falada, `responsible` como nome cadastrado e `step_type`. O backend resolve nome e data e so entao cria `ServiceReminderCreate`; o modelo nao fornece `user_id`.

`ProviderToolResult.tool` passa a aceitar `consultar_servicos`. `ProviderPendingAction.action_type` passa a aceitar `register_service_event`, `correct_service_event` e `create_service_reminders`.

- [ ] **Etapa 1: Escrever testes de contratos e lista permitida**

Verificar rejeicao de campo extra, ID menor que 1, mais de cinco mudancas/lembretes e estado fora dos literais. Verificar que `_ollama_tools` inclui somente ferramentas permitidas na rodada.

- [ ] **Etapa 2: Escrever testes de evidencia**

Casos obrigatorios: `test_cannot_claim_service_query_without_tool_evidence`, `test_cannot_claim_service_registration_before_confirmed_result`, `test_failed_service_query_cannot_be_called_successful` e `test_finance_document_tax_and_email_writes_remain_blocked`.

- [ ] **Etapa 3: Confirmar falhas**

```bash
.venv/bin/pytest tests/test_assistant_contracts.py tests/test_assistant_service_records.py -q
```

Esperado: falhas pela uniao de comandos e evidencias ausentes.

- [ ] **Etapa 4: Implementar contratos compactos e capacidades**

Adicionar `service_read` e mudar `service_write` para `available`, com descricao explicita de confirmacao. Manter `document_write`, `finance_write`, `email_send` e `tax_issue` indisponiveis.

Remover `servico`/`atendimento` apenas dos bloqueios genericos que agora colidirem com as ferramentas implementadas; preservar bloqueios de geracao documental, fiscal, financeiro e envio. Compactar resultados de servico enviados ao Ollama para no maximo dez chamados e campos: ID, cliente, resumo, estados, proxima pendencia e datas — nunca o historico inteiro.

- [ ] **Etapa 5: Executar testes focados**

```bash
.venv/bin/pytest tests/test_assistant_contracts.py tests/test_assistant_service_records.py tests/test_assistant_email_grounding.py -q
```

Esperado: contratos e protecoes passam; protecoes de e-mail nao regridem.

---

### Tarefa 5: Adaptador conversacional, rascunho e confirmacao

**Arquivos:**

- Criar: `app/assistant/service_records.py`
- Modificar: `app/assistant/service.py`
- Expandir: `tests/test_assistant_service_records.py`

**Produz:**

```python
@dataclass(frozen=True)
class ServiceQueryExecution:
    reply: AssistantReply
    result: ProviderToolResult | None = None
```

`AssistantServiceRecordAdapter` expoe `execute_query(conversation_id, command) -> ServiceQueryExecution`, `prepare_event(conversation_id, request_id, command) -> AssistantReply`, `correct_draft(conversation_id, request_id, command) -> AssistantReply`, `prepare_reminders(conversation_id, request_id, command) -> AssistantReply` e `confirm(action) -> AssistantReply`.

- [ ] **Etapa 1: Escrever casos conversacionais vermelhos**

Com `QueueProvider`, cobrir `test_inspection_draft_does_not_claim_execution`, `test_finished_repair_asks_only_for_missing_client_or_call`, `test_ambiguous_client_asks_short_question`, `test_multiple_open_calls_ask_which_call`, `test_single_open_call_is_shown_in_confirmation`, `test_force_new_call_does_not_reuse_open_call`, `test_missing_date_proposes_today_with_absolute_date`, `test_cancel_service_draft_writes_nothing`, `test_confirmed_service_action_is_idempotent` e `test_retry_after_commit_reconciles_service_result`.

Para “fui à empresa Alfa, mas só fiz uma inspeção”, afirmar no rascunho `evento=Inspecao`, `execucao=Não iniciada` e ausencia de `execution_completed` no banco antes e depois da confirmacao.

- [ ] **Etapa 2: Confirmar as falhas**

```bash
.venv/bin/pytest tests/test_assistant_service_records.py -q
```

Esperado: ferramentas ainda nao roteadas.

- [ ] **Etapa 3: Implementar grounding deterministico**

O adaptador deve validar o comando contra o texto atual:

- palavras de inspecao com “so/somente/nao consertei” prevalecem sobre qualquer inferencia de execucao;
- `execution_completed` exige expressao explicita de conclusao no texto e `execution_completed_explicitly=True`;
- cliente, data, etapa, defeito, peca, valor e trabalho nao citados nao podem ser adicionados pelo modelo;
- data ausente resolve para hoje somente como default exibido no rascunho;
- chamada a ID exige que o chamado exista, pertença ao cliente resolvido e tenha sido citado ou apresentado na conversa;
- duas ou mais correspondencias geram esclarecimento, sem acao persistida.

- [ ] **Etapa 4: Generalizar a acao pendente sem quebrar tarefas**

Manter `AssistantAction` como envelope. `action_type` determina o executor em `confirm_action`:

```python
CONFIRMERS = {
    "create_task": self._confirm_task_action,
    "register_service_event": self._confirm_service_event_action,
    "correct_service_event": self._confirm_service_correction_action,
    "create_service_reminders": self._confirm_service_reminders_action,
}
```

A reivindicacao atomica `pending -> executing`, o hash do token, a reconciliacao de `executed` e o cancelamento existentes continuam comuns. O resultado guarda IDs estruturados, nunca raciocinio do modelo.

- [ ] **Etapa 5: Implementar consulta e continuidade**

`consultar_servicos` chama o dominio antes de responder e produz `ProviderToolResult` com `evidence_id` aleatorio, `state` derivado da consulta e `payload` compacto. Persistir nos detalhes visuais apenas os campos sinteticos exibidos. Referencias como “esse chamado” e “o segundo” so resolvem IDs presentes nos resultados anteriores da conversa.

- [ ] **Etapa 6: Executar testes de assistente e regressao de tarefas**

```bash
.venv/bin/pytest tests/test_assistant_service_records.py tests/test_assistant_service.py tests/test_assistant_routes.py -q
```

Esperado: novos casos e confirmacoes de tarefas existentes passam.

---

### Tarefa 6: Etapas administrativas, correcoes e lembretes confirmados

**Arquivos:**

- Modificar: `app/assistant/service_records.py`
- Modificar: `app/assistant/service.py`
- Expandir: `tests/test_assistant_service_records.py`

- [ ] **Etapa 1: Escrever testes de etapas e correcao**

Cobrir `test_proposal_required_can_precede_execution`, `test_proposal_not_applicable_is_preserved`, `test_completed_execution_can_keep_report_pending`, `test_unknown_to_pending_to_waiting_customer_is_visible_in_history`, `test_multi_step_confirmation_has_one_event_and_one_transition_per_step`, `test_repeated_multi_step_confirmation_does_not_duplicate_transitions`, `test_persisted_correction_appends_and_never_updates_original`, `test_correction_rebuilds_technical_and_administrative_projection`, `test_draft_correction_invalidates_old_confirmation_token` e `test_old_confirmation_after_correction_returns_conflict`.

- [ ] **Etapa 2: Escrever testes de lembretes**

Criar um chamado tecnicamente concluido com relatorio e proposta pendentes. Pedir lembretes, confirmar e verificar duas `Task`, dois `ServiceTaskLink` e URLs do quadro. Repetir a confirmacao e verificar que as contagens permanecem duas.

- [ ] **Etapa 3: Implementar atualizacao append-only e lote atomico**

Uma acao exclusivamente administrativa cria um evento `note`; uma acao operacional usa seu tipo operacional. Em ambos os casos, cada etapa alterada cria `ServiceWorkflowTransition(step_type, previous_status, new_status, observation, service_event_id, assistant_action_id)`. Uma acao que altera relatorio e proposta cria um evento e duas transicoes. O replay consulta primeiro o evento pelo `assistant_action_id` e devolve as transicoes ja existentes, sem reaplicar a projecao. Uma retificacao administrativa cria novas transicoes a partir dos estados atualmente projetados e conserva as anteriores; corrigir apenas o fato operacional nao desfaz implicitamente mudancas administrativas vinculadas a acao antiga.

Correcao persistida cria `correction` com `supersedes_event_id`, valida que o alvo e a folha atual e chama `rebuild_current_projection` na mesma transacao. A resposta de confirmacao deve mostrar o estado tecnico e administrativo recomposto, nao o estado anterior ao evento corrigido. Lembretes sao preparados com no maximo cinco itens, passam pela validacao de cliente/responsavel/prazo do quadro e sao gravados numa unica transacao.

- [ ] **Etapa 4: Executar testes focados**

```bash
.venv/bin/pytest tests/test_assistant_service_records.py tests/test_service_record_service.py tests/test_board_assistant_validation.py -q
```

Esperado: todos passam, inclusive as validacoes antigas do quadro.

---

### Tarefa 7: Respostas, links e caminho de voz

**Arquivos:**

- Modificar: `app/assistant/contracts.py`
- Modificar: `app/static/assistant_chat.js`
- Modificar: `tests/js/assistant_chat.test.mjs`
- Modificar: `tests/test_assistant_voice_routes.py`
- Modificar: `tests/js/assistant_voice.test.mjs`

**Resposta estendida:**

```python
class AssistantReply(BaseModel):
    # campos existentes preservados
    service_call_id: int | None = None
    service_url: str | None = None
    task_urls: list[str] = Field(default_factory=list)
```

- [ ] **Etapa 1: Escrever testes de renderizacao**

Verificar que uma resposta de sucesso renderiza “Abrir chamado” apontando para `/web/services/7` e cada tarefa em `task_urls`, sem enviar envelopes internos ao TTS.

- [ ] **Etapa 2: Escrever regressao de voz**

No teste de JavaScript, simular transcricao “Fui à Alfa, mas só fiz uma inspeção” e verificar que o texto enviado a `/api/assistant/messages` e exatamente a transcricao. No teste Python, verificar que transcricao e sintese continuam fora do event loop e que nenhuma rota de voz grava servico diretamente.

- [ ] **Etapa 3: Implementar links sem novo fluxo de escrita**

O navegador continua chamando apenas `/api/assistant/messages` e os endpoints atuais de confirmacao/cancelamento. Adicionar links a partir dos campos retornados; nenhuma chamada direta de criacao de servico sera exposta ao frontend.

- [ ] **Etapa 4: Executar testes Python e Node**

```bash
.venv/bin/pytest tests/test_assistant_voice_routes.py tests/test_assistant_voice_policy.py -q
node --test tests/js/assistant_chat.test.mjs tests/js/assistant_voice.test.mjs
```

Esperado: todos passam.

---

### Tarefa 8: Isolamento, dados sinteticos e validacao local real

**Arquivos:**

- Criar: `scripts/seed_assistant_service_validation.py`
- Criar: `tests/test_assistant_service_ollama_live.py`
- Modificar: `scripts/run_assistant_8011_yahoo.sh`
- Modificar: `docs/assistente/execucao.md`
- Criar: `docs/assistente/validacao-servicos-local.md`

- [ ] **Etapa 1: Implementar a trava de isolamento do seed**

O script deve exigir `SERVICE_VALIDATION_ALLOW_SYNTHETIC_SEED=1` e recusar banco que nao seja SQLite ou cujo caminho nao esteja sob `/tmp/ad-balancas-services-8011/`. Ele cria apenas:

- `Alfa Servicos Sintetica`;
- `Alfa Industria Sintetica`;
- `Beta Comercio Sintetica`;
- `Carlos Teste`, ativo;
- chamados e tarefas marcados claramente como sinteticos.

O script nao le, imprime ou altera configuracoes Yahoo.

- [ ] **Etapa 2: Configurar somente a 8011 para o banco de validacao**

No launcher, manter `APP_ENV_FILE=.env.yahoo.local`, Ollama e voz atuais. Trocar somente os caminhos da instancia 8011 para:

```bash
DATABASE_URL=sqlite:////tmp/ad-balancas-services-8011/app.sqlite3
OUTPUT_DIR=/tmp/ad-balancas-services-8011/output
TEMPLATE_DOC_PATH=/tmp/ad-balancas-services-8011/doc_templates/proposta_template.docx
APP_HOST=127.0.0.1
APP_PORT=8011
```

Nao mostrar usuario ou senha de aplicativo e nao tocar na porta 8000.

- [ ] **Etapa 3: Criar teste Ollama real opt-in**

Marcar os casos com `pytest.mark.skipif(os.getenv("RUN_OLLAMA_LIVE") != "1", reason="Ollama real requer opt-in")`. Usar banco temporario e clientes sinteticos. Casos:

1. inspecao sem reparo;
2. inicio e conclusao explicita;
3. cliente Alfa ambiguo;
4. proposta necessaria e dispensada;
5. relatorio pendente;
6. correcao antes da confirmacao;
7. cancelamento;
8. oferta e confirmacao de lembrete.

O teste confirma somente rascunhos sinteticos e nunca usa mensagens da caixa real.

- [ ] **Etapa 4: Executar suite automatizada completa**

```bash
.venv/bin/pytest -q
node --test tests/js/*.test.mjs
```

Esperado: suite completa passa. Testes live permanecem pulados sem `RUN_OLLAMA_LIVE=1` e nao podem ser relatados como validacao real.

- [ ] **Etapa 5: Executar validacao real controlada**

Depois de confirmar que `127.0.0.1:11434` ja responde, executar:

```bash
RUN_OLLAMA_LIVE=1 .venv/bin/pytest tests/test_assistant_service_ollama_live.py -q -s
SERVICE_VALIDATION_ALLOW_SYNTHETIC_SEED=1 \
DATABASE_URL=sqlite:////tmp/ad-balancas-services-8011/app.sqlite3 \
.venv/bin/python scripts/seed_assistant_service_validation.py
```

Registrar modelo, tempos, resultados e erros sem conteudo de e-mail, credenciais ou raciocinio interno.

- [ ] **Etapa 6: Reiniciar somente a instancia 8011**

Identificar o PID que escuta `127.0.0.1:8011`, encerrar somente esse processo, iniciar `./scripts/run_assistant_8011_yahoo.sh` e verificar:

```bash
curl --fail --silent http://127.0.0.1:8011/healthz
curl --fail --silent http://127.0.0.1:8011/api/assistant/voice/status
curl --fail --silent http://127.0.0.1:8000/healthz
```

Esperado: as duas portas respondem; 8011 usa o banco sintetico; 8000 permanece intacta.

- [ ] **Etapa 7: Executar roteiro manual por voz**

Abrir `http://127.0.0.1:8011/web/assistente` e testar, nesta ordem:

1. “Fui à Alfa, mas só fiz uma inspeção.” — deve perguntar qual Alfa.
2. “Alfa Indústria Sintética.” — deve mostrar inspeção, data absoluta e execução não iniciada.
3. “Pode registrar.” — deve salvar um chamado e um evento.
4. “Comecei o conserto desse chamado.” — deve preparar `execution_started`.
5. “Terminei o conserto; o relatório ficou pendente e não precisa de proposta.” — deve separar conclusão técnica, relatório pendente e proposta dispensada.
6. “Na verdade, a visita foi ontem.” — deve preparar correção append-only.
7. “Crie lembretes para o relatório e a nota fiscal.” — deve mostrar outro rascunho e aguardar confirmação.
8. Repetir “Pode criar.” — não pode duplicar tarefas.
9. Dizer “Cancela” em um novo rascunho — não pode gravar.

Depois do passo 5, conferir no detalhe do chamado que a unica confirmacao produziu um evento e uma transicao para cada etapa alterada, com os estados anterior e novo. Depois do passo 6, conferir que o evento original continua visivel, a correcao aparece como novo evento e os estados tecnico e administrativo exibidos correspondem a projecao recomposta.

Comparar a resposta falada com o historico visual e abrir os links do chamado e do quadro.

- [ ] **Etapa 8: Documentar evidencias e pendencias**

`docs/assistente/validacao-servicos-local.md` deve separar:

- testes automatizados simulados;
- Ollama real com dados sinteticos;
- STT/Piper reais;
- roteiro humano ainda pendente ou executado;
- Yahoo preservado em somente leitura, sem afirmar que mensagens foram consultadas neste teste;
- Ryzen ainda nao validado;
- ausencia de migracao operacional.

---

## Matriz de validacao final

| Criterio | Evidencia exigida |
|---|---|
| Inspecao nao conclui execucao | teste de dominio + conversa Ollama sintetica |
| Eventos distintos no mesmo chamado | duas linhas `ServiceEvent` e pagina de detalhe |
| Conclusao tecnica separada | `execution_status=completed`, `administrative_status=open` |
| Proposta flexivel | testes antes/depois da execucao e `not_applicable` |
| Relatorio pendente | etapa visivel na consulta, pagina e resposta |
| Cliente/chamado ambiguo | esclarecimento sem `ServiceCall` ou `ServiceEvent` novo |
| Auditoria administrativa estruturada | uma acao confirmada gera um evento e uma transicao por etapa, contendo etapa, estado anterior, estado novo, observacao e `assistant_action_id` |
| Sequencia de estados administrativos | `unknown -> pending -> waiting_customer` produz duas transicoes e projecao final `waiting_customer` |
| Correcao preserva historico e recompõe estado | evento original intacto + cadeia por `supersedes_event_id`; correcao de conclusao para inspecao resulta em `in_progress` com inicio anterior ou `not_started` sem ele |
| Imutabilidade do historico | ORM e SQL direto rejeitam `UPDATE`/`DELETE`; exclusao do chamado falha sem remover eventos/transicoes |
| Idempotencia | repeticao mantem IDs e contagens de evento, transicoes, chamado e tarefas |
| Lembretes confirmados | tarefas reais + `ServiceTaskLink` + links |
| Cancelamento | nenhuma gravacao de dominio |
| Voz e texto | mesma rota de mensagem e mesmo fluxo de confirmacao |
| Isolamento | caminho do banco 8011 documentado e health da 8000 preservado |
| Limites externos | propostas, financeiro e Yahoo sem escrita |

## Condicao de conclusao

A implementacao so pode ser declarada concluida quando os testes focados e a regressao passarem, incluindo os contratos de transicao administrativa, recomposicao de projecoes e imutabilidade por ORM e SQL direto. A validacao Ollama sintetica deve ter resultado registrado, a 8011 deve responder com o banco isolado e a porta 8000 deve continuar saudavel. A protecao equivalente em PostgreSQL deve ser executada em ambiente isolado ou registrada explicitamente como pendente; nao pode ser inferida do resultado em SQLite. Teste humano de microfone e desempenho no Ryzen devem ser descritos como pendentes se nao forem efetivamente executados.
