# Refatoração segura — 7 a 9 de outubro de 2026

## Escopo e preservação

Trabalho na branch `refactor/safe-modularization`, criada a partir de
`feature/gemini-provider-pilot`. O agente não executou commit, push, merge,
migração, instalação de dependências ou alteração de configuração operacional.
O usuário dispensou a validação prévia do login como bloqueio para
o trabalho de código; isso **não** desativa nem remove a autenticação.

O HEAD inicial era `f82f6f1`. Durante o trabalho, um commit externo `823df11`
incorporou as alterações de autenticação que já estavam presentes. Ele foi
preservado; os hashes dos três arquivos de autenticação permanecem iguais à
linha de base registrada.

Na continuação de 08/10, commits externos `b2825e6`, `8116be0` e `95bc5c3`
incorporaram as etapas anteriores e foram preservados. Eles não foram criados
pelo agente. Na retomada, o commit externo `ba245e2` incorporou o fechamento
anterior. Em 09/10, o commit externo `b32c784` incorporou as etapas 10–11.
Foi preservado, sem commit/push pelo agente durante a refatoração.

O usuário encerrou novas refatorações e autorizou explicitamente commit, push
e merge em 09/10. As etapas 12–13 já presentes no disco foram fechadas com
validação antes da publicação, sem novas extrações. A autorização substitui
somente a restrição anterior de integração Git/ativação; segredos e dados
continuam protegidos.

O [plano e a linha de base](superpowers/plans/2026-10-07-refatoracao-segura.md)
contêm a tabela de rastreabilidade entre funcionalidades, módulos e testes.

## Arquitetura auditada

FastAPI registra routers que delegam a serviços SQLAlchemy. As páginas usam
Jinja2 e JavaScript sem framework. O Assistente mantém orquestração de histórico,
confirmação, idempotência e evidências, com provedores de texto, leitura de e-mail
e voz separados. Modelos, schemas, scripts de compatibilidade, workers, geradores
DOCX/PDF, OCR, templates, assets e procedimentos de inicialização foram inspecionados.

Não foram lidos arquivos privados de configuração nem usados registros
operacionais como fixtures. Testes usam bancos temporários, documentos sintéticos
e transportes simulados. Não houve chamadas reais ao Gemini, Yahoo, SMTP ou voz.

## Etapas e responsabilidades

| Área | Classificação | Resultado ou trabalho restante |
|---|---|---|
| Protocolo de Gemini/Ollama | Refatorada e validada nos testes focados | `tool_protocol.py` concentra catálogo, declarações e projeção; `response_policy.py` concentra fundamentação, escopo e reparo. Gemini não importa mais o adaptador Ollama. Transporte, prompts específicos e erros continuam nos respectivos provedores. |
| Preparação de respostas do Assistente | Refatorada e validada nos testes focados | `service_reports.py` prepara prévias e tokens; `email/query_presentation.py` prepara intervalo e apresentação; `evidence.py` concentra validação de alegações. Orquestrador conserva commits, claims e recuperação. |
| Resumo operacional e apresentação da agenda | Refatorada e validada | `day_presentation.py` recebe resultados já consultados e produz texto, fala e evidência. Consultas e sua ordem continuam no serviço; não salva agenda. |
| Reconhecimento determinístico de intenções | Refatorado e validado nos testes focados | `intent_routing.py` concentra 11 funções puras. Aliases históricos continuam na classe; ordem de decisão, execução de ferramentas, confirmações e transações ficam no orquestrador. |
| Rascunhos de tarefas | Refatorados e validados | `task_drafts.py` concentra preparação, correção, esclarecimento e apresentação do rascunho. Mesma sessão e callbacks; confirmação, execução, commit, cancelamento e recuperação permanecem no orquestrador. |
| Resolução de clientes e responsáveis | Refatorada e validada | `entity_resolution.py` conserva consultas, normalização, correspondências, opções e filtro de responsáveis ativos. Resolução estrita de serviços continua distinta do vínculo opcional de tarefas; não cadastra entidades. |
| Indexação/OCR | Refatorada e validada com OCR simulado | `local_pdf_ocr.py` concentra subprocessos e renderização. Indexador conserva caminhos autorizados, fingerprint, páginas, reconciliação e persistência. Mac/Windows reais não foram testados nesta rodada. |
| Apresentação da busca documental | Refatorada e validada | `document_presentation.py` concentra respostas, citações, fala e limitações. Busca autorizada continua no Assistente, antes da apresentação; sem novo acesso a arquivos. |
| Extração textual DOCX | Refatorada e validada | `docx_text.py` lê texto/seções ZIP/XML; os wrappers públicos validam o pacote antes. Exceção compartilhada em `document_errors.py`, aliases preservados; upload, limites e persistência intocados. |
| Formulário de propostas | Refatorado e validado nos testes focados | `routers/proposal_form.py` prepara defaults, prefill e parsing. O router conserva validação antecipada, redirects e ordem dos serviços. Construtor de payload de clonagem reutilizado após caracterização de equivalência. |
| Rotas web de Clientes e Propostas | Refatoradas e validadas | `web_clients.py` e `web_proposals.py` têm handlers literais; `web_rendering.py` mantém o contexto compartilhado. `pages.router` conserva ordem, nomes e tags; aliases preservam entradas usadas pelos testes. APIs e geradores intocados. |
| Consulta da fila de e-mails | Refatorada e validada | `message_workbench_service.py` concentra consultas locais por provider/mailbox, filtros, listas, contagens e vínculos. GET comprovado como SELECT-only; POSTs de revisão/confirmar permanecem iguais. |
| Tarefas, Hoje, agenda, financeiro e promoções | Mantidas: serviços já separados por responsabilidade | Preservadas consultas determinísticas, snapshots, confirmação, transições e transportes. Cobertura na suíte existente; nenhuma alteração de regra de negócio. |
| STT/TTS e captura de voz | Mantidos: componentes separados | Adaptadores locais, política, filas e máquina de estados JS preservados. Sem microfone real nesta rodada. |
| Login e proteção de recursos | Não refatorados por decisão explícita do usuário | Arquivos e contratos preservados; testes sintéticos continuam na suíte. Ativação e login real da 8013 não são declarados validados. |
| Núcleo transacional da conversa e persistência de serviços/documentos | Mantido por unidade de responsabilidade; não refatorado integralmente | O protocolo de requests, leases, tokens, confirmação, commit e reconciliação permanece no mesmo dono de sessão. Os adapters agora separam preparação/apresentação/resolução. Os serviços documentais têm políticas de recuperação diferentes; não criar helper genérico sem benefício demonstrado. O orquestrador ainda tem 2373 linhas; novas extrações foram encerradas pelo usuário. |
| Templates e navegação | Refatorados e validados por equivalência de HTML | Quatro componentes Jinja separam estilos/scripts do shell e formulário. Fontes reconstruídos são byte a byte idênticos; quatro hashes integrais e testes JS preservados. Sem redesenho e sem teste visual manual. |
| Modelos, banco, jobs e inicialização | Não refatorados: restrição operacional | Não alterar schema, configuração, volumes ou efeitos de startup. Reiniciar a aplicação pode executar compatibilidade de banco, backfill, arquivamento e IMAP. |

Esta entrega separa responsabilidades do backend; **não significa que todo o
repositório ou a atualização operacional estejam concluídos**.

| Módulo original | Linhas antes | Linhas depois |
|---|---:|---:|
| `assistant/ollama.py` | 1171 | 524 |
| `assistant/service.py` | 3665 | 2373 |
| `services/proposal_file_service.py` | 593 | 535 |
| `services/document_index_service.py` | 467 | 309 |
| `routers/pages.py` | 867 | 344 |
| `templates_web/base.html` | 1269 | 104 |
| `templates_web/proposal_form.html` | 896 | 492 |

Essas reduções representam código realocado por responsabilidade, não remoção
de funcionalidades. O corpo de sete helpers compartilhados permaneceu idêntico
por comparação AST; 66 métodos do orquestrador permaneceram intactos, inclusive
confirmações, commits e recuperação.

Na etapa 5, outros 11 métodos estáticos foram extraídos com corpo/assinatura
idênticos. Os 62 métodos restantes, incluindo `handle_message`, não sofreram
alteração em relação à etapa 4. O novo módulo tem 401 linhas e importa somente
contratos, normalização e `re`: nenhuma consulta, provedor concreto ou I/O.

Na etapa 6, somente os dois métodos que apresentavam resumo/agenda foram
modificados; os outros 60 continuaram idênticos por AST. Na etapa 7, o bloco
SQL foi movido literalmente substituindo somente acesso ao provider/mailbox
pelos parâmetros; contexto e POSTs permaneceram idênticos. Na etapa 9, os 23
ASTs das funções originais do router foram conferidos entre os módulos de
destino e os handlers retidos; tabela de rotas e OpenAPI permaneceram iguais.

Nas etapas 10–11, quatro métodos de rascunho e quatro resolvers foram movidos
literalmente, com wrappers de assinatura preservada. Contra a linha de base
anterior a essas duas etapas, somente o inicializador e esses oito wrappers
mudaram; os outros **53 métodos** têm AST idêntica. Os módulos novos têm 350 e
98 linhas. A resolução continua na mesma sessão usada pelos adapters existentes.
Um alerta inicial sobre dois métodos de relatório foi identificado como
truncamento do relatório de AST, não alteração de código; a comparação por
hashes compactos confirmou a equivalência.

Os includes Jinja recompõem exatamente os fontes anteriores: base com 45.654
bytes e formulário com 34.758 bytes. Os novos componentes conservam CSS/JS
literalmente, sem novos requests de assets ou alterações de CSRF e eventos.

Os aliases históricos mantêm importação e identidade. Globals privados das
funções extraídas pertencem agora aos módulos de destino; novos testes que
substituam dependências internas devem usar esse módulo. Não foi identificado
consumidor que dependesse de reatribuir os imports internos de decimal/schemas
em `pages`, ou as constantes internas de OCR no indexador. Pontos de substituição
efetivamente usados pela suíte foram preservados.

## Limpeza: nada removido sem evidência

Nenhum arquivo existente nem teste foi excluído. Código extraído permanece nos
novos módulos, com pontos de importação compatíveis. Não foram removidos testes
opt-in nem enfraquecidos asserts para contornar falhas.

Foi removida somente uma asserção consecutiva duplicada no teste
`test_cancel_can_discard_a_draft_that_needs_clarification`: havia duas consultas
idênticas `Task.count() == 0`, sem operação entre elas, em banco sintético sem
escritor concorrente. A primeira asserção, o teste e a verificação do cancelamento
permanecem. Não havia comportamento único coberto pela segunda consulta. O teste
e os novos módulos passaram em 25 casos focados e na suíte completa.

- `scripts/ocr_pdf_vision.swift`: chamado pelo adaptador e referenciado na
  documentação de busca documental; não é sobra de implementação.
- `scripts/run_assistant_8011_yahoo.sh`: permanece referenciado em procedimentos
  históricos/operacionais; não se infere inutilidade pelo número da porta.
- Fallbacks de extração PDF: chamados pelo importador/armazenamento e cobertos por
  testes próprios de ausência de texto e falha de extração.
- Testes de API real e conversores Docker: cobrem integrações diferentes dos
  mocks; skips por falta de opt-in não tornam esses testes redundantes.
- `upload_to_drive_placeholder`: ausência de chamador literal não comprova que o
  módulo de armazenamento inteiro possa ser removido; nenhuma exclusão foi feita.
- Dados, documentos, modelos DOCX, backups, OCR e arquivos ignorados foram
  preservados, sem leitura de seu conteúdo.

## Questões preexistentes, não corrigidas oportunisticamente

O [registro separado de defeitos](refatoracao-defeitos-pendentes.md) distingue
reprodução sintética de observações apenas no código. RF-01 foi reproduzido em
SQLite em memória: falha da fonte de tarefas ainda pode ser descrita como quadro
vazio pelo resumo atual; nenhuma alteração funcional foi misturada à extração.

- Propostas e relatórios têm políticas diferentes diante de commit ambíguo:
  propostas limpam arquivos na exceção; relatórios reconciliam o resultado antes
  de removê-los. Unificar essas políticas alteraria comportamento.
- O startup chama `create_all`, compatibilidade e backfill, e inicia workers. O
  worker de e-mail faz uma consulta imediata antes de esperar o intervalo.
- A linha de base do lint contém 223 ocorrências; não houve autofix global.
- APIs de testes emitem depreciações preexistentes, registradas no plano.
- Caracterização das intenções encontrou limites anteriores: “corrija” não
  corresponde ao detector que usa `corrig*`; “urgentes” não ativa o filtro que
  reconhece “urgente”; “e-mails não lidos” isolado não aciona o detector;
  “segunda via” satisfaz a detecção de data por substring. Esses comportamentos
  foram preservados e não devem ser apresentados como correções funcionais.

## Validação e situação operacional

### Resultados automatizados

| Verificação | Linha de base | Resultado no fechamento autorizado |
|---|---|---|
| Suíte Python completa, integrações simuladas | 722 passaram, 13 pulados | **860 passaram, 13 pulados**, 110,96 s no fechamento |
| JavaScript (`node:test`) | 36 passaram | **36 passaram**, sem falhas ou skips |
| Ruff global | 223 ocorrências | **223 ocorrências**, mesma distribuição por código |
| Ruff completo nos arquivos novos | Não aplicável | Passou nos módulos puros/helpers/testes; routers web têm 11 B008 transferidos das assinaturas existentes |
| Ruff E9/F nos arquivos modificados | Não aplicável | Passou |
| Compilação e `git diff --check` | Linha de base preservada | Passaram; também Jinja e sintaxe dos dois scripts extraídos |
| OpenAPI / DDL PostgreSQL compilado | 97 rotas, 34 tabelas | Hashes SHA256 idênticos; sem migração nem conexão ao PostgreSQL |
| Autenticação | Três arquivos com alterações anteriores | Hashes SHA256 idênticos |
| Preservação de testes | 586 funções originais, algumas parametrizadas | Nenhuma função original removida |

Os 13 skips são 10 testes de provedores reais opt-in, dois de conversores Docker
opt-in e um dependente de LibreOffice indisponível. Não foram transformados em
mocks para fabricar aprovação. Os avisos passaram de 6001 para 6857 por execução
dos cenários adicionais; são depreciações de `utcnow`, `on_event`, Jinja e AnyIO.
O lint global continua reprovando por problemas anteriores; não se declara lint
global limpo. Houve um I001 novo nos imports dos testes OCR; foi corrigido
apenas nesse bloco, retornando à mesma distribuição de 223 ocorrências.

Testes focados por etapa: protocolo 115 antes/116 depois; preparação do
Assistente 64 antes/147 na expansão posterior; OCR 19 antes/27 incluindo busca;
formulário 15 antes/15 depois. A correção de exportações de compatibilidade
também passou por 113 testes focados. Os conjuntos se sobrepõem e **não devem ser
somados** como testes diferentes.

Etapa 5: 151 testes focados passaram antes e depois (2082 avisos preexistentes),
incluindo **43 casos novos** de intenções. Na primeira escrita dos testes, duas
expectativas não refletiam o vocabulário existente; foram corrigidas ainda antes
de modificar produção. Não foi enfraquecido teste anterior. A revisão independente
da etapa aprovou código e especificação; corrigiu-se a contagem inicialmente
reportada como 41, sem mudança no total de 151 passes.

O executável `node` não estava no PATH da retomada. Sem instalar nada ou carregar
configuração privada, os 36 testes JS foram repetidos com a instalação existente:
`/Users/mateuscardoso/.nvm/versions/node/v24.15.0/bin/node --test tests/js/*.test.mjs`.

Etapas 6–9: respectivamente 95, 41, 43 e 48 testes focados passaram antes e
depois. Incluem 7 casos novos de apresentação, 7 da fila, 4 hashes integrais de
templates e 2 testes HTTP de Clientes/Propostas. Os conjuntos se sobrepõem; o
total exclusivo está na suíte completa. A fixture da fila foi reforçada com
estado de outro provider na mesma mailbox; validada no fechamento.

A primeira execução completa desta continuação teve **1 falha, 811 passes e 13
skips**: um teste antigo usava o relógio real às 23h13 de Recife e esperava bloco
de 60 minutos numa janela com apenas 45 minutos restantes. O planejador estava
correto. Foi fixado somente o relógio do teste, mantendo todos os asserts e
acrescentando a verificação `00:01–01:01` após compromisso. O conjunto de agenda,
fila e OCR passou (32 testes); a repetição completa passou com 812/13. Nenhuma
regra de agendamento foi flexibilizada para fazer a suíte passar.

Etapas 10–11: 130 e 125 testes focados passaram antes e depois, respectivamente.
Incluem 7 novos casos de rascunhos e 17 de resolução. Cobrem ambiguidades,
remoções/correções, expiração de confirmação antiga, mesmo rascunho, cliente
opcional, propostas incompatíveis e ausência de Task antes da confirmação.
Os conjuntos se sobrepõem e não representam 255 testes exclusivos.

Etapa 12: 76 testes focados antes/depois; dez casos novos de apresentação.
Etapa 13: 94 testes antes, com 14 casos novos; a interrupção encerrou novas
extrações. O controlador validou o delta existente com a suíte completa acima
e 77 testes focados (extração/upload/apresentação), depois repetiu o conjunto
DOCX após explicitar aliases de compatibilidade (67 passaram). A coleta final
confirmou 24 casos novos exclusivos entre os dois arquivos. Revisão independente
aprovada: corpos AST equivalentes, validação antes de leitura, classe de erro
única e nenhum contrato de persistência alterado.

### Comandos de validação

Executados no ambiente virtual do projeto. O override do carregamento padrão
de configuração vale somente para o processo de testes, não altera `.env`.

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "-ra"]))'
node --test tests/js/*.test.mjs
.venv/bin/ruff check app scripts tests --statistics
.venv/bin/ruff check app/assistant/tool_protocol.py app/assistant/response_policy.py app/assistant/email/query_presentation.py app/assistant/service_reports.py app/services/local_pdf_ocr.py app/routers/proposal_form.py tests/test_assistant_tool_protocol.py tests/test_proposal_form.py
.venv/bin/ruff check app/assistant/intent_routing.py tests/test_assistant_intent_routing.py
.venv/bin/ruff check app/assistant/task_drafts.py app/assistant/entity_resolution.py tests/test_assistant_task_drafts.py tests/test_assistant_entity_resolution.py
.venv/bin/ruff check app/assistant/day_presentation.py app/services/message_workbench_service.py app/routers/web_rendering.py tests/test_assistant_day_presentation.py tests/test_message_workbench_service.py tests/test_template_characterization.py tests/test_web_page_contracts.py
.venv/bin/ruff check --select E9,F app/routers/web_clients.py app/routers/web_proposals.py tests/test_agenda_routes.py
.venv/bin/ruff check --select E9,F app/assistant/evidence.py app/assistant/gemini.py app/assistant/ollama.py app/assistant/service.py app/services/document_index_service.py app/routers/pages.py tests/test_assistant_email_service.py tests/test_assistant_service_report.py tests/test_document_index_service.py
.venv/bin/python -m compileall -q app scripts tests
git diff --check
```

### Limitações e instância principal

- Etapas 12–13 aprovadas na revisão final antes da publicação Git autorizada.
  A ativação operacional precisa de verificação separada de backup, administrador,
  startup e health check; commit/merge não comprovam aplicação em execução.
- Revisão consolidada das etapas 10–11 aprovada, com comparação AST independente
  dos oito métodos extraídos e dos outros 53 métodos preservados. Não encontrou
  regressão crítica ou importante. RF-05 foi confirmado como comportamento
  preexistente, registrado separadamente; não foi corrigido oportunisticamente.
- Revisão independente final aprovada novamente após as nove etapas, sem
  regressão crítica ou importante. Sugestão menor não bloqueante: o teste de
  ordem do apresentador não instrumenta mensagem/snapshot; a sequência atual
  foi confirmada por AST. Não foi adicionado teste que apenas espelhasse essas
  chamadas internas. A observação menor anterior
  sobre o teste de clonagem foi resolvida com valores esperados independentes;
  os 15 testes focados e o lint passaram novamente. Isso não substitui os testes
  operacionais/manuais que permanecem fora desta rodada.
- PostgreSQL real, chamadas Gemini/Yahoo/SMTP, conversores e OCR reais não foram
  exercitados. A compilação do DDL não é teste de execução no PostgreSQL.
- Sem teste manual no navegador, microfone ou máquina Windows. Os 36 testes JS
  não substituem captura/reprodução com hardware real.
- Na verificação anterior, a 8013 permaneceu no PID **56224**, cwd deste checkout, iniciada em 07/10/2026
  às 11:08:02, escutando somente em `127.0.0.1:8013`. `/healthz` respondeu 200
  ao final das etapas de código. Nenhuma página com dados operacionais foi usada
  como teste desta refatoração.
- **Atualização em 08/10/2026:** na retomada, `lsof` não encontrou listener na
  8013, o PID 56224 não existia mais e `curl /healthz` terminou com código 7
  (falha de conexão, sem resposta HTTP). A instância está fora do ar nessa
  verificação. Nenhum processo foi encerrado pela refatoração; a causa da parada
  não foi determinada. O resultado HTTP 200 acima é histórico, não estado atual.
- **Rechecagem em 09/10/2026:** continua sem listener na 8013; `/healthz`
  retornou HTTP 000/erro de conexão (curl código 7). O código novo não está ativo.
- **Não houve reinício nem ativação do código novo.** `app/main.py` executa
  compatibilidade de schema e backfill na inicialização; o worker Yahoo consulta
  imediatamente antes de aguardar. Reiniciar nas condições atuais violaria as
  restrições de não aplicar migrações nem iniciar consulta externa. O processo
  anterior não usava reload. Não foi alterada configuração para contornar esse
  bloqueio nem iniciada outra instância. A restauração operacional permanece
  pendente de um caminho autorizado que trate esses efeitos de inicialização.
- Nenhuma alteração foi feita em banco, volumes, documentos, `.env`, configuração
  Gemini/Yahoo ou instâncias secundárias. Não houve commit por este trabalho.
