# Refatoração segura — 7 de outubro de 2026

## Escopo e preservação

Trabalho na branch `refactor/safe-modularization`, criada a partir de
`feature/gemini-provider-pilot`. Nenhum commit, push, merge, migração, instalação
de dependências ou alteração de configuração operacional foi feito pela
refatoração. O usuário dispensou a validação prévia do login como bloqueio para
o trabalho de código; isso **não** desativa nem remove a autenticação.

O HEAD inicial era `f82f6f1`. Durante o trabalho, um commit externo `823df11`
incorporou as alterações de autenticação que já estavam presentes. Ele foi
preservado; os hashes dos três arquivos de autenticação permanecem iguais à
linha de base registrada.

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
| Indexação/OCR | Refatorada e validada com OCR simulado | `local_pdf_ocr.py` concentra subprocessos e renderização. Indexador conserva caminhos autorizados, fingerprint, páginas, reconciliação e persistência. Mac/Windows reais não foram testados nesta rodada. |
| Formulário de propostas | Refatorado e validado nos testes focados | `routers/proposal_form.py` prepara defaults, prefill e parsing. O router conserva validação antecipada, redirects e ordem dos serviços. Construtor de payload de clonagem reutilizado após caracterização de equivalência. |
| Tarefas, Hoje, agenda, financeiro e promoções | Mantidas: serviços já separados por responsabilidade | Preservadas consultas determinísticas, snapshots, confirmação, transições e transportes. Cobertura na suíte existente; nenhuma alteração de regra de negócio. |
| STT/TTS e captura de voz | Mantidos: componentes separados | Adaptadores locais, política, filas e máquina de estados JS preservados. Sem microfone real nesta rodada. |
| Login e proteção de recursos | Não refatorados por decisão explícita do usuário | Arquivos e contratos preservados; testes sintéticos continuam na suíte. Ativação e login real da 8013 não são declarados validados. |
| Orquestração central e persistência de serviços/documentos | Não refatoradas integralmente | `AssistantService` ainda é extenso. Confirmação, commit e recuperação exigem preservar diferenças entre tipos de ação; próximas extrações precisam caracterizar falhas de persistência por operação. Não foi criado helper genérico de transação. |
| Templates, navegação e consultas da página de e-mails | Não refatorados nesta rodada | CSS/JS embutidos e composição de filtros/drafts ainda têm acoplamento. Separação completa requer caracterização do HTML e equivalência visual em navegador, não validada aqui. |
| Modelos, banco, jobs e inicialização | Não refatorados: restrição operacional | Não alterar schema, configuração, volumes ou efeitos de startup. Reiniciar a aplicação pode executar compatibilidade de banco, backfill, arquivamento e IMAP. |

Esta entrega separa responsabilidades do backend; **não significa que todo o
repositório ou a atualização operacional estejam concluídos**.

| Módulo original | Linhas antes | Linhas depois |
|---|---:|---:|
| `assistant/ollama.py` | 1171 | 524 |
| `assistant/service.py` | 3665 | 3323 |
| `services/document_index_service.py` | 467 | 309 |
| `routers/pages.py` | 867 | 700 |

Essas reduções representam código realocado por responsabilidade, não remoção
de funcionalidades. O corpo de sete helpers compartilhados permaneceu idêntico
por comparação AST; 66 métodos do orquestrador permaneceram intactos, inclusive
confirmações, commits e recuperação.

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

- Propostas e relatórios têm políticas diferentes diante de commit ambíguo:
  propostas limpam arquivos na exceção; relatórios reconciliam o resultado antes
  de removê-los. Unificar essas políticas alteraria comportamento.
- O startup chama `create_all`, compatibilidade e backfill, e inicia workers. O
  worker de e-mail faz uma consulta imediata antes de esperar o intervalo.
- A linha de base do lint contém 223 ocorrências; não houve autofix global.
- APIs de testes emitem depreciações preexistentes, registradas no plano.

## Validação e situação operacional

### Resultados automatizados

| Verificação | Linha de base | Resultado após as quatro extrações |
|---|---|---|
| Suíte Python completa, integrações simuladas | 722 passaram, 13 pulados | **749 passaram, 13 pulados**, 45,89 s na repetição final |
| JavaScript (`node:test`) | 36 passaram | **36 passaram**, sem falhas ou skips |
| Ruff global | 223 ocorrências | **223 ocorrências**, mesma distribuição por código |
| Ruff completo nos arquivos novos | Não aplicável | Passou |
| Ruff E9/F nos arquivos modificados | Não aplicável | Passou |
| Compilação e `git diff --check` | Linha de base preservada | Passaram |
| OpenAPI / DDL PostgreSQL compilado | 97 rotas, 34 tabelas | Hashes SHA256 idênticos; sem migração nem conexão ao PostgreSQL |
| Autenticação | Três arquivos com alterações anteriores | Hashes SHA256 idênticos |
| Preservação de testes | 586 funções originais, algumas parametrizadas | Nenhuma função original removida |

Os 13 skips são 10 testes de provedores reais opt-in, dois de conversores Docker
opt-in e um dependente de LibreOffice indisponível. Não foram transformados em
mocks para fabricar aprovação. Os avisos passaram de 6001 para 6026 por execução
dos cenários adicionais; são depreciações de `utcnow`, `on_event`, Jinja e AnyIO.
O lint global continua reprovando por problemas anteriores; não se declara lint
global limpo.

Testes focados por etapa: protocolo 115 antes/116 depois; preparação do
Assistente 64 antes/147 na expansão posterior; OCR 19 antes/27 incluindo busca;
formulário 15 antes/15 depois. A correção de exportações de compatibilidade
também passou por 113 testes focados. Os conjuntos se sobrepõem e **não devem ser
somados** como testes diferentes.

### Comandos de validação

Executados no ambiente virtual do projeto. O override do carregamento padrão
de configuração vale somente para o processo de testes, não altera `.env`.

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "-ra"]))'
node --test tests/js/*.test.mjs
.venv/bin/ruff check app scripts tests --statistics
.venv/bin/ruff check app/assistant/tool_protocol.py app/assistant/response_policy.py app/assistant/email/query_presentation.py app/assistant/service_reports.py app/services/local_pdf_ocr.py app/routers/proposal_form.py tests/test_assistant_tool_protocol.py tests/test_proposal_form.py
.venv/bin/ruff check --select E9,F app/assistant/evidence.py app/assistant/gemini.py app/assistant/ollama.py app/assistant/service.py app/services/document_index_service.py app/routers/pages.py tests/test_assistant_email_service.py tests/test_assistant_service_report.py tests/test_document_index_service.py
.venv/bin/python -m compileall -q app scripts tests
git diff --check
```

### Limitações e instância principal

- Revisão independente final aprovada, sem achados pendentes. A observação menor
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
- **Não houve reinício nem ativação do código novo.** `app/main.py` executa
  compatibilidade de schema e backfill na inicialização; o worker Yahoo consulta
  imediatamente antes de aguardar. Reiniciar nas condições atuais violaria as
  restrições de não aplicar migrações nem iniciar consulta externa. O processo
  anterior não usava reload. Não foi alterada configuração para contornar esse
  bloqueio nem iniciada outra instância. A restauração operacional permanece
  pendente de um caminho autorizado que trate esses efeitos de inicialização.
- Nenhuma alteração foi feita em banco, volumes, documentos, `.env`, configuração
  Gemini/Yahoo ou instâncias secundárias. Não houve commit por este trabalho.
