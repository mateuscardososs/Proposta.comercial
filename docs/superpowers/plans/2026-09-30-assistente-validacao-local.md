# Assistente Local Real Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Executar o assistente com Ollama real e validar consultas, criação, correção, confirmação, cancelamento e recuperação em banco isolado.

**Architecture:** O modelo apenas classifica a conversa em comandos Pydantic. `AssistantService` resolve entidades, mantém um único rascunho pendente e executa mutações idempotentes; `AssistantRequest` fornece lease persistente para retries. Um runner de validação chama os endpoints reais contra SQLite temporário e Ollama nativo.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, SQLite, HTTPX, Ollama 0.35, Qwen3 4B Instruct Q4_K_M e pytest.

## Global Constraints

- Usar somente `.venv/bin/python` para comandos Python.
- Não abrir `.env`, bancos, documentos ou volumes reais.
- Manter Ollama em loopback e sem recursos de nuvem.
- Não adicionar ferramentas para exclusão, atendimento, financeiro, documentos ou voz.
- Toda mudança comportamental começa por teste falhando.
- Não fazer push, deploy ou exposição externa.

---

### Task 1: Comandos conversacionais seguros

**Files:**
- Modify: `app/assistant/contracts.py`
- Modify: `app/assistant/ollama.py`
- Test: `tests/test_assistant_ollama.py`
- Test: `tests/test_assistant_contracts.py`

**Interfaces:**
- Produces: `ConfirmActionCommand`, `CancelActionCommand`, `TaskDraftCorrectionCommand` dentro de `AssistantCommand`.
- Consumes: histórico limitado de `ProviderMessage` e JSON Schema já usado por `OllamaProvider`.

- [ ] Escrever testes que rejeitem campos extras e validem os três comandos novos.
- [ ] Executar os testes e observar falha por tipos ausentes.
- [ ] Implementar modelos com `extra="forbid"`, flags explícitas de limpeza e prompt de limites/segurança.
- [ ] Executar testes de contrato e adaptador até passarem.

### Task 2: Correção, confirmação e cancelamento por texto

**Files:**
- Modify: `app/assistant/service.py`
- Test: `tests/test_assistant_service.py`
- Test: `tests/test_assistant_routes.py`

**Interfaces:**
- Consumes: comandos da Task 1 e última `AssistantAction` pendente da conversa.
- Produces: prévia corrigida com token rotacionado, confirmação/cancelamento textual e respostas idempotentes.

- [ ] Escrever testes de confirmação e cancelamento por mensagem.
- [ ] Executar e observar falha porque os comandos não são despachados.
- [ ] Implementar despacho interno sem expor token ao provedor.
- [ ] Escrever teste de correção de título, prazo, cliente e responsável com invalidação do token antigo.
- [ ] Executar e observar falha por correção ausente.
- [ ] Implementar patch validado sobre a ação pendente e gerar nova prévia curta.
- [ ] Executar testes de serviço e rotas.

### Task 3: Lease persistente e recuperação

**Files:**
- Modify: `app/models.py`
- Modify: `app/config.py`
- Modify: `app/assistant/service.py`
- Modify: `app/routers/assistant.py`
- Test: `tests/test_assistant_service.py`
- Test: `tests/test_assistant_schema_compatibility.py`

**Interfaces:**
- Produces: modelo `AssistantRequest` e parâmetro `request_lease_seconds` de `AssistantService`.
- Consumes: `request_id`, mensagem persistida e resposta cacheada.

- [ ] Escrever teste de schema aditivo e de requisição com lease válido.
- [ ] Escrever teste em que lease expirado é tomado e o provedor é chamado exatamente uma vez.
- [ ] Escrever teste em que request concluído retorna cache sem nova chamada.
- [ ] Executar e observar as falhas esperadas.
- [ ] Implementar a tabela independente e claim condicional por timestamp.
- [ ] Marcar request completo na mesma transação da resposta.
- [ ] Executar testes de recuperação e regressão do assistente.

### Task 4: Runner real isolado e configuração

**Files:**
- Create: `scripts/validate_assistant_local.py`
- Modify: `.env.example`
- Modify: `docs/assistente/execucao.md`
- Test: `tests/test_assistant_local_runner.py`

**Interfaces:**
- Consumes: URL FastAPI temporária, `OLLAMA_MODEL`, diretório temporário e vinte casos sintéticos.
- Produces: relatório JSON/Markdown com comando observado, resposta, duração e mutações verificadas.

- [ ] Escrever teste do seed sintético e da serialização de resultados sem iniciar Ollama.
- [ ] Executar e observar falha por runner ausente.
- [ ] Implementar seed, cliente HTTP, medições monotônicas e invariantes de banco.
- [ ] Documentar variáveis nativas e Docker sem expor o servidor.
- [ ] Executar os testes do runner.

### Task 5: Validação real e evidências

**Files:**
- Create: `docs/assistente/validacao-local.md`
- Modify: `docs/assistente/plano.md`

**Interfaces:**
- Consumes: Ollama nativo, modelo instalado, app temporária e runner da Task 4.
- Produces: evidência reproduzível da validação local.

- [ ] Confirmar `ollama list`, `/api/tags`, modelo/quantização e bind de loopback.
- [ ] Executar o teste de integração real somente leitura.
- [ ] Iniciar FastAPI com SQLite e diretórios temporários.
- [ ] Executar os vinte casos, incluindo conversa com esclarecimento, correção e confirmação.
- [ ] Registrar tempos reais, interpretações incorretas, correções e pendências.
- [ ] Executar suíte completa, Ruff, `compileall`, `git diff --check` e conferir Git.
