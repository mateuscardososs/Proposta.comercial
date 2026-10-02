# Tarefa 4 — contratos, capacidades e evidencia do assistente

## Entrega

- Quatro comandos Pydantic de servico: consulta, registro de evento, correcao e lote de lembretes. Campos inesperados, IDs invalidos, estados fora dos literais e lotes com mais de cinco itens sao rejeitados. O modelo nao fornece `user_id`.
- `ProviderToolResult` aceita `consultar_servicos`; `ProviderPendingAction` aceita as tres acoes pendentes de servico.
- `service_read` e `service_write` estao disponiveis; escrita exige confirmacao. Escrita de documento, financeira e e-mail, e emissao fiscal continuam indisponiveis.
- As novas ferramentas so aparecem ao Ollama quando estao na allowlist da rodada. O conjunto padrao anterior permanece ate a integracao da Tarefa 6.
- Resultado de consulta enviado ao Ollama e limitado a dez chamados, a campos de identificacao/estado/pendencia/data e a textos curtos. Historico completo e outros campos nao entram no prompt.
- Alegacoes de consulta de servico exigem resultado da consulta na solicitacao; consulta com estado `failed` nao sustenta sucesso. Alegacoes conversacionais de registro continuam rejeitadas antes de um resultado confirmado. Os bloqueios de escrita financeira, documental, fiscal e de e-mail permanecem.

## RED/GREEN

- Comando do plano `.venv/bin/pytest tests/test_assistant_contracts.py tests/test_assistant_service_records.py -q`: nao coletou porque o runner local nao incluiu a raiz do projeto no `sys.path` (`ModuleNotFoundError: app`). Os comandos seguintes usam `PYTHONPATH=.`.
- `PYTHONPATH=. .venv/bin/pytest tests/test_assistant_contracts.py tests/test_assistant_service_records.py -q`: **17 falhas, 17 passes**, antes da implementacao. As falhas apontaram comandos/capacidades ausentes, `ProviderToolResult` sem servico e alegacoes sem evidencia.
- `PYTHONPATH=. .venv/bin/pytest tests/test_assistant_service_records.py::test_service_clarification_requires_service_tools_in_the_round -q`: falha esperada antes de restringir a rodada.
- `PYTHONPATH=. .venv/bin/pytest tests/test_assistant_service_records.py::test_explicit_task_about_a_service_is_not_blocked -q`: falha esperada antes de distinguir tarefa explicita de registro de servico.
- `PYTHONPATH=. .venv/bin/pytest tests/test_assistant_service_records.py::test_large_service_result_is_bounded_before_ollama_prompt -q`: falha esperada antes de limitar strings do resultado.
- `PYTHONPATH=. .venv/bin/pytest tests/test_assistant_service_records.py::test_ollama_describes_service_pending_action_as_service_draft -q`: falha esperada antes de instruir o provedor sobre rascunho de servico pendente.
- `PYTHONPATH=. .venv/bin/pytest tests/test_assistant_contracts.py tests/test_assistant_service_records.py tests/test_assistant_email_grounding.py tests/test_assistant_ollama.py tests/test_assistant_service.py tests/test_assistant_email.py tests/test_assistant_email_service.py tests/test_assistant_routes.py -q`: **167 passes**. Apenas avisos de deprecacao preexistentes de bibliotecas e APIs.

## Integracao posterior

O adaptador da Tarefa 5 fornece `ProviderToolResult.payload` com `count` e `service_calls`; cada item inclui as projecoes do chamado e os estados das etapas administrativas. A integracao subsequente coloca as ferramentas de servico na allowlist da rodada apropriada. `AssistantService`, rotas e paginas sao integrados nas tarefas 5 a 7.

Nenhum commit, push ou deploy foi feito.

## Revisao adicional e correcoes de grounding

A revisao independente identificou formas nao cobertas de alegacoes falsas (consulta negativa e registro passivo/plural), datas ISO verdadeiras rejeitadas, falso bloqueio de lembretes solicitados explicitamente e possibilidade de sobrescrever o discriminador `tool` dentro dos argumentos.

- RED: `PYTHONPATH=. .venv/bin/pytest tests/test_assistant_contracts.py -q -k 'service_claim_variants or reminder_task or override_the_authorized or service_result_date'` — 6 falhas reproduzidas.
- GREEN: o mesmo comando — 6 passed.
- Regressao: `PYTHONPATH=. .venv/bin/pytest tests/test_assistant_contracts.py tests/test_assistant_service_records.py tests/test_assistant_email_grounding.py tests/test_assistant_ollama.py -q` — 99 passed, apenas avisos de deprecacao preexistentes.

As alegacoes negativas agora tambem exigem resultado `consultar_servicos`; formas passivas/plurais de sucesso sao bloqueadas sem resultado persistido. Datas ISO do resultado sao comparadas na forma brasileira equivalente. Uma solicitacao explicita de tarefa/lembrete permite a ferramenta de quadro sem interpretar isso como registro do chamado. Os argumentos do modelo nao podem substituir o nome da ferramenta que passou pela allowlist.
