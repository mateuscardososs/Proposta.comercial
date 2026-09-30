# Correcao Conversacional do Assistente Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o assistente conversar naturalmente, consultar o quadro quando necessario e reagir de forma confiavel no chat e no inicio da voz.

**Architecture:** Ollama continua escolhendo exatamente uma ferramenta validada por turno, agora incluindo `responder_conversa`. Chat e voz ganham bootstraps independentes; o chat possui timeout e retry idempotente, e a voz consome sua API publica.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy, Ollama, JavaScript nativo, MediaRecorder, pytest e node:test.

## Global Constraints

- Preservar o banco operacional e usar somente `/tmp/ad-balancas-voice-manual.VnwzuO` na validacao manual.
- Nao usar API paga, nuvem, SQL/modelo, shell/modelo ou arquivos/modelo.
- Manter confirmacao, cancelamento, datas, persistencia e idempotencia deterministicas.
- Manter `127.0.0.1:8011`; nao alterar a aplicacao antiga em `8000`.
- Nao implementar e-mail, financeiro, notas ou emissao fiscal.

---

### Task 1: Saida conversacional estruturada

**Files:**
- Modify: `app/assistant/contracts.py`
- Modify: `app/assistant/ollama.py`
- Test: `tests/test_assistant_contracts.py`
- Test: `tests/test_assistant_ollama.py`

**Interfaces:**
- Produces: `ConversationCommand(tool="responder_conversa", message: str)`.
- Consumes: `assistant_command_adapter` e a lista limitada de ferramentas do Ollama.

- [ ] Escrever testes que rejeitam mensagem vazia/longa e validam a ferramenta `responder_conversa` retornada pelo Ollama.
- [ ] Executar os testes e observar falha por ferramenta inexistente.
- [ ] Adicionar o contrato, a definicao da ferramenta e prompt que separa conversa, consulta e mutacao.
- [ ] Executar os testes de contrato/Ollama ate passarem.
- [ ] Commitar `feat: add structured conversational replies`.

### Task 2: Resposta fundamentada e contexto

**Files:**
- Modify: `app/assistant/service.py`
- Test: `tests/test_assistant_service.py`
- Test: `tests/test_assistant_routes.py`

**Interfaces:**
- Consumes: `ConversationCommand`.
- Produces: `AssistantReply(kind="text")` sem `action_id` ou `task_id`.

- [ ] Escrever testes para saudacao natural, pergunta sobre resposta anterior, quadro vazio com texto explicito e recusa de confirmacao inferida.
- [ ] Executar os testes e observar que `ConversationCommand` nao e tratado.
- [ ] Retornar a mensagem conversacional validada e ajustar a resposta vazia de consulta para oferecer proxima acao.
- [ ] Executar regressao do servico e rotas.
- [ ] Commitar `feat: support grounded assistant conversation`.

### Task 3: Chat resiliente independente da voz

**Files:**
- Create: `app/static/assistant_chat.js`
- Create: `app/static/assistant_voice_bootstrap.js`
- Modify: `app/templates_web/assistant.html`
- Test: `tests/js/assistant_chat.test.mjs`
- Modify: `tests/test_assistant_routes.py`

**Interfaces:**
- Produces: `AssistantChatController.send(message)`, `retry()` e `window.assistantChat`.
- Consumes: `/api/assistant/messages`, historico e acoes existentes.

- [ ] Escrever testes JavaScript para mensagem imediata, timeout, HTTP/JSON/resposta vazia, `finally` e retry com o mesmo `request_id`.
- [ ] Executar `node --test tests/js/assistant_chat.test.mjs` e observar falha pelo modulo ausente.
- [ ] Implementar controlador e bootstrap textual sem importar voz.
- [ ] Mover o bootstrap de voz para modulo separado que usa `window.assistantChat`.
- [ ] Executar testes JavaScript e regressao HTML.
- [ ] Commitar `fix: decouple and harden assistant chat`.

### Task 4: Inicio de voz observavel e recuperavel

**Files:**
- Modify: `app/static/assistant_voice.js`
- Modify: `app/static/assistant_voice_bootstrap.js`
- Modify: `app/templates_web/assistant.html`
- Modify: `tests/js/assistant_voice.test.mjs`

**Interfaces:**
- Produces: callback `onLevel(level)` e erros de microfone orientados ao usuario.
- Consumes: `VoiceSessionController` e `AssistantChatController`.

- [ ] Escrever testes para reacao imediata, erros `NotAllowedError`, `NotFoundError`, `NotReadableError`, cancelamento pendente e nivel de audio.
- [ ] Executar os testes e observar as falhas de mensagens/medidor ausentes.
- [ ] Implementar classificacao de erro, callback de nivel e estados/botoes visiveis.
- [ ] Executar todas as suites JavaScript.
- [ ] Commitar `fix: make voice startup observable`.

### Task 5: Avaliacao real, documentacao e instancia 8011

**Files:**
- Create: `scripts/validate_assistant_conversation_local.py`
- Create: `docs/assistente/validacao-conversa-local.md`
- Modify: `docs/assistente/execucao.md`
- Test: `tests/test_assistant_conversation_local_runner.py`

**Interfaces:**
- Consumes: Ollama real, API FastAPI e SQLite isolado.
- Produces: relatorio JSON com respostas, latencias e contagens de tarefas.

- [ ] Escrever teste que garante configuracao exclusiva do banco isolado.
- [ ] Implementar os 14 casos reais, incluindo criacao/correcao/confirmacao unica, cancelamento, indisponibilidade e retry.
- [ ] Executar suite completa, node:test, Ollama real e o runner conversacional.
- [ ] Documentar causas, respostas reais, latencias, limites e roteiro sem cache.
- [ ] Reiniciar somente o processo `8011` com o codigo validado e verificar health, voz e banco isolado.
- [ ] Commitar `docs: validate corrected assistant conversation`.
