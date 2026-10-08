# Refatoração segura AD Balanças — plano e linha de base

> Execução por etapas com revisão independente (subagent-driven-development). A instrução do usuário de não fazer commits prevalece sobre recomendações de skills. O usuário dispensou a ativação prévia do login; as correções de autenticação permanecem intactas.

**Objetivo:** separar responsabilidades reais sem alterar comportamento, persistência, contratos HTTP ou integrações.

**Arquitetura:** FastAPI/Jinja2 com rotas em `app/routers`, serviços SQLAlchemy em `app/services`, orquestrador do assistente e adaptadores de texto/voz/e-mail em `app/assistant`. Extrair somente protocolo independente do provedor, preparação/projeção de respostas, OCR local e parsing de formulário. Manter a propriedade de transações nos serviços atuais.

**Tecnologias:** Python 3.12, FastAPI, Pydantic, SQLAlchemy, Jinja2, httpx; JavaScript sem framework; pytest e node:test.

## Restrições globais

- Não fazer commit, push, merge, deploy, migração, exclusão de dados ou instalação de dependências.
- Não ler `.env`, configurações privadas ou dados operacionais; não chamar Gemini, Yahoo, SMTP, STT/TTS reais.
- Usar bancos temporários e dados sintéticos. Nenhuma outra instância de aplicação.
- Preservar URLs, nomes de rotas, schemas, HTML, mensagens, ordenação, confirmações, idempotência, efeitos colaterais e formatos.
- Não alterar modelos, configuração, templates, arquivos estáticos ou inicialização como atalho para ativar mudanças.
- Não excluir arquivos nem testes sem comprovação de redundância e uso. Preservar os testes opt-in.
- Não reiniciar a 8013 se isso disparar IMAP, migração ou falhar pela ausência de administrador. A dispensa do pré-requisito de login não autoriza remover ou desabilitar autenticação.

## Estado inicial verificado em 2026-10-07

- Checkout: `/Users/mateuscardoso/dev/pai/Proposta.comercial`.
- Origem: `feature/gemini-provider-pilot`, HEAD `f82f6f11dfa7d662a486272148821f60e21e15e4`.
- Branch criada: `refactor/safe-modularization`; sem stash/reset/commit.
- Alterações preexistentes: `app/security/auth.py`, `app/security/routes.py`, `tests/test_authentication.py` (52 inserções, 3 remoções). Nenhum não rastreado no início.
- PID 56224, cwd deste checkout, launcher `scripts.run_assistant_8013_local`, escuta em `127.0.0.1:8013`, sem reload.
- Nenhum `AGENTS.md` encontrado no repositório ou ancestrais consultados.
- Login operacional ainda pendente conforme auditoria anterior; a presente etapa não o ativa.
- Startup de `app/main.py`: readiness de autenticação, `create_all`, compatibilidade de schema, backfill de drafts, worker de arquivamento financeiro e worker Yahoo. Este último sincroniza imediatamente antes de aguardar 900 s. Não executar startup operacional nesta refatoração.

### Testes de referência

Para impedir que construtores `Settings()` carreguem o `.env` implicitamente, a configuração padrão de leitura é desativada somente no processo de testes. Arquivos sintéticos explicitamente fornecidos pelos testes de configuração continuam sendo testados.

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "-ra"]))'
node --test tests/js/*.test.mjs
.venv/bin/ruff check app scripts tests --statistics
git diff --check
```

- Python: **722 passed, 13 skipped**, 42,73 s, 6001 avisos de depreciação preexistentes.
- JS: **36 passed**, nenhuma falha ou skip.
- Ruff completo: **223 ocorrências preexistentes**; principais: B008=86, I001=45, UP037=19, DTZ011=15, BLE001=11. Não executar autofix global.
- Skips: 10 testes de provedores reais opt-in, 2 conversores Docker opt-in, 1 LibreOffice indisponível. Não equivalem a integração real validada.
- Contratos obtidos sem startup/conexão de banco: 97 rotas; 34 tabelas. SHA256 OpenAPI: `0d679f8d78330e91b9d9e08f79759f6568a8ff2ecd7e1fef03cbb1f2136fa941`; SHA256 DDL PostgreSQL compilado: `857074c100468d75940f37bbbf38a08bd966b8ef0916d0dfd364e62ae2f8c2be`.
- SHA256 das correções preservadas: auth.py `4beec9d00496c4fb205d205d0c718935e75cf12e18384d3206bd0260461e579a`; routes.py `fda04a9f10a9641ac92b65422509274ce6000393c48d9f4f70618ac053fd6a6d`; test_authentication.py `dc4b38804c4d827d3e7100806dc761c79bcd5adac303052f289d6c4b93e2b690`.
- Durante a execução, HEAD avançou externamente para `823df11` (`auth`, 2026-10-07 13:22:14 -0300), incorporando exatamente essas três alterações. Nenhum comando de commit foi executado pela refatoração; hashes dos três arquivos continuam idênticos. O commit foi preservado.

## Mapa e rastreabilidade

| Fluxo | Módulos e contratos existentes | Testes protetores | Direção desta etapa |
|---|---|---|---|
| Autenticação | `security/{auth,routes,passwords}.py`, `User`, bootstrap; cookie, CSRF, Argon2id | `test_authentication.py` | Preservar integralmente por decisão do usuário |
| Texto/provedores | `assistant/{service,provider,contracts,ollama,gemini,evidence}.py`; ferramentas aprovadas e schemas | `test_assistant_{ollama,gemini,contracts,provider_parity,service,routes}.py` | Desacoplar protocolo de Ollama e separar projeções |
| Voz | `assistant/voice/{audio,faster_whisper,piper,policy,runtime,speech}.py`, `routers/assistant.py`, chat/voice JS | `test_assistant_voice_*.py`, `tests/js/assistant*.test.mjs` | Componentes já separados; preservar captura, fila e cancelamento |
| Quadro/Hoje/agenda | `board_service`, `today_service`, `daily_schedule_service`, `daily_brief_service`; rotas board/agenda/pages | `test_board_*`, `test_today_*`, `test_daily_schedule_service`, `test_assistant_daily_brief`, JS Kanban | Preservar consultas determinísticas e snapshots |
| Serviços e relatório | `service_record_service`, `service_report_service`, `technical_report_document_service`, adaptador `assistant/service_records.py` | `test_service_*`, `test_assistant_service_{records,report}`, `test_service_history_immutability` | Extrair preparação conversacional; manter transações e histórico |
| Propostas/clientes/usuários | `routers/{pages,clients,users,proposals,proposal_files,imports}.py`, `proposal_service`, `proposal_file_service`, `pdf_import_service` | `test_proposal_*`, `test_document_total_marker`, `test_pdf_*`, novos testes de formulário | Extrair parsing e preparação de formulário; manter efeitos de criação/geração |
| E-mails | `assistant/email/{imap,classification,extraction,sync,worker}.py`, `email_review_service`, `email_review`/pages | `test_assistant_email*` | Extrair projeção da consulta; IMAP e worker intocados |
| Financeiro | `lancamento_service`, `finance_archive_worker`, routers financeiro | `test_lancamento_*`, `test_financeiro_routes` | Serviço coeso; preservar transições e arquivamento |
| Promoções | `promotion_{campaign,generation,mail}_service`, routers promotions | `test_promotion_{campaigns,gemini,mail}` | Limites de geração/transporte já definidos; manter |
| Documentos e OCR | `document_index_service`, `document_search_service`, `proposal_file_service`, script Swift | `test_document_index_service`, `test_assistant_document_search`, `test_proposal_file_*` | Extrair OCR local sem persistência |
| UI e navegação | `templates_web` (inclui base/formulários), `static/{assistant_chat,assistant_voice,kanban_ui}.js` | testes HTTP/Jinja e 36 JS | Não alterar HTML/CSS/JS nesta rodada sem equivalência visual |
| Dados/instalação | `models.py`, `schemas.py`, `db.py`, SQL em `scripts/migrations`, Docker/Compose, `scripts/*`, diretórios configuráveis output/doc_templates/.models e local-data externo | schema compatibility, runtime/local runner | Não alterar schema, scripts operacionais ou diretórios de dados |

## Etapa 1 — protocolo compartilhado dos provedores

**Arquivos:** modificar `app/assistant/{ollama,gemini}.py`; criar `app/assistant/tool_protocol.py` e `app/assistant/response_policy.py`; testes de provedores, paridade, contratos e fundamentação.

**Interface:** catálogo e declarações neutras `{name, description, parameters}`, projeção de resultados e constantes em `tool_protocol`; validadores de escopo/fundamentação e razões/dicas de reparo em `response_policy`. Ambos dependem apenas de contratos e políticas compartilhadas, nunca de adaptador concreto.

- [x] Caracterizar declarações para `None`, vazio e subconjuntos de ferramentas; guardar prompts/transporte/erros existentes como referência pelos testes atuais.
- [x] Mover sem reescrever textos: catálogo, compactação, validadores e classificação/dicas de reparo. `_validated_command` e envelope Ollama ficam em Ollama; `_google_schema` e parser Gemini ficam em Gemini.
- [x] Gemini deixa de importar Ollama. Preservar imports históricos dos helpers de Ollama mediante aliases explícitos, sem duplicar implementação. Não unificar system prompts diferentes nem alterar budgets/ordem de reparo.
- [x] Rodar contratos/paridade/grounding e testes HTTP simulados de ambos; lint selecionado, compilação e diff; revisão independente.

**Resultado:** 115 testes de caracterização/referência antes; 116 depois (inclui projeção neutra). AST de sete helpers movidos idêntica ao original. Revisão independente aprovada sem achados críticos/importantes. `tool_protocol.py` tem 221 linhas e `response_policy.py` 479; nenhuma lógica de transporte foi compartilhada artificialmente.

## Etapa 2 — preparações e evidências no Assistente

**Arquivos:** modificar `app/assistant/service.py` e `app/assistant/evidence.py`; criar `app/assistant/service_reports.py` e `app/assistant/email/query_presentation.py`; testes correspondentes.

**Interface:** `AssistantServiceReportAdapter(db, token_hash=...)` prepara/corrige/atualiza prévia e localiza ação pendente. Orquestrador mantém `edit_service_report_preview`, inserção de histórico, commit, claim de confirmação, execução e recuperação. Helpers de e-mail recebem comando, horário/fuso e resultado tipado; produzem query/clarificação e reply/evidência sem I/O.

- [x] Executar/caracterizar prévias ambíguas, token rotacionado, fonte atualizada, cancelamento, retry; consultas de e-mail com falha, vazio filtrado, parcial e limite visual.
- [x] Extrair prévia para adaptador por composição seguindo `service_records.py`, preservando token/hash, flush e pontos de commit.
- [x] Extrair construção de intervalo e projeção da consulta. Preservar limites diferentes: até 100 candidatos, até 20 visuais e até 3 no modelo. A chamada ao leitor, telemetria e geração do evidence ID ficam sob controle do serviço.
- [x] Consolidar validação de alegações de conversa em `evidence.py`, com argumentos explícitos e histórico consultado pelo serviço sob demanda; nenhuma consulta implementada dentro da política.
- [x] Testar conversa/texto/voz, confirmações, correções e idempotência; revisar manutenção de exceções, transações e logs.

**Resultado:** 64 testes antes; 147 na expansão posterior; lint selecionado/novos módulos, compilação e diff aprovados. Revisão independente aprovada. Histórico usa callback lazy para preservar exatamente short-circuit e quantidade de consultas; nenhuma consulta antecipada foi adicionada. Comparação AST confirmou 66 métodos originais intactos, incluindo handle_message, edição pública, confirmações, claims, commits e recuperação. Os wrappers de compatibilidade delegam ao adaptador; não há mixin nem referência ao serviço completo.

## Etapa 3 — OCR local separado da indexação

**Arquivos:** `app/services/document_index_service.py`, novo `app/services/local_pdf_ocr.py`, `tests/test_document_index_service.py`.

**Interface:** mesmas `LocalOCRUnavailable`, `local_vision_ocr(path)`, `local_tesseract_ocr(path)` e códigos. Dispatcher compatível continua no indexador para preservar patches/interceptações existentes.

- [x] Caracterizar exceções/timeout e limpeza com PDFs sintéticos e subprocessos simulados, antes de extrair.
- [x] Mover somente implementação OCR, constantes e renderer; manter autorização de caminhos, reconciliação, fingerprint, metadados, flush e exclusão do índice no serviço atual.
- [x] Preservar `por`, seleção Darwin/Windows, limites 500 páginas/90 s total/30 s por página, argumentos sem shell, fechamento de PDFium e diretório temporário.
- [x] Testar OCR/indexação/citações, reindexação/substituição/exclusão; lint, compilação e revisão independente. Não executar OCR em documento operacional.

**Resultado:** 19 testes de caracterização antes e 27 com busca documental depois; revisão independente aprovada. Adaptador local com 179 linhas, indexador reduzido de 467 para 309. Funções e exceção preservam identidade nos imports históricos; o dispatcher mantém os pontos existentes de substituição dos leitores nos testes. Globals internos de OCR pertencem agora ao adaptador: alterar/rebind de constantes deve ser feito nesse módulo; nenhuma configuração pública mudou. OCR real em Mac/Windows não foi executado nesta rodada.

## Etapa 4 — formulário de propostas

**Arquivos:** `app/routers/pages.py`, novo `app/routers/proposal_form.py`, novo `tests/test_proposal_form.py`.

**Interface:** `parse_proposal_form(form, *, client_id, user_id) -> ProposalCreate`, defaults com `default_km_value` explícito e helpers de prefill/conversão da proposta. Rotas e nomes continuam em pages; validação dos IDs e redirecionamentos permanecem nos mesmos pontos.

- [x] Caracterizar via POST sintético: itens brasileiros, listas de tamanhos diferentes, linhas vazias, cronograma, IDs inválidos, erro de parsing, modo revisão, warning e cartão opcional; nenhum gerador real.
- [x] Extrair parsing puro e preparação de formulário, mantendo mensagens/exceções e serialização sem normalização nova.
- [x] Comparar `_proposal_to_payload` com `_build_clone_payload` usando proposta sintética; reutilizar o construtor existente após provar equivalência, sem substituir o fluxo de duplicação por outro serviço com efeitos diferentes.
- [x] Manter `create_proposal`, `generate_documents` e criação opcional no quadro na mesma ordem e transações. Não unificar cópia de arquivos com relatórios (contratos diferentes).
- [x] Testes focados e revisão independente, comparar OpenAPI, DDL e hashes de autenticação ao baseline.

**Resultado dos testes:** 15 cenários novos passaram antes e depois. O parser tem 151 linhas; router caiu de 867 para 700. Defaults diferentes de GET/POST, listas desalinhadas, redirects de revisão, falhas de parsing, warnings e ordem dos serviços preservados. Testes novos exercitam diretamente o handler com request sintético; a suíte existente cobre HTTP/middleware. Não equivale a validação manual em navegador. Revisão final independente aprovada: melhoria do teste de clonagem aplicada, comparando ambos os builders a valores esperados independentes; 15 testes passaram novamente. Reatribuição hipotética dos antigos imports internos não foi considerada regressão sem consumidor real; imports, identidades e pontos de substituição usados pelos testes continuam preservados.

## Fechamento

- [x] Revisar possíveis arquivos sem uso por imports, rotas, templates, JS, scripts, Docker, docs e migrações. Nenhuma exclusão é presumida por ausência de uma referência literal.
- [x] Suíte Python completa isolada, 36 JS, compilação, lint selecionado/global comparativo e `git diff --check`.
- [x] Documentar áreas refatoradas/coesas/não refatoradas e defeitos preexistentes separados.
- [x] Decisão de runtime: não reiniciar. Startup executa compatibilidade/backfill e inicia IMAP imediatamente; não contornar essas restrições nem desabilitar login.

**Validação final executada:** 749 Python passed, 13 skipped, 6026 warnings de depreciação (46,36 s); 36 JS passed. Nenhuma falha. Os mesmos 13 skips da linha de base permanecem. Lint completo dos oito arquivos novos e E9/F dos nove arquivos modificados passaram; lint global mantém exatamente os mesmos 223 achados por código. Compilação `app scripts tests` e `git diff --check` passaram. OpenAPI/DDL têm os mesmos hashes, 97 rotas e 34 tabelas; hashes de autenticação preservados. Comparação AST do inventário preservou todas as 586 funções originais de teste, inclusive casos parametrizados/opt-in. Nenhum arquivo foi excluído. Revisão final independente aprovada, sem achados pendentes; ainda sem ativação operacional ou refatoração integral da UI/orquestração.

## Questões preexistentes fora do escopo

**Retomada em 08/10/2026:** mantidos branch/HEAD e todas as mudanças. A repetição final da suíte após fortalecer o teste de clonagem confirmou 749 passed, 13 skipped, 6026 warnings em 45,89 s. A 8013 agora está sem listener e o PID anterior não existe; health check falhou na conexão. Nenhum processo foi encerrado por esta refatoração. Não iniciar automaticamente: os efeitos de startup continuam proibidos neste escopo. O relatório `docs/refatoracao-segura.md` distingue o health check histórico do estado atual.

- A autenticação do código atual exige administrador e segredo no launcher. Dispensa de bloqueio da refatoração não remove esse requisito de runtime.
- `main.on_startup` aplica compatibilidade e backfill e agenda workers com efeitos reais. Não pode ser tratado como simples health check.
- Propostas removem arquivos em exceção de commit; relatórios reconciliam commit ambíguo antes de removê-los. Não unificar esses comportamentos em helper genérico.
- O modelo User não tem papéis; usuários autenticados ativos compartilham acesso. Não criar RBAC nesta tarefa.
- `base.html` contém estilos/scripts acoplados e `pages.py` reúne áreas diferentes. Esta rodada preserva layout e extrai apenas preparação de formulário; mudanças visuais exigem caracterização adicional em navegador.
