# Tarefa 5 — adaptador conversacional de chamados

## Entrega

- `app/assistant/service_records.py`: consulta real limitada a dez chamados com `ProviderToolResult` e ID de evidência; preparação de rascunho de evento; resolução de cliente e chamado; esclarecimento com contexto preservado; validação determinística de tipo, data, descrição e etapas citadas; confirmação que chama `service_record_service.register_event(commit=False)`.
- `app/assistant/service.py`: roteamento de consulta e registro pelo mesmo `handle_message` usado por texto e voz; `AssistantAction` pendente, confirmação, cancelamento, replay e resultado estruturado do serviço; controles diretos como `confirmo`, `pode registrar` e `cancela`. A transição de ação e a escrita do domínio usam o mesmo commit.
- `tests/test_assistant_service_records.py`: testes conversacionais em SQLite isolado para inspeção sem conclusão, cliente e chamado ambíguos, reutilização ou novo chamado, data local, cancelamento, confirmação idempotente, retry, esclarecimento, consulta com evidência, grounding e não conversão de serviço em tarefa.

## RED/GREEN

- RED inicial: `PYTHONPATH=. .venv/bin/pytest tests/test_assistant_service_records.py -q --disable-warnings` — **7 failed, 14 passed**, pois os comandos de serviço ainda não eram roteados.
- GREEN inicial após adaptador: mesmo comando — **21 passed**.
- RED adicional para data relativa `ontem`: **1 failed, 26 passed**; GREEN após resolver no fuso local.
- RED adicional para filtro de cliente inventado em consulta: **1 failed, 29 passed**; GREEN após validação do filtro contra o pedido.
- RED adicional para contexto de conclusão após esclarecimento: teste isolado **1 failed**; GREEN após preservar o texto anterior.
- RED adicional para etapa administrativa não citada: **1 failed, 32 passed**; GREEN após filtrar etapas pelo texto.
- RED adicional para `pode registrar`: **1 failed, 34 passed**; GREEN após controle direto.
- RED adicional para tipo de evento inventado: teste isolado **1 failed**; GREEN após validação de pistas explícitas.
- Regressão focada: `PYTHONPATH=. .venv/bin/pytest tests/test_assistant_service_records.py tests/test_assistant_service.py tests/test_assistant_routes.py tests/test_assistant_contracts.py tests/test_assistant_email_grounding.py tests/test_assistant_email_service.py tests/test_assistant_ollama.py -q --disable-warnings` — **188 passed, 1337 warnings** (avisos de deprecação preexistentes), saída 0.
- `git diff --check` — saída 0.

## Limites

- Esta tarefa integra consulta e registro de eventos. Correção persistida e lote de lembretes são da Tarefa 6 e ainda não foram ligados ao adaptador.
- Nenhum Ollama, Whisper ou Piper real foi executado. Nenhum commit, push, deploy, banco operacional, Yahoo ou processo das portas 8000/8011 foi tocado.
