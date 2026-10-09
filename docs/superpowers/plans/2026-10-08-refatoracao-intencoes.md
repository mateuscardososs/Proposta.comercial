# Separação de intenções determinísticas — plano de implementação

> Execução com subagent-driven-development, caracterização antes da extração e revisão independente. Sem commits; preservar todas as etapas anteriores.

**Objetivo:** retirar reconhecimento textual puro de `AssistantService` sem alterar decisões, prioridades ou efeitos.

**Arquitetura:** `app/assistant/intent_routing.py` contém somente funções puras que recebem texto e, quando aplicável, comando validado. `service.py` mantém aliases estáticos com nomes e assinaturas históricos; ordem de chamada e execução das ferramentas permanecem intactas. Sem classe genérica de router, dependência nova ou consulta ao banco.

**Restrições:** manter branch `refactor/safe-modularization` e alterações existentes; não ler configuração privada, não consultar dados reais, não chamar provedores/IMAP/SMTP, não reiniciar aplicação, não alterar schema, arquivos operacionais, regras, mensagens, regex ou limites. Login intocado.

## Etapa 5 — intenções puras

Arquivos: modificar `app/assistant/service.py`; criar `app/assistant/intent_routing.py` e `tests/test_assistant_intent_routing.py`.

Extrair somente estes métodos estáticos, removendo o prefixo `_` no módulo de destino:

- `_ground_task_query`, `_ground_email_query`;
- `_direct_email_query`, `_direct_document_query`, `_direct_board_query`, `_direct_daily_brief_request`;
- `_direct_service_return_query`, `_direct_service_report_request`, `_direct_service_report_correction`;
- `_direct_schedule_save_request`, `_message_mentions_date`.

Cada método conserva corpo/assinatura; o service expõe, por exemplo,
`_direct_email_query = staticmethod(intent_routing.direct_email_query)`.
Não mover os três validadores de proibição/escopo que referenciam `AssistantService`:
essas chamadas continuam passando pelo mesmo alias, mantendo substituições existentes.

- [x] Caracterizar cada detector pelo alias histórico antes de mover: e-mail indireto/categorias/escopo de tarefas; documento versus geração; resumo diário versus quadro; retorno; preparação/correção de relatório; solicitação de salvar agenda; datas; grounding com comando intacto versus cópia. Casos positivos e negativos e comparação integral de argumentos, sem I/O.
- [x] Executar novos testes e testes existentes de serviço/resumo/busca/relatório/agenda antes da extração, com configuração privada desabilitada.
- [x] Extrair corpos literalmente, manter aliases estáticos e chamadas atuais. Conferir equivalência AST e ausência de imports de DB/provedor concreto no novo módulo.
- [x] Executar testes focados, lint novo/fatal existente, compilação, diff-check e revisão independente.
- [x] Reexecutar suíte completa isolada e JavaScript; comparar contratos HTTP/schema/auth; atualizar relatório e estado da 8013 sem reiniciar.

Launcher obrigatório de testes:

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "tests/test_assistant_intent_routing.py", "tests/test_assistant_service.py", "tests/test_assistant_daily_brief.py", "tests/test_assistant_document_search.py", "tests/test_assistant_service_report.py", "tests/test_daily_schedule_service.py"]))'
```

Os testes devem descrever comportamento observado, não ampliar o vocabulário nem corrigir limitações descobertas. Problemas anteriores ficam registrados separadamente. Nenhum teste existente será removido.

## Evidências da execução

- 43 casos novos; conjunto focado: 151 passed antes/depois, mesmos 2082 avisos.
- Revisão independente da etapa: spec PASS, qualidade APPROVE; contagem documental corrigida de 41 para 43.
- 11 corpos/assinaturas extraídos idênticos por AST; os 62 métodos restantes continuam iguais.
- Suíte completa: 792 passed, 13 skipped, 6026 avisos, 86,11 s. JS: 36 passed.
- Novo módulo e novos testes passam lint completo; service passa E9/F; global mantém 223 ocorrências preexistentes. Compilação e diff-check aprovados.
- OpenAPI/DDL/auth com hashes idênticos aos anteriores; 97 rotas e 34 tabelas. Nenhuma conexão ao PostgreSQL operacional.
- HEAD avançou externamente para b2825e6 incorporando etapas anteriores; preservado. Nenhum commit pelo agente.
- 8013 segue sem listener; não foi reiniciada devido aos efeitos de startup. Revisão consolidada final APPROVE, sem achados pendentes; somente inspeção de código, sem alegar validação operacional.
