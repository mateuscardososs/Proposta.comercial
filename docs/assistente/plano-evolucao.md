# Plano de evolucao do Assistente AD Balancas

> Escopo aprovado para execucao local com provedor sintetico. Nao autoriza processar Yahoo real, alterar instancias/portas, configurar WhatsApp, publicar ou expor a rede.

> **Estado em 02/10/2026:** etapas 1–3 implementadas localmente nesta branch. Validacao executada com SQLite temporario e fixtures sinteticas; nenhuma consulta real Yahoo foi iniciada. PostgreSQL, navegador manual e operacao das portas 8000/8011 nao foram testados nem alterados.

**Objetivo:** entregar, nesta ordem, automacao segura de e-mail com fixtures sinteticas, agenda Hoje e reformulacao progressiva da interface/navegacao.

**Arquitetura:** manter FastAPI, SQLAlchemy e Jinja2; expandir casos de uso/servicos existentes, sem agente SQL, SPA ou framework novo. Eventos externos entram por adaptadores limitados; o dominio valida, deduplica e emite evidencias. Escritas seguem os servicos existentes, rascunhos e confirmacao, exceto tarefas originadas de e-mail que cumpram a regra de alta confianca e idempotencia desta especificacao.

**Tecnologias e componentes:** Python, FastAPI, Pydantic, SQLAlchemy, Jinja2, JavaScript existente, pytest e provedores atuais Ollama/Yahoo IMAP/faster-whisper/Piper.

## Restricoes globais

- Preservar `/` e rotas atuais enquanto migra a navegacao; nao reescrever o frontend nem alterar fluxos existentes de propostas/Word.
- Desenvolver com banco isolado e mensagens sintéticas; nao ler/alterar dados operacionais durante implementacao/testes.
- Yahoo permanece somente leitura; nao alterar flags, mover, excluir ou enviar mensagens.
- E-mail e mensagens sao dados nao confiaveis; nao abrem ferramentas nem executam instrucoes nelas contidas.
- Criacao automatica se limita a tarefas de e-mail com categoria/acao/cliente/campos requeridos validados e referencia idempotente; financeiro fica como rascunho para conferencia.
- Nenhum pagamento, baixa, emissao fiscal, envio de documento, e-mail ou WhatsApp faz parte das fases descritas.
- Sem expor publicamente o app atual. Autenticacao/autorizacao efetiva e requisito de entrada para dados empresariais por rede externa.
- Datas e limites diarios usam timezone configurado (`America/Recife` por padrao atual); nenhum horario ou duracao e inventado.
- Nao ler ou imprimir arquivos de credencial `.env*`; testes devem fornecer segredos sinteticos injetados.
- `EMAIL_SYNC_ENABLED=false` e `EMAIL_AUTO_TASK_CREATION_ENABLED=false` por padrao; Yahoo real nunca sera instanciado nos testes.
- Nao processar a caixa Yahoo real nem iniciar sincronizacao real durante esta etapa.
- Preservar as instancias existentes nas portas 8000/8011; nao reiniciar nem reconfigurar seus ambientes.
- WhatsApp esta fora de escopo: nao configurar Meta/API/numero/webhook/tunel/SDK/terceiros.
- Nao fazer commit, push, merge, deploy nem publicar.

---

## Plano executavel vigente

O preflight confirma que a aplicacao nao tem autenticacao efetiva. Como esta execucao fica em loopback e nao altera host/porta, nao adicionar login agora; impedir/documentar qualquer exposicao externa ate que autenticacao, autorizacao e CSRF sejam implementados em escopo proprio.

### Etapa 1 — Sincronizacao sintetica, categorizacao e fila de revisao

**Dependencia:** executar preflight de isolamento; usar somente `SyntheticEmailReader` e banco/filesystem temporarios. Nada deve abrir socket IMAP nos testes.

**Arquivos implementados:**

- modificar `app/config.py` para intervalo, lote, lookback, habilitacao desligada e limites;
- modificar `app/models.py` com tabelas aditivas `inbox_emails`, `email_task_links`, `email_sync_states`; `Base.metadata.create_all` cria apenas tabelas ausentes em bancos existentes. Chave unica por provider/mailbox/referencia/acao;
- adicionar `app/assistant/email/sync.py` para sync unitario/incremental, pausa, estado de execucao, idempotencia e falha sanitizada; adicionar `worker.py` para ciclo serial em thread, desligado por padrao;
- ampliar `app/assistant/email/contracts.py`, `classification.py`, `synthetic.py` e `app/assistant/capabilities.py`; reutilizar `EmailReader`, `board_service.create_task` e estados existentes;
- adicionar rotas `/web/mensagens` em `app/routers/pages.py` e `app/templates_web/messages.html`; mostra estado, remetente/data/categoria/prioridade/razao/resumo, pausar/retomar e revisao da categoria;
- adicionar `tests/test_assistant_email_sync.py`, `tests/test_assistant_email_triage.py`, `tests/test_today_service.py`, `tests/test_today_routes.py` e ajustar `test_dashboard_routes.py` para o novo home; fixtures sao sinteticas.

**Criterios implementados:** sync e automacao de tarefa estao desligados por padrao. Quando opt-in, worker aguarda intervalo, executa serialmente fora do event loop, limita lote e aplica sobreposicao incremental. Falha persiste apenas codigo, nao conteudo de excecao; ciclo falho/parcial nunca significa caixa vazia. Releitura usa constraints idempotentes e reconciliacao persistente; cliente citado ambiguo ou inexistente vai para revisao. Categoria e classificacao deterministicas, sem inferencia de LLM. Pedido inequivoco de orcamento, pedido claro de conferencia fiscal e possivel resposta pendente com Entrada/Enviados completos podem gerar tarefa `a_fazer` somente com a flag ativada. Itens financeiros nunca criam/alteram `Lancamento`. Yahoo nao foi instanciado nos testes. Leitura nao muda flags; link/anexo nao processado. Corpo integral nao e persistido nem enviado a telemetria.

**Testes executados:** casos sinteticos para categorias, prompt injection, prazo explicito, automacao `a_fazer`, retry idempotente, cliente ambiguo/desconhecido, cobertura de Enviados, erro sanitizado e provedor failed versus empty; `create_all` aditivo preserva tabela/dado SQLite e migracao de cobertura preserva linhas. Flag de automacao explicitamente habilitada somente em teste. Nao foi feita validacao IMAP real nem exercitado timeout de socket; nao existe retry interno (a falha e tentada no proximo ciclo periodico). Alta confianca segue gate humano/configuravel/desligado por padrao. PostgreSQL segue sem validação.

### Etapa 2 — Agenda “Hoje”

**Dependencia:** etapa 1 para somar tarefas de email; pode ser implementada com fixture sem sincronizacao ativa.

**Arquivos implementados:** `app/services/today_service.py`, `/` em `app/routers/pages.py`, `app/templates_web/index.html` e testes `tests/test_today_service.py`, `tests/test_today_routes.py`, `tests/test_dashboard_routes.py`.

**Criterios implementados:** tarefas vencidas, hoje, proximas e tarefas de e-mail sem prazo; servicos com execucao ativa ou etapa administrativa pendente; lancamentos pendentes vencidos/proximos. Ordenacao deterministica por rank, prazo e identificador; cada item explica motivo e abre seu modulo. Lista read-only, sem horario inventado; KPIs mensais continuam recolhidos como painel secundario. E-mail pendente tem contador, nao afirma caixa vazia sem sync.

**Testes/risco:** fixtures controlam `America/Recife`, virada de dia, prazo ausente, feriado/fim de semana, chamado tecnico versus pendencia administrativa, Lancamento sem baixa, email sem dados e duplicate source. Testes garantem que construir Today e read-only. Validacao humana decide tamanho da janela “proximos”; enquanto isso usar sete dias configuraveis e rotulados como janela, nao prazo.

### Etapa 3 — Navegacao e paginas consistentes

**Dependencias:** etapa 2 para “Hoje”; modulo Inbox da etapa 1 existente. Sem dependencia de Yahoo real.

**Arquivos implementados:** `app/templates_web/base.html` com sidebar compartilhada, desktop recolhivel, drawer mobile, estado ativo, breadcrumb/voltar fallback, skip-link e `prefers-reduced-motion`; `index.html` e `messages.html`. Nao houve framework nem arquivo JS novo.

**Criterios implementados:** navegacao Jinja usa paleta/identidade existente, links reais, toggle desktop, drawer mobile com Escape, labels/aria-current, foco e breadcrumb/voltar com fallback. Home e `/web/mensagens` estao integrados ao shell; demais paginas mantem templates e URLs. Busca global adiada por falta de autenticacao. Tema escuro adiado ate revisar cores hardcoded/contraste; nao foi declarado acessivel sem teste visual.

**Testes executados:** renderizacao TestClient do home, Assistente e E-mails, marcadores de acessibilidade/navegacao e testes regressivos existentes. Validacao visual manual em larguras 360/768/desktop e navegador continua pendente.

### Evidencia final desta execucao

- Comando: `APP_ENV_FILE=/tmp/ad-balancas-no-env PYTHONPATH=. .venv/bin/pytest -q` — **442 passed, 5 skipped**. O caminho de configuracao apontava para um arquivo ausente em `/tmp`, portanto nenhum `.env` do projeto foi carregado. Testes usaram a fixture SQLite isolada em `/tmp`.
- `ruff check` passou nos modulos novos de sync, agenda e respectivos testes; `git diff --check` passou.
- A validacao de compatibilidade foi apenas SQLite. Nao houve servidor PostgreSQL para executar validacao PostgreSQL.
- Nao iniciado o aplicativo, Uvicorn, worker de sync, consulta Yahoo ou Ollama real. Portas 8000/8011 e dados operacionais permaneceram sem alteracao. Teste manual no navegador ainda pendente.

### Fora do escopo vigente

- Qualquer integracao/configuracao WhatsApp ou conta Meta.
- Qualquer leitura/sincronizacao real Yahoo ou validacao com e-mail operacional.
- Autenticacao para rede externa, deploy, novas portas ou modificacao das instancias 8000/8011.
- Blocos horarios e duracoes estimadas.

---

## Plano anterior arquivado (nao executar)

O conteudo abaixo preserva a primeira proposta de roadmap e fica superado pela ordem, escopo e regras acima. Em particular, fases de WhatsApp, processamento de Yahoo real e implementacao de login nao pertencem a este trabalho.

<details>
<summary>Roadmap anterior</summary>

## Fase 0 — Fundacao de seguranca e politicas de dados

**Dependencias:** nenhuma; obrigatoria antes de habilitar acesso externo, automatizar dados financeiros ou receber WhatsApp real. Pode preceder implementacao local de interface com synthetic.

**Arquivos provaveis:**

- modificar `app/models.py`, `app/config.py`, `app/main.py` para identidade de usuario/sessao/configuracao segura, sem credenciais no banco;
- adicionar `app/security/` ou `app/auth/` para autenticacao/autorizacao e CSRF, seguindo escolha revisada da arquitetura;
- modificar `app/routers/*.py` para exigir usuario e permissoes em todas as rotas mutaveis/de dados;
- adicionar `tests/test_authentication.py`, `tests/test_authorization.py`, `tests/test_csrf.py` e atualizar `tests/conftest.py`.

**Entregaveis e aceite:** login real, hash de senha robusto, sessao protegida e renovavel, protecao CSRF para formularios mutaveis, roles minimas e trilha de ator para acoes. Rotas sem permissao retornam 401/403; usuario inativo nao opera; caminho de desenvolvimento local fica explicito. Remover dependencia de senha padrao conhecida e exigir bootstrap operacional seguro. Nao liberar interface de internet ate fechar esta fase e revisar proxy/TLS/backup/logs.

**Riscos/testes:** risco de interromper uso atual; manter modo de transicao exclusivamente local, mas nao alegar que loopback equivale a autenticacao. Testar todas rotas existentes anonimas/autenticadas, session fixation, CSRF, autorizacao por modulo e regressao das operacoes de proposta/quadro/financeiro.

## Fase 1 — Shell de navegacao acessivel, gradual

**Dependencias:** pode ocorrer em paralelo com Fase 0 em banco de teste; nao depende de Yahoo/WhatsApp. Acesso externo continua bloqueado ate Fase 0.

**Arquivos provaveis:** `app/templates_web/base.html`; extrair estilos/JS comuns para `app/static/app.css` e `app/static/navigation.js` se reduzir duplicacao; macros Jinja2 em `app/templates_web/components/`; `app/routers/pages.py` para rotas/aliases; testes em `tests/test_navigation_routes.py`, `tests/test_template_accessibility.py` e `tests/js/navigation.test.mjs`.

**Entregaveis e aceite:** sidebar recolhivel em desktop, drawer em celular e botao toggle nomeado; estado ativo por rota; foco visivel, Escape/Tab/foco restaurado, skip-link e labels; breadcrumbs e “Voltar” contextual; tokens claro/escuro com escolha persistida localmente e respeito a tema/reducao de movimento do sistema. Manter paleta azul/verde, tipografia e cartoes atuais; aliases preservam URLs. Busca global fica somente no shell visual nesta fase e so e conectada depois de autorizacao e validacao por escopo.

**Riscos/testes:** largura de paginas Kanban e tabelas, menu em viewport estreito, contraste e scripts inline existentes. Rodar snapshot/rotas e navegacao por teclado; validar larguras 360, 768 e desktop, zoom 200%, leitor de tela basico e fluxo atual de propostas sem regressao. Nao redesenhar todas as paginas de uma vez.

## Fase 2 — Inbox de e-mail, classificacao e acao segura

**Dependencias:** reutiliza `EmailReader`, Synthetic e Yahoo IMAP atuais. Para conta real/conteudo ou aprovacao automatica, depender da Fase 0. Implementar/testar primeiro com provedor sintético. Nao depende da agenda nem do WhatsApp.

**Arquivos provaveis:**

- expandir `app/assistant/email/contracts.py`, `classification.py`, `provider.py` e `app/assistant/capabilities.py` com categorias, evidencias e destinos; adicionar `routing.py`/`triage_service.py` para decisao deterministica;
- adicionar tabelas aditivas em `app/models.py` para referencia/cursor de mensagem, classificacao/revisao e origem de tarefa; criar constraints unicas e migracao compativel com SQLite/PostgreSQL em `app/db.py` ou adotar ferramenta de migration aprovada antes desta fase;
- reutilizar `board_service.py`, `service_record_service.py` e servico de lancamentos para rascunhos, sem duplicar regras;
- expandir `app/assistant/service.py`, `contracts.py` e `routers/assistant.py` mantendo uma unica confirmacao/action ledger;
- adicionar `app/routers/messages.py`, pagina Jinja2 `app/templates_web/messages.html`, componente de revisao e links no `base.html`;
- testes novos provaveis: `tests/test_email_triage.py`, `tests/test_email_task_idempotency.py`, `tests/test_email_financial_drafts.py`, `tests/test_email_readonly.py`, `tests/test_email_prompt_injection.py`, `tests/test_messages_routes.py` e fixtures synthetic; manter `tests/test_assistant_email*.py`.

**Entregaveis e aceite:** cobertura de todas as categorias/tabela da especificacao, ranking explicado por prazo/impacto/acao, explicito vs inferido, fila de revisao e estados do provedor. Alta confianca e limiar por categoria sao aprovados por avaliacao humana antes de habilitar auto-tarefa; incerteza em intencao, categoria, cliente, prazo ou valor necessario encaminha para revisao. Mensagem identificada por chave estavel (`provider/mailbox/folder/UIDVALIDITY/UID` ou id equivalente); unique constraint impede duplicar por releitura/retry; timeout reconcilia antes de gravar novamente. Tarefa automatica guarda referencia de origem e link; lancamento nunca passa de rascunho ate revisao/confirmação. Releitura nao marca como lido; falha IMAP nao vira “vazio”; nenhuma acao faz escrita no provedor.

**Testes:** matrix sintetica incluindo fornecedor/cliente ambiguos, orçamento vs cotacao, PO, NFs, pagar/receber, comprovante, chamado/inspecao, pendencia de resposta e publicidade; prova de imutabilidade de `\\Seen`; duas leituras e retry; timeout antes/depois de commit; prompt injection; cliente nao cadastrado; Enviados indisponivel e consulta parcial/desatualizada. Real Yahoo e opt-in limitado apos revisar auth, com relatorio sem PII. Nenhum e-mail de producao em fixtures, logs ou snapshots.

**Riscos:** falso positivo cria tarefa operacional; correlacao de email pode falhar com mudanca de UIDVALIDITY; pasta Enviados incompleta; valores/prazos extraidos incorretamente. Kill switch por config desativa classificacao/automacao sem parar o assistente textual.

## Fase 3 — Pagina Hoje e lista priorizada

**Dependencias:** servicos atuais de tarefas, chamados e lancamentos; Fase 2 apenas para incluir itens/tarefas relacionados a email. Sem Fase 2, a secao de email informa indisponibilidade e nao inventa dados.

**Arquivos provaveis:** `app/services/today_service.py` (novo, agregacao/deduplicacao/prioridade), `app/schemas.py` (view models), `/` em `app/routers/pages.py`, `app/templates_web/index.html` ou `today.html`, e `tests/test_today_service.py`, `tests/test_today_routes.py`.

**Entregaveis e aceite:** combina tarefas incompletas atrasadas, prazo hoje/proximos, origem de email, servicos em andamento/próxima etapa e lancamentos que exigem conferencia/atencao. Cada item mostra regra/motivo e link para fonte; distingue status confirmado, desconhecido e aguardando terceiro. Ordenacao deterministica documentada, zona `America/Recife`, limites do dia corretos e janela futura configuravel. Nao altera nenhum registro. A UI chama a pagina “Hoje”, substituindo gradualmente o resumo mensal na rota `/`; manter KPIs mensais secundarios acessiveis.

**Testes:** hoje, virada de dia/fuso, vencidos, status concluidos, etapas desconhecidas/aguardando cliente, rascunho nao contabilizado, origem vinculada, duplicados, empate deterministico, erro parcial e ausencia de dados. Playwright/browser manual testa links e celular. Nenhum bloco horario; teste verifica que nenhum `start_time`/duracao e sintetizado.

**Riscos:** ordenacao subjetiva, lancamentos sem origem e duplicacao do mesmo fato em tarefa e servico. Exibir origem/tipo e deduplicar apenas por FK/referencia real, nunca por similaridade textual destrutiva. Alteracao de prazo/status/responsavel exige fluxo confirmado do modulo.

## Fase 4 — Evolucao gradual das paginas e busca

**Dependencias:** Fase 1 para tokens/shell; Fase 0 antes da busca por dados pessoais ou expansao de permissao. Pode ser entregue modulo por modulo, independente de WhatsApp.

**Arquivos provaveis:** `app/templates_web/{board,services,service_detail,assistant,proposals,clients,lancamentos_board}.html`; `app/routers/pages.py`, `board.py`, `services.py`, `financeiro.py`; macros/componentes Jinja2 e CSS comum; `app/services/search_service.py` e `/api/search` apos autorizacao; testes de rota, consulta e acessibilidade por cada modulo.

**Ordem sugerida:** Hoje → Tarefas → Servicos → Mensagens/Email → Propostas → Clientes → Contas a Pagar/Receber → Administracao. Em cada etapa, preservar forms, links, IDs, estados Kanban e regras de dominio existentes. Para cada pagina usar a tabela de objetivo, informacao prioritaria, acoes, entrada/saida de `especificacao-produto-evolucao.md`.

**Aceite:** componentes consistentes de filtro, vazio, carregamento, confirmacao e erro; responsividade sem perder informacao; caminhos antigos continuam funcionando; busca global sempre aplica permissao/escopo e retorna tipo/origem explicita, sem consultar corpo de e-mail por padrao. Administracao nao mostra segredos nem permite configurar senha de Yahoo em HTML/logs.

**Riscos/testes:** mudanca visual regressiva ou links quebrados. Testes de rotas/render, links internos, contraste, teclado e navegacao manual cobrindo operacoes que o usuario ja utiliza (nova proposta, Word, quadro, financeiro, clientes e servicos).

## Fase 5 — WhatsApp Cloud API, recebimento e triagem somente

**Dependencias:** Fase 0 obrigatoria, revisao de privacidade/rede, WABA e numero elegivel. Infra de HTTPS publico para apenas webhook. Manter fase opt-in, synthetic primeiro, sem envio. Pode ocorrer independente das Fases 2/3, mas so compartilhar a Inbox quando o contrato comum de mensagem/origem estiver estabilizado.

**Arquivos provaveis:** `app/messaging/whatsapp/contracts.py`, `webhook.py`, `signature.py`, `deduplication.py`; `app/routers/whatsapp_webhook.py` ou gateway isolado; `app/models.py` para evento/source idempotente e status; `app/config.py` para feature flags e segredos via environment/secret manager; worker/queue persistente limitada; `tests/test_whatsapp_webhook.py`, `test_whatsapp_signature.py`, `test_whatsapp_deduplication.py`, `test_whatsapp_privacy.py`; atualizar mensagens na Inbox sem misturar canais.

**Entregaveis e aceite:** validacao GET/handshake e assinatura de POST conforme docs oficiais, allowlist de tipos, persistencia minima, resposta HTTP rapida e trabalho fora do handler, chave unica pelo ID da mensagem Meta, protecao contra replay/duplicata, retry seguro, fila limitada e estado de falha recuperavel. Recebimento apenas de texto/metadados na primeira fase; midia nao baixa. Triagem/acao usa mesmo review flow e confirmacao das fases existentes. Nenhuma rota de envio e nenhum token no log/banco aberto.

**Teste/validacao:** payloads oficiais/sinteticos; assinatura valida/invalida; token de verificacao errado; origem nao inscrita; duplicados e eventos fora de ordem; app indisponivel; payload enorme/malformado; filas saturadas; segredo ausente; redacao de PII nos logs. Real Meta apenas com numero/WABA de teste e webhook HTTPS temporario autorizado, seguido de desligamento do tunel. Nenhum contato/cliente real inicialmente.

**Riscos:** exposição publica, custo e termos variaveis, duplicacao/retry Meta, PII, indisponibilidade do PC e risco de desconectar numero usado em aplicativo. Nunca apontar o callback a toda a instancia loopback. Nao operar ate o responsavel confirmar conta/numero, politica de retencao, custo e disponibilidade continua.

## Fase 6 — Planejamento horario (opcional e posterior)

**Dependencias:** dados de jornada, compromissos fixos, estimativas, locais/deslocamento e disponibilidade dos responsaveis fornecidos e revisados pelo negocio. Nao bloqueia Hoje.

**Arquivos provaveis:** entidades/configuracao de disponibilidade somente apos decisao; `app/services/scheduling_service.py`; UI/calendario e testes de conflito/intervalo. Nao selecionar biblioteca/calendario antes de avaliar necessidade e politica de dados.

**Aceite:** horario e duracao sao rotulados como sugestoes calculadas a partir de fontes identificadas; nenhum bloco e salvo sem confirmacao; conflitantes e incerteza vao para lista priorizada sem hora. Testes de fuso, jornada, deslocamento, estimativa ausente, conflito, urgencia e confirmacao.

---

## Sequencia e portas de validacao

```text
Fase 0 (seguranca) ──────────┬──> Fase 2 (email) ──┬──> Fase 3 (Hoje completo)
                            │                    └──> Fase 4 (mensagens/busca)
Fase 1 (shell/UI) ──────────┴──> Fase 3/4
Fase 0 + WABA/HTTPS ────────────> Fase 5 (WhatsApp recebido)
Dados de agenda/jornada ────────> Fase 6 (sugestao horaria opcional)
```

Cada fase tem gate de avaliacao e opt-in separado; resultados de uma nao ativam gravacoes de outra. Todos os testes de servicos devem usar banco de teste segregado. A porta 8000 e os bancos/arquivos reais continuam fora do ambiente de validacao.

## Informacoes de negocio ainda necessarias

Nao sao bloqueio para este plano documental; tornam-se pre-requisitos apenas para habilitar estas partes:

1. **Email:** pessoas autorizadas a revisar tarefas/rascunhos e prazo de retencao de resumo/evento operacional; prioridades/SLAs por tipo de cliente se diferentes da regra generica. Limiar de alta confianca sai da avaliacao humana, nao de escolha do usuario sem dados.
2. **Hoje:** quantidade de dias da janela “proximos” e confirmacao de que feriados/fins de semana devem apenas informar ou afetar ordenacao. Jornada por tecnico, duracoes e deslocamentos sao necessarios somente para a fase opcional de blocos de horario.
3. **Acesso:** responsaveis/roles e metodo de login desejado antes de ativar autenticacao para mais de uma pessoa ou receber dados externamente. A auditoria nao encontrou login real.
4. **WhatsApp:** titularidade e tipo do numero atual (WhatsApp pessoal ou Business), WABA/portfolio Meta existente, elegibilidade de coexistencia/migracao confirmada pela Meta, telefone que recebe codigo, responsavel pela conta e permissao para configurar app/token. Sem isso, nenhum numero e conectado.
5. **WhatsApp/operacao:** decisao de infraestrutura (dominio/HTTPS publico, relay ou host gerenciado), disponibilidade/plantao, retencao, aviso/consentimento aplicavel e teto orcamentario. Custos Meta mudam; verificar rate card vigente antes de solicitar billing.

## Validacao deste documento

- Inspecao executada: rotas, paginas Jinja2, modelos, servicos e contratos listados na secao de linha de base da especificacao.
- Pesquisa atual executada em 02/10/2026: fontes oficiais Meta/Postman e termos/politica WhatsApp citados em `especificacao-produto-evolucao.md`; paginas `developers.facebook.com` deram rate limit ao navegador, por isso as referencias oficiais Postman da Meta foram usadas para requisitos tecnicos acessiveis.
- Nao foram executados testes de aplicacao, consultas a Yahoo, acesso a banco, validacao com WABA/numero, webhook ou verificacao manual de numero existente. Nao houve alteracao de codigo, ambiente, dados, credenciais, porta ou processo.
</details>
