# Refatoração de apresentação, fila de mensagens e templates

> Execução incremental com subagent-driven-development; testes de caracterização antes da extração e revisão independente por etapa. Sem commits.

**Objetivo:** concluir as separações de responsabilidades restantes identificadas na apresentação do Assistente, na fila de e-mail e nos templates extensos, sem mudar comportamento.

**Arquitetura:** apresentação pura recebe resultados dos serviços atuais; consulta da fila fica em serviço SQLAlchemy específico; estilos/scripts existentes viram includes Jinja para conservar exatamente o HTML entregue. Orquestradores e routers conservam transações, ordem, URLs e contratos.

**Restrições globais:** preservar branch `refactor/safe-modularization`, mudanças locais e commits externos; não ler configurações privadas; nenhum acesso a dados operacionais, IMAP, SMTP, Gemini, STT/TTS reais; nenhuma instância adicional/restart; nenhuma migração, mudança de configuração, dependência, regra, mensagem, filtro, limite, ordenação ou confirmação. Não alterar autenticação. Nenhuma exclusão de arquivos ou testes existentes. Usar `apply_patch`. Nunca rodar pytest sem launcher seguro abaixo; nunca rodar duas suítes Python simultâneas (compartilham banco temporário).

## Etapa 6 — apresentação do resumo diário e agenda

Arquivos: `app/assistant/service.py`, novo `app/assistant/day_presentation.py`, novo `tests/test_assistant_day_presentation.py`.

Interfaces:

```python
present_daily_brief(conversation_id: int, brief: dict[str, object]) -> AssistantReply
task_agenda_message(plan: TaskDayPlan, schedule: DailySchedule, today: date) -> str
task_agenda_result(plan: TaskDayPlan, schedule: DailySchedule, today: date, duration_by_task: dict[int, int | None]) -> ProviderToolResult
```

`_execute_daily_brief` mantém chamada a `build_daily_brief` e passa o mesmo resultado ao apresentador. `_execute_task_agenda` mantém a ordem: buscar plano → calcular agenda → apresentar mensagem → consultar durações → construir evidência/resposta. Não adiantar consultas nem alterar `schedule.snapshot()`. Helpers movidos literalmente, sem normalizar mensagens. Não mover `_prepare_daily_schedule_snapshot`, confirmações, commit ou geração de documentos.

- [ ] Caracterizar saídas completas ou trechos/argumentos independentes relevantes ANTES: resumo vazio, sem disponibilidade, fonte parcial/indisponível, singular/plural, cliente/prazo, blocos fixos e estimados; agenda vazia e não alocada, cliente pendente, payload completo das tarefas/durações. Somente fixtures/banco sintético.
- [ ] Rodar novos testes + `test_assistant_daily_brief.py`, `test_assistant_service.py`, `test_daily_schedule_service.py` antes.
- [ ] Extrair somente apresentação, mantendo assinaturas dos métodos públicos e consultas em `service.py`.
- [ ] Rodar mesmo conjunto depois; AST dos métodos não tocados deve continuar idêntica. Ruff completo dos arquivos novos, E9/F no existente; compile/diff; revisão independente.

## Etapa 7 — consulta da fila de e-mails

Arquivos: `app/routers/pages.py`, novo `app/services/message_workbench_service.py`, novo `tests/test_message_workbench_service.py`.

Interface:

```python
get_message_workbench(db: Session, *, provider: str, mailbox_key: str) -> dict[str, object]
```

Retorna `sync_state`, três listas, `message_summary` e `action_drafts_by_email`. Extrair bloco de consultas de `messages_page` (state até message_summary) literalmente. Preservar provider/mailbox, três filtros com lógica SQL atual (inclusive NULL), ordem `received_at DESC, id DESC`, 100 mensagens por grupo, contagens de todos os registros, vínculos não nulos, escolha do último draft elegível por id ASC e atributo de apresentação `task_id`. Não fazer commit/flush explícito, reclassificar, sincronizar ou criar rascunhos. Não alterar rotas POST de review/pause/confirm; confirmação e configuração de provedor continuam no router. Manter labels/sugestões e HTML. Imports históricos ainda usados ou com consumidores devem permanecer compatíveis.

- [ ] Caracterizar pelo router original: separação operational/informational/review, fornecedor/categoria/baixa confiança, provider e mailbox isolados, 101 registros por grupo versus contagem completa, empates de data, latest draft elegível, links não nulos e nenhuma gravação por visualizar. Os cinco estados válidos de draft são todos elegíveis hoje; não inserir estado inválido violando o CHECK para inventar um caso inelegível. Preservar o filtro mesmo assim.
- [ ] Rodar novos testes + `test_today_routes.py`, `test_assistant_email_review.py`, `test_assistant_email_sync.py` antes.
- [ ] Extrair para serviço e reduzir router a consulta/flags/contexto/render; não introduzir consulta paralela nem mudar o formato do contexto.
- [ ] Rodar mesmo conjunto depois; lint novo/fatal existente; compile/diff; revisão independente. Não chamar Yahoo.

## Etapa 8 — componentes Jinja sem mudança visual

Arquivos: `app/templates_web/base.html`, `app/templates_web/proposal_form.html`, novos includes em `app/templates_web/components/`, novo `tests/test_template_characterization.py`.

Separar os blocos `<style>...</style>` e `<script>...</script>` do shell e os equivalentes do formulário em componentes coesos. Use includes Jinja; não criar requests novos de assets nem mover código para arquivos externos nesta etapa. Não alterar seletores, CSS, ordem dos scripts, CSRF wrapper, links, formulários, atributos ARIA ou eventos JS. Preservar whitespace do HTML renderizado.

Exemplo da técnica (o bloco original inclui sua indentação; o include não acrescenta espaços):

```jinja2
{% include "components/base_styles.html" %}
```

- [ ] ANTES, criar caracterização de HTML integral com hashes de saídas determinísticas (SHA256), request/session sintéticos e contexto completo: shell sem sessão e com sessão/CSRF/nav ativa, proposta nova e revisão com warning/dados. Obter hashes do código anterior, não gerá-los dinamicamente do código sob teste.
- [ ] Rodar caracterização e `test_today_routes.py`, `test_dashboard_routes.py`, `test_proposal_form.py`, `test_authentication.py` antes.
- [ ] Extrair blocos sem reescrever conteúdo, usando `apply_patch`; preservar newline final do componente e do include para saídas integrais idênticas.
- [ ] Rodar novamente, e suíte JS existente. Conferir includes via compilação Jinja e hashes integrais. Sem afirmar validação manual de navegador.
- [ ] Revisão independente das mudanças/templates/testes; nenhuma alteração em assets/voz/login.

## Fechamento

- [ ] Suíte Python completa, 36 JS, compilação, lint novo e global comparativo, diff-check.
- [ ] Comparar OpenAPI, DDL PostgreSQL compilado e hashes de autenticação com baseline. Não conectar ao PostgreSQL real.
- [ ] Revisão consolidada; atualizar relatório com todas as áreas auditadas: refatorada/coesa/motivo concreto de preservação/trabalho restante.
- [ ] Confirmar processo da 8013 sem disparar startup. O bloqueio de runtime é operacional: startup executa ajustes no banco e leitura Yahoo. Não confundir isso com bloqueio para continuar refatoração no checkout.

Launcher obrigatório (substituir apenas a lista de arquivos de teste):

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "-ra"]))'
```

Baseline desta continuação: 792 Python passed, 13 skipped; 36 JS passed; Ruff global 223 ocorrências. HEAD b2825e6, etapas 5 e documentação ainda com mudanças locais; preservar integralmente.
