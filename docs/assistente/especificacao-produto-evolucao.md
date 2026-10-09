# Especificacao de produto — Assistente operacional AD Balancas

**Status:** escopo aprovado e primeira fatia implementada localmente com dados sinteticos; Yahoo real e WhatsApp explicitamente fora desta etapa.  
**Auditoria do codigo:** 02/10/2026.  
**Escopo:** priorizar (1) automacao de e-mail, (2) agenda “Hoje” e (3) reformulacao gradual da interface/navegacao. WhatsApp permanece ideia futura, sem configuracao Meta, API, numero, webhook, SDK ou servico de terceiro.

**Atualizacao de validacao em 02/10/2026:** consultas conhecidas de categorias de e-mail agora sao roteadas deterministicamente antes do Ollama; a classificacao acontece sobre os candidatos consultados no periodo antes do limite visual/de contexto. A verificacao de escopo e o tratamento de erro distinguem leitura de mensagens sobre nota/conta de pedidos para emitir ou pagar. A falha do Ollama continua explicita e retryavel, sem afirmar resultado quando a resposta estruturada e invalida. A voz pausa apos a transcricao para revisao/edicao antes do envio. Foram executados 467 testes Python, 21 testes JavaScript e cinco smoke cases com Ollama real e mensagens sinteticas; nenhuma consulta Yahoo real foi feita. A interface completa no navegador continua pendente por indisponibilidade de browser de teste.

## 1. Visao e principios

O assistente e uma interface operacional por texto e voz, nao um agente com acesso livre. Interpretacao e classificacao podem sugerir; servicos Python validam, consultam dados reais e controlam escritas. Toda resposta factual precisa apontar para consulta executada ou dado persistido; toda alteracao operacional requer confirmacao humana, exceto a criacao automatica restrita de tarefas de e-mail explicitamente autorizada nesta especificacao.

Principios que atravessam as fases:

- manter FastAPI, SQLAlchemy, Jinja2, JavaScript simples, modelos e servicos existentes; sem SPA ou migracao de framework;
- manter a fala como camada de entrada/saida do mesmo fluxo de conversa e confirmacao;
- tratar corpo de e-mail e mensagens recebidas como dados externos nao confiaveis; nunca como instrucao para ampliar ferramentas;
- manter e-mail Yahoo em leitura somente: nao alterar flags, pastas ou mensagens, nao abrir links, nao baixar/abrir anexos e nao enviar;
- nao pagar, dar baixa, emitir nota fiscal ou proposta, nem responder automaticamente a cliente;
- separar sugestao de prioridade de alteracao efetiva de prazo, status ou responsavel;
- usar dados, bancos, contas e mensagens sinteticas nos testes; nao usar o banco operacional na implementacao;
- nao abrir publicamente a aplicacao atual. A auditoria nao encontrou autenticacao efetiva nas rotas web/API; esse e um bloqueio antes de qualquer exposicao de paginas ou dados a rede externa.
- sincronizacao automatica inicia desligada por padrao; testes nunca leem caixa Yahoo nem acionam sincronizacao real;
- nao alterar a porta 8000 nem instancias fora da 8011; a 8011 e a instancia de validacao explicitamente autorizada para reinicio em modo sintetico, banco e arquivos isolados.

## 2. Linha de base auditada

Auditoria somente de leitura de `app/routers`, `app/assistant`, `app/services`, `app/models.py`, `app/config.py`, `app/main.py` e `app/templates_web`.

| Capacidade | Estado atual identificado no codigo | Reuso / lacuna para esta evolucao |
|---|---|---|
| Assistente | `/web/assistente`; texto, voz local e contratos de ferramenta; `AssistantService`, Ollama, faster-whisper, Piper, capacidades e verificacao de evidencias. | Reutilizar orquestracao, estado de conversa, confirmacao, datas Recife e voz. Novos canais nao criam um segundo fluxo de acao. |
| Tarefas | `Task`, `board_service`, quadro `/web/board`, estados existentes e movimento pelo endpoint. Tarefa admite cliente, proposta, responsavel e prazo opcionais. | Tarefas oriundas do Inbox reutilizam `board_service.create_task`; origem/categoria/motivo ficam em `email_task_links`; a unicidade por mensagem/acao mantem a correlacao mesmo se a tarefa for removida. |
| Servicos | `ServiceCall`, eventos append-only, correcoes append-only, projecao de execucao, etapas administrativas e transicoes auditaveis; `/web/services` e detalhe. | Reutilizar `service_record_service`; chamada de e-mail deve passar por rascunho e confirmacao existentes. Inspecao permanece distinta de execucao. |
| Financeiro | `Lancamento` com pagar/receber, valor, emissao, vencimento, status pendente/pago e vinculos opcionais a cliente/proposta; quadros e formularios proprios. | Pode alimentar Hoje. E-mail apenas propoe rascunho de Lancamento para conferencia; nao pagar, baixar ou assumir valores/datas incertos. |
| Propostas | Entidade/servico/rotas de criacao, revisao, duplicacao e documentos Word/PDF; pagina e upload/reupload. | Reutilizar links e clientes. Mensagem nao deve gerar/enviar proposta; pedido vira tarefa ou revisao conforme a classificacao. |
| Clientes | Cadastro e API de clientes; propostas e tarefas se relacionam por FK. | Resolver nomes contra cadastro existente. Correspondencia ambigua sempre vai para revisao. |
| E-mail | `EmailReader` substituivel, adaptador IMAP Yahoo, provedor sintetico, leitura somente leitura e limites. | Agora existem classificacao estruturada deterministica, projecao persistente sem corpo integral, origem/task link idempotentes, estado de sync, cobertura de Entrada/Enviados, worker opt-in e Inbox `/web/mensagens`. `EMAIL_SYNC_ENABLED` e `EMAIL_AUTO_TASK_CREATION_ENABLED` sao falsos por padrao. Nenhum teste nem worker real Yahoo foi executado. |
| Navegacao/UI | Jinja2 server-rendered, identidade azul/verde, Barlow/Trebuchet, cartoes e tabelas. | Agora `/` e a agenda “Hoje”, mantendo KPIs mensais em painel recolhivel; shell tem sidebar colapsavel/drawer, estado ativo, breadcrumbs, retorno com fallback e skip-link. Busca global e tema escuro ficam adiados por ausencia de autenticacao efetiva e validacao de contraste/escopo, respectivamente. |
| Administracao/autenticacao | Pagina `/web/users` e APIs de cadastro; usuario/modelo nao implicam login. `main.py` inicializa usuario padrao. Nao foi identificada dependencia global de usuario autenticado/autorizacao nas rotas analisadas. | Criar a fase de autenticacao/autorizacao antes de disponibilizar busca agregada com conteudo, fila financeira/e-mail, webhook ou acesso fora do loopback. |

### Paginas/rotas existentes observadas

- Inicio/Hoje: `/`; lista priorizada de tarefas abertas com prazo dentro da janela ou origem de e-mail, chamados em execucao/etapas administrativas pendentes e lancamentos com vencimento na janela. KPIs mensais continuam em detalhe recolhivel.
- Tarefas: `/web/board`, `/web/board/new`, edicao por tarefa; cinco colunas, cartoes com prazo/cliente/responsavel/proposta e drag-and-drop.
- Servicos: `/web/services` e `/web/services/{service_call_id}`; lista e detalhe com execucao, etapas e historico.
- Assistente: `/web/assistente`; texto e voz na mesma tela.
- Propostas: `/web/proposals`, `/web/proposals/new`, `/web/proposals/{id}`, upload externo e reenvio Word.
- Clientes: `/web/clients`, criacao, detalhe/edicao. Usuarios: `/web/users` e cadastro.
- Contas a pagar e receber: `/web/contas-a-pagar` e `/web/contas-a-receber`, formularios e movimento de status.
- Importacao de proposta: `/import-proposals`.
- E-mails e mensagens: `/web/mensagens`, consulta da projecao local, estado, pausar/retomar e revisao manual de categoria. Nao ha acao que altere a mensagem remota.
- Nao existe pagina autenticada `/web/administracao`; usuarios continuam em `/web/users` sem representar login.

## 3. E-mail: triagem e automacao controlada

### 3.1 Classificacao estruturada

Cada mensagem analisada recebe `category`, `confidence_band`, evidencias, campos extraidos, `explicit_deadline`/`inferred_deadline`, impacto, proxima acao e destino. Prioridade deve expor fatores legiveis: proximidade do prazo explicitamente indicado, impacto do atraso, dependencia de cliente/fornecedor, trabalho tecnico interrompido, risco financeiro e existencia de uma acao concreta. Um adjetivo isolado como “urgente” nao determina prioridade. Prazos inferidos nunca sao apresentados como prazo combinado.

| Categoria | Destino padrao | Regra de seguranca |
|---|---|---|
| Pedido de orcamento/cotacao enviado por cliente | Tarefa automatica em `A fazer` quando categoria e acao atingirem alta confianca e os dados indispensaveis forem claros; senao fila `Revisar`. | Nao criar proposta nem inventar escopo, quantidade, equipamento, valor ou prazo. |
| Cotacao recebida de fornecedor | Somente classificacao se informativa; tarefa apenas quando houver acao clara (comparar, aprovar, responder); duvidas para revisao. | Cotacao nao e conta a pagar. |
| Pedido/ordem de compra | Tarefa `A fazer` apenas se a acao operacional estiver explicita e classificada com alta confianca; senao fila `Revisar`. | Nao inferir aceite, contrato, estoque, valor final ou execucao. |
| Solicitacao para emitir/enviar nota fiscal | Tarefa `A fazer` para conferencia quando pedido/intencao forem claros; senao fila `Revisar`. | Nunca emite, altera documento fiscal ou envia mensagem/documento. |
| Nota fiscal recebida | Tarefa `A fazer` de conferencia ou fila `Revisar`; pode haver rascunho nao contabilizado depois de revisao humana. | Sem pagar, marcar quitacao ou assumir valor/vencimento ausente. |
| Conta a pagar / cobranca de fornecedor | Tarefa de conferencia `A fazer` ou fila `Revisar`; rascunho financeiro so por acao humana explicita posterior. | Vencimento explicito separado de data inferida; nunca efetua pagamento. |
| Cobranca ou conta a receber | Tarefa de conferencia `A fazer` ou fila `Revisar`; rascunho financeiro so por acao humana explicita posterior. | Nunca dar baixa nem marcar recebido. |
| Comprovante de pagamento | Fila `Revisar` vinculada a lancamento candidato se houver correspondencia clara; opcional tarefa de conciliacao. | Um comprovante nao prova liquidacao bancaria nem autoriza baixa. |
| Chamado ou servico | Tarefa `A fazer` para triagem quando inequívoca; registro de chamado continua no fluxo confirmado existente. | Diferenciar inspecao, execucao e conclusao tecnica. Nunca criar servico automaticamente so por classificar o e-mail. |
| Resposta pendente | Tarefa automatica `A fazer` apenas para pedido de resposta explicito, cobertura suficiente de Enviados e confianca alta; senao fila `Revisar`. | E uma inferencia sobre conversa: comparar Entrada e Enviados, informar cobertura e incerteza. |
| Informativo/publicidade | Somente classificacao/arquivo visual na lista. | Nao criar tarefa por defeito. Nao mover nem marcar mensagens. |
| Outra mensagem que requer triagem | Fila de revisao com categoria “outra/nao determinada”. | Nao converter silenciosamente em tarefa, servico ou lancamento. |

### 3.2 Regras de confianca e revisao

“Alta confianca” nao e um percentual bruto declarado pelo LLM. No piloto, e uma regra deterministica restrita por categoria/acao; a classificacao e revisavel e nao cria tarefas para financeiro/fiscal. Se cliente estiver ausente ou ambíguo, uma acao operacional reconhecida ainda pode criar tarefa textual ligada a origem, com `client_id` vazio e estado de vinculo pendente; a falta do cadastro nunca descarta a tarefa. Incerteza de categoria/intencao mantem a mensagem na fila de revisao. Prazo/valor incerto nao e inventado nem gravado como fato.

Cada automacao registra a mensagem de origem por referencia opaca do provedor e a decisao estruturada. Chave unica idempotente proposta: `provider + mailbox_id + folder_role + UIDVALIDITY + UID` (ou equivalente estavel do provedor); uma mesma origem pode gerar no maximo uma tarefa automatica por `action_type`. Releitura, sincronizacao repetida, evento duplicado ou retry retornam o resultado ja persistido. Se a mensagem nao puder ser identificada de forma estavel, nao criar automaticamente.

O sincronizador e periodico, com intervalo/lote configuraveis, execucao sequencial em thread worker e limite de mensagens por ciclo. `EMAIL_SYNC_ENABLED=false` e `EMAIL_AUTO_TASK_CREATION_ENABLED=false` por padrao. Quando ativado, persiste `activation_at` antes da primeira consulta, faz um ciclo imediato e nunca consulta antes desse limite; ciclos seguintes aplicam um dia de sobreposicao limitado ao mesmo instante. A tela mostra ultimo ciclo, estado/erro sanitizado e pausar/retomar localmente. O worker e single-flight dentro de cada processo; a constraint unica protege repeticoes entre ciclos. Nao ha lease distribuido entre multiplos processos, por isso nao habilitar workers em replicas concorrentes.

No piloto local, pedido inequívoco de orçamento/cotacao, ordem de compra reconhecida e solicitação explícita de serviço/atendimento podem gerar tarefa `a_fazer` idempotente quando `EMAIL_AUTO_TASK_CREATION_ENABLED=true`. Solicitação de nota fiscal, notas recebidas, contas e pagamentos ficam para revisão e não criam lançamentos; resposta pendente não gera tarefa automaticamente nesta configuração. A correspondência única resolve `client_id`; nome ausente usa `Cliente a identificar`; cliente citado e não cadastrado usa o texto informado; nomes ambíguos ficam “a confirmar”. Nos casos sem vínculo único, a tarefa é criada e permanece revisável, sem cadastro fictício. Categoria, confiança, motivo, estado lido, cobertura e chave de origem ficam no Inbox; tarefa referencia provedor/caixa/mensagem em tabela idempotente. O sincronizador não apaga esses vínculos caso a tarefa seja apagada.

Mensagem e conteudo externo: prompt injection, anexos, links e texto com instrucoes nao autorizam novas capacidades. Nesta fase nao se abrem links, nao se baixam/abrem anexos e nao se emite/envia nada. A leitura Yahoo continua IMAP somente leitura e teste sem escrita de flags.

Testes automatizados usam somente fixtures sinteticas e nao instanciam o leitor Yahoo real. A consulta real, quando autorizada, fica limitada a uma instância isolada cujo primeiro intervalo parte do `activation_at`; não usar caixa real nos testes automatizados.

### 3.3 Historico, cache e privacidade

Persistencia implementada: identificador opaco, remetente, assunto, data, flag vista fornecida pelo servidor, resumo ate 400 caracteres, categoria, confianca, razao, prioridade, prazo explicito, status de revisao e vinculo de tarefa. O corpo integral nao e armazenado. Remetente/assunto/resumo sao dados pessoais/comerciais e ficam no banco local sem expiracao automatica implementada; definir e implementar retencao/expurgo antes de habilitar sync real. Segredos e raciocinio interno nao sao persistidos. Erros do worker persistem apenas estado/codigo de classe, nao texto de excecao. Testes nao enviam corpo ou credencial aos logs.

## 4. Agenda diaria “Hoje”

“Hoje” e uma **lista priorizada**, nao calendario por hora. No topo mostra resumo do dia e contagens de prioridades, atrasos, e-mails novos e itens aguardando revisao. Mostra conjunto e razao para ordenar:

1. itens vencidos, abertos e acionaveis (tarefa atrasada, etapa de servico pendente com risco operacional, lancamento vencido que aguarda acao humana);
2. compromisso/prazo explicito para hoje, distinguindo fonte e natureza;
3. tarefa ou solicitacao de e-mail com prazo explicito proximo;
4. servico em andamento e proxima etapa administrativa confirmada, separando pendente, aguardando cliente e desconhecida;
5. recebiveis/pagaveis pendentes por data de vencimento, sem recomendar pagar/baixar;
6. proximos prazos em janela configuravel, abaixo do que ja venceu/vence hoje.

Empates ficam estaveis por data explicita mais proxima, impacto explicado, dependencias externas, prioridade manual existente se houver, depois identificador/data de criacao. Cada cartao inclui “por que aparece aqui”, origem (quadro, chamado, mensagem ou financeiro), data confiavel e link para o registro. A lista remove duplicacao por referencia do item, nao esconde alertas apenas por ser fim de semana e respeita fuso `America/Recife`.

O usuario pode pedir ao assistente que recomende outra ordem; recomendacao nao salva mudancas. Hoje somente oferece links para abrir os registros; acoes concluir/adiar continuam nos fluxos existentes, nao duplicadas na agenda. Alterar prazo, status, responsavel ou estado financeiro exige a confirmacao ja aplicavel no modulo. Dados financeiros incompletos/ambiguos nao aparecem como compromisso certo.

Blocos horários agora são sugestões determinísticas da página Hoje e do Assistente, no fuso configurado da aplicação (`America/Recife`). Disponibilidade semanal, janelas de trabalho, intervalos e compromissos recorrentes/avulsos precisam ser configurados; sem janela para o dia, nenhum horário é presumido livre. Tarefas usam a estimativa individual em minutos ou, quando ausente, o padrão editável de 60 minutos, sempre rotulado como estimativa. A alocação mantém a ordem compartilhada por atraso, prazo, urgência explícita e status, respeita blocos contínuos e mostra itens que não couberam e o motivo. Não há dependências formais, duração real, deslocamento ou buffers avançados no modelo atual; nenhuma dessas informações é inventada.

Gerar e visualizar é somente leitura e não altera tarefa ou calendário externo. Para persistir, o usuário pede explicitamente para salvar a agenda e confirma uma prévia. Isso grava um snapshot versionado para a data; salvar novamente exige confirmação de substituição e mantém a versão anterior. `AssistantAction` e a chave idempotente evitam duplicação em retry. O fluxo está disponível por texto/voz e a proposta é renderizada em Hoje. Não há sincronização com Google Calendar ou Outlook nesta fase.

## 5. WhatsApp futuro — ideia fora do escopo vigente

Nenhuma configuracao Meta, API, numero, webhook, tunel, SDK ou servico de terceiro sera feita nesta etapa. Se houver fase futura, a direcao registrada permanece a Cloud API oficial; os apontamentos abaixo sao apenas referencias pesquisadas, nao trabalho autorizado agora. Nao usar automacao de WhatsApp Web, scraping ou bibliotecas nao oficiais. O primeiro escopo futuro seria receber, deduplicar e classificar mensagens; envio fica fora ate autorizacao separada.

Requisitos apurados nas referencias oficiais Meta consultadas em 02/10/2026:

- portfolio empresarial Meta, WhatsApp Business Account (WABA), aplicativo Meta for Developers e numero empresarial elegivel/verificavel; vinculacao e permissoes/token devem seguir onboarding oficial da conta;
- endpoint HTTPS publicamente alcancavel, certificado TLS valido, verificacao do handshake do webhook, validacao criptografica da assinatura do payload com o segredo do app, allowlist de campos/tipos e rejeicao segura de eventos invalidos;
- assinar/inscrever a aplicacao na WABA para receber eventos. Payload pode conter conteudo pessoal, identificador de mensagem/numero, timestamp e tipo (texto ou midia); guardar somente o necessario, com acesso/retencao documentados;
- custos e regras comerciais sao controlados pela tabela/preco atual da Meta e podem mudar; nao incluir estimativa fixa no plano. Antes de orcar/ativar, consultar a rate card da regiao/mercado e simular volume e categorias;
- politicas podem exigir modelos aprovados para mensagens iniciadas pela empresa, janela de atendimento, consentimento e escalonamento humano. Embora esta fase nao envie, a arquitetura futura nao deve tratar webhook recebido como autorizacao para responder.

Fontes oficiais: [colecao WhatsApp Business Platform da Meta](https://www.postman.com/meta/whatsapp-business-platform/overview), [Cloud API e requisitos de conta](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api), [webhooks e HTTPS](https://www.postman.com/meta/whatsapp-business-platform/folder/tduohwq/webhook-payload-reference), [assinatura/inscricao da WABA](https://www.postman.com/meta/whatsapp-business-platform/folder/ozgs3jn/webhook-subscriptions), [termos e cobranca Meta](https://www.whatsapp.com/legal/meta-terms-whatsapp-business), [politica de mensagens](https://business.whatsapp.com/policy/preview?lang=pt_BR). Documentacao de coexistencia/eligibilidade do numero existente ainda precisa ser confirmada no fluxo da conta Meta; nao presumir suporte.

### Loopback e operacao

- **Registro para avaliacao futura, nao executar agora:** o backend permanece em loopback; caso exista aprovacao futura, desenvolver primeiro com payloads sinteticos e endpoint de teste separado. Operacao futura exigiria endpoint publico isolado e HTTPS, nunca tunel para a aplicacao toda. Nenhuma dessas infraestruturas faz parte desta etapa.

O numero atualmente usado em aplicativo nao foi verificado, e o tipo do aplicativo/conta e elegibilidade de coexistencia nao podem ser inferidos por codigo. Migrar/registrar numero pode alterar disponibilidade no aplicativo dependendo do caminho oficial escolhido. Nenhum numero sera conectado sem confirmar titularidade, tipo de app, capacidade de receber SMS/ligacao de verificacao e elegibilidade exibida pela Meta, com plano de rollback operacional.

## 6. Navegacao e experiencia visual

Preservar identidade atual (paleta azul/verde, Barlow/Trebuchet, cartoes, badges, tabelas, bordas e raios), FastAPI/Jinja2, rotas atuais e formularios usados. Implementados shell lateral, recolhimento no desktop, drawer no celular, estado ativo, Escape, skip-link, breadcrumbs/voltar com fallback, foco por teclado e respeito a `prefers-reduced-motion`. Rotas legadas permanecem.

Busca global foi adiada: sem login efetivo, uma busca agregada ampliaria acesso a dados pessoais/comerciais e nao e segura para ativar. Tema escuro tambem foi adiado ate inventariar cores hardcoded e validar contraste; o shell atual segue claro. Manter foco visivel, labels, controles operaveis por teclado, estados vazios e mensagens consistentes como trabalho progressivo por pagina.

| Pagina | Objetivo e informacao prioritaria | Acoes | Entrada e saida |
|---|---|---|---|
| Hoje (`/`, mantendo rota) | Lista priorizada do dia: atrasos, prazos proximos, tarefas de e-mail, servicos e financeiro; resumo e contagens, motivo e fonte por item. | Abrir registro; pedir recomendacao; confirmar conclusao/adiamento antes da gravacao. | Entrada pela raiz/home; sai para detalhe do item, Assistente ou modulo correspondente. |
| Assistente (`/web/assistente`) | Conversa texto/voz, capacidades e confirmacoes pendentes. | Consultar, preparar tarefa/registro e confirmar/cancelar. | Menu ou CTA Hoje; retorno ao Hoje ou link direto ao objeto criado. |
| Tarefas (`/web/board`) | Quadro Kanban atual com filtros por cliente, responsavel, prazo, origem e estado. | Criar, editar, mover e concluir conforme regras existentes; filtros nunca mudam estado. | Hoje/Assistente/Mensagens; sai para tarefa, chamado, cliente ou proposta vinculada. |
| Servicos (`/web/services`) | Chamados abertos, estado tecnico, administrativo, proxima etapa e historico. | Abrir chamado/detalhe, consultar eventos e criar lembrete pelo fluxo confirmado. | Hoje/Assistente/Mensagens; volta a lista/Hoje, links para tarefas/cliente. |
| E-mails (`/web/mensagens`) | Entrada Yahoo rotulada como somente leitura, estado/ultima sincronizacao, categorias, prioridade/motivo, origem, dados principais e fila “Revisar”. | Filtrar, pausar/retomar sync, revisar classificacao e abrir tarefa vinculada; nunca enviar/alterar mensagem. | Menu/Hoje/Assistente; sai para tarefa, chamado, cliente ou financeiro. |
| Propostas (`/web/proposals`) | Historico, cliente, data, responsavel, origem e valor; preservar edicao Word e documentos atuais. | Nova, abrir, duplicar, revisar, upload/reupload existente. | Clientes/Tarefas/Assistente/Hoje; detalhe volta a lista/cliente/Hoje. |
| Clientes (`/web/clients`) | Cadastro e relacoes recentes com propostas/tarefas/servicos. | Buscar, criar, editar e navegar relacoes. | Busca global ou qualquer detalhe; volta ao modulo de origem ou lista. |
| Contas a Pagar (`/web/contas-a-pagar`) | Pendentes/pagas, vencimento, fornecedor, valor, origem e itens aguardando conferencia. | Abrir/editar/mover estado manualmente; revisar rascunho de e-mail e confirmar explicitamente. | Hoje/Mensagens/Propostas; retorna ao Hoje ou origem. |
| Contas a Receber (`/web/contas-a-receber`) | Pendentes/pagas, vencimento, cliente, valor, proposta relacionada, comprovantes aguardando revisao. | Abrir/editar/mover estado manualmente; revisar e confirmar rascunho/baixa. | Hoje/Mensagens/Propostas; retorna ao Hoje ou origem. |
| Administracao | Nao ha pagina de administracao autenticada no sistema auditado; nao incluir link vazio nesta etapa. | A gestao atual de usuarios fica em `/web/users`; nao tratar isso como mecanismo de login. | Fora da navegacao reformulada ate existir controle efetivo de acesso. |

Todos os destinos acima sao intencoes de navegacao; rotas novas e redirecionamentos devem preservar URL legada. Cada pagina deve ter filtros vazios claros, limites/paginacao, feedback de rede/provedor indisponivel e estado sem resultados que nao confunda falha com vazio.

## 7. Limites e fora de escopo

### Evidencia da implementacao local (02/10/2026)

- `APP_ENV_FILE=/tmp/ad-balancas-no-env PYTHONPATH=. .venv/bin/pytest -q`: 442 passaram, 5 foram ignorados pelo suite; o teste usou SQLite temporario e dados/mensagens sinteticos.
- Ruff passou nos modulos novos de sync, agenda e testes novos; `git diff --check` passou.
- Validado em SQLite: criacao aditiva das tabelas sem perda das linhas anteriores e acrescimo das colunas de cobertura sem apagar a projecao antiga.
- Nao foi iniciado Uvicorn nem worker periodico; nao foram consultados Yahoo/Ollama reais; nenhuma mensagem ou banco operacional foi acessado. PostgreSQL, navegacao manual em browser e visual responsivo em dispositivos reais continuam pendentes.

- Sem pagamento, baixa financeira, emissao/envio de nota, criacao/envio de proposta ou envio de e-mail/WhatsApp.
- Sem mudanca de prazo, status, responsavel ou execucao de servico sem confirmacao explicita.
- Sem criacao automatica de chamado, lancamento contabil final ou classificacao como fato confirmado.
- Sem alterar/deletar/mover e-mail ou mensagens; Yahoo continua somente leitura.
- Sem download ou processamento automatico de anexos, links ou midia do WhatsApp.
- Sem publicacao externa antes de autenticacao, autorizacao, CSRF, hardening de sessao, politica de dados e revisao operacional.
- Sem blocos de calendario/duracao antes de obter disponibilidade e estimativas de trabalho confiaveis.
- O Yahoo real so e usado pelo piloto isolado documentado em `piloto-email-tarefas.md`; nunca nos testes automatizados, banco operacional ou instancias 8000/8011.
- Sem implementacao/configuracao de WhatsApp; permanece somente como ideia futura.

### Atualizacao: piloto local e cliente opcional em tarefas (02/10/2026)

Esta atualizacao substitui a evidência anterior desta seção sobre não ter iniciado Yahoo real. A tarefa mantém `client_id` nulo se o nome não estiver cadastrado ou for ambíguo, grava o nome informado em texto livre e sinaliza revisão; a confirmação manual continua obrigatória. A rota curta para pedidos explícitos de criação reduz dependência do Ollama sem ampliar as ferramentas autorizadas.

O piloto 8012 usa SQLite e diretórios em `/tmp`, configuração Yahoo local ignorada pelo Git, início em `activation_at`, IMAP somente leitura e intervalo de 900 segundos. O primeiro e o segundo ciclos reais consultaram Entrada com sucesso e encontraram zero mensagens novas desde a ativação; isso não declara a caixa inteira vazia. Nenhuma tarefa de e-mail real ou lançamento financeiro foi criado. A saída de testes, configuração, porta e restrições está em `piloto-email-tarefas.md`; o resumo de testes automatizados é 481 passed / 10 skipped. O PostgreSQL e o uso conversacional geral do Ollama seguem pendentes de validação.
