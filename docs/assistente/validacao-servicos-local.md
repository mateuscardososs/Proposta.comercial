# Validação local — registro e acompanhamento de serviços

Data: 2026-10-02. Instância restrita ao loopback em `127.0.0.1:8011`.

## Ambiente e isolamento

- Desenvolvimento executado no Mac com Apple Silicon M5.
- Ollama local em `http://127.0.0.1:11434`, modelo `qwen3:4b-instruct-2507-q4_K_M` (Q4_K_M, já instalado). Nenhum modelo foi baixado nesta etapa.
- Banco de teste da instância: `/tmp/ad-balancas-services-8011/app.sqlite3`; documentos e saída também ficam sob `/tmp/ad-balancas-services-8011/`.
- A carga contém três clientes explicitamente sintéticos, um responsável fictício, chamados e tarefas com prefixo `[SINTÉTICO]`.
- O banco anterior de teste em `/tmp/ad-balancas-conversational.xFP65K` foi preservado. O banco operacional não foi usado.
- `.env.yahoo.local` continua fora do Git e não foi lido pelo relatório. Nenhuma consulta à conta Yahoo foi feita para validar serviços; sua integração permanece somente leitura.
- A aplicação antiga da porta 8000 não foi modificada.
- Uma consulta natural real executada pela API da instância retornou o chamado sintético da Alfa Serviços, indicou relatório pendente e reconheceu o evento de inspeção registrado. A solicitação usou uma consulta e uma resposta natural do modelo, sem reparo; não consultou tarefas nem caixa de e-mail.

## Comportamentos cobertos

1. Inspeção cria evento `inspection` e não conclui a execução.
2. Execução iniciada e conclusão explícita são projetadas separadamente do encerramento administrativo.
3. Cliente ambíguo gera pergunta de esclarecimento; não é escolhido um ID por aproximação.
4. Campos administrativos passam por rascunho e confirmação; transições mantêm etapa, estado anterior/novo, observação e ação.
5. Correção de evento confirmado acrescenta evento de correção, preserva o original e recompõe a projeção técnica.
6. Correção do rascunho anterior à confirmação cancela o token antigo e emite uma nova confirmação.
7. Cancelar um rascunho não cria chamado, evento nem tarefa.
8. Lembretes usam o serviço existente do quadro, ficam ligados ao chamado e a confirmação repetida não duplica tarefas.
9. Alegações de estado técnico/administrativo contraditórias à consulta real ou sobre ID não apresentado são rejeitadas.
10. A interface recebe links para abrir chamado e cada tarefa associada.

## Evidência executada

- Suite Python completa: **409 passed, 5 skipped**. Os skips incluem testes opt-in de provedores reais. Os avisos restantes são deprecações do SQLAlchemy/Starlette/FastAPI já existentes.
- JavaScript de chat e voz: **18 passed**, incluindo renderização dos links para chamado e lembretes.
- Integração real do Ollama: executada com `RUN_OLLAMA_LIVE=1` e o modelo local listado acima. O modelo classificou o relato sintético como inspeção; a ação só persistiu após confirmação e o estado final permaneceu `not_started`. Resultado: **1 passed**, duração observada do caso completo **2,56 s** com o modelo aquecido; uma execução inicial mediu **9,17 s**. São observações isoladas, não mediana nem garantia de desempenho.
- Testes SQLite verificam `PRAGMA foreign_keys=ON`, guardas de imutabilidade, `RESTRICT`, correção append-only, replay/idempotência e rollback. As conexões SQLAlchemy usadas pela aplicação e pelo seed recebem a configuração; conexões SQLite abertas diretamente com `sqlite3` fora do SQLAlchemy não são abrangidas pelo listener.
- O PostgreSQL foi declarado na implementação das guardas, mas **não foi executado** contra container/servidor PostgreSQL nesta validação. Validação PostgreSQL e inspeção de plano de migração nesse backend permanecem pendentes.

O tempo de carregamento do modelo não foi separado do tempo do primeiro caso e não foi medido por etapa nesta entrega. Também não houve validação de STT/TTS, microfone no navegador, Windows/Ryzen ou conta de e-mail real.

Durante a consulta HTTP real, a primeira validação detectou que a camada de escopo interpretava a resposta pós-consulta como função indisponível, pois a ferramenta de leitura é removida da allowlist após seu uso. A regra agora aceita a resposta natural quando existe evidência de consulta bem-sucedida no mesmo pedido, mantendo apenas `responder_conversa` permitido na rodada seguinte. O resultado compacto inclui eventos efetivos e estados das cinco etapas; a repetição do teste real passou sem alegar que a inspeção não ocorreu nem que consultou tarefas.

## Iniciar e testar manualmente

Com Ollama já ativo em loopback, a partir da raiz do projeto:

```bash
DATABASE_URL=sqlite:////tmp/ad-balancas-services-8011/app.sqlite3 \
SERVICE_VALIDATION_ALLOW_SYNTHETIC_SEED=1 PYTHONPATH=. \
.venv/bin/python scripts/seed_assistant_service_validation.py
./scripts/run_assistant_8011_yahoo.sh
```

Abra [http://127.0.0.1:8011/web/assistente](http://127.0.0.1:8011/web/assistente). Se a porta já estiver ocupada, confira o PID e encerre somente a instância 8011 conhecida; não toque na 8000. O launcher verifica credenciais localmente, mantém o Yahoo em modo de leitura e não imprime os valores.

Roteiro sugerido:

1. “Fui à Alfa” — deve perguntar qual das empresas Alfa.
2. “Alfa Serviços Sintética; fiz só uma inspeção, sem conserto” — revisar e confirmar; a execução deve continuar não iniciada.
3. “Terminei o reparo na Beta Comércio Sintética” — revisar e confirmar; a conclusão técnica não encerra as etapas administrativas.
4. Consultar o chamado; depois informar que falta o relatório e, em outra ação confirmada, que aguarda o cliente.
5. Solicitar correção do evento de execução para inspeção — confirmar; o histórico anterior permanece e a projeção deixa de mostrar execução concluída.
6. Pedir lembretes de relatório e proposta para um chamado exibido — confirmar; abrir os links e repetir a confirmação para verificar idempotência.
7. Cancelar um rascunho e conferir que nada foi persistido.

Para voz, repetir exatamente os mesmos enunciados usando o microfone; STT apenas encaminha a transcrição ao mesmo endpoint textual, sem caminho paralelo de gravação. A qualidade por microfone e sintetizador depende de teste humano.

## Extensão do ciclo de acompanhamento — 2026-10-06

Esta extensão reutiliza `ServiceCall`, `ServiceEvent`, `ServiceTaskLink`, `Task`, `AssistantAction`, os adaptadores Gemini/Ollama e as páginas existentes. Os campos de equipamento, problema, análise e trabalho executado são validados contra o relato e ficam como narrativa rotulada no evento append-only; não foi adicionada tabela/coluna e não há migração de banco.

Uma data de retorno explícita aparece no rascunho como data absoluta. A mesma confirmação grava o evento e cria, via `board_service`, uma tarefa de retorno ligada ao evento. A consulta de retornos usa somente essas ligações explícitas; o resultado de verificação exige que a tarefa tenha sido apresentada na conversa e gera outro evento. A tarefa só muda para concluída após confirmação do resultado “resolvido”.

Na validação inicial, o relatório técnico existia apenas na tela de Serviços. A entrega de 2026-10-07 conecta o Assistente ao mesmo gerador e às mesmas rotas, sem duplicar geração nem alterar o fluxo de propostas.

### Evidência executada nesta extensão

- Testes Python com SQLite temporário e dados sintéticos: **609 passed, 11 skipped** na suíte completa; skips são testes opt-in. Cobrem descrição estruturada, inspeção sem conclusão, execução, ambiguidade, data de retorno, consulta sem escrita, confirmação do resultado, cancelamento/idempotência e paridade dos contratos de ferramenta.
- Testes JavaScript do projeto: **34 passed**; a resposta de conclusão renderiza o link para o fluxo existente de proposta.
- `compileall` e `git diff --check` executados após a implementação.
- Não houve mudança de schema; portanto, não foi aplicada nem necessária migração PostgreSQL. A instância principal conectou ao PostgreSQL `propostas_db` existente, saudável em loopback.
- 8013 foi iniciada no mesmo endereço (`127.0.0.1:8013`), PID observado **73503**. Health check, Assistente, Serviços, Propostas e endpoints de status de voz/capacidades retornaram HTTP 200. Voz local informou STT/TTS disponíveis. A porta 8000 não foi tocada.
- O provedor configurado na execução é Gemini, modelo `gemini-3.1-flash-lite`; a chave foi verificada apenas como presente e não foi impressa. Não foi feita chamada do Assistente contra registros operacionais durante esta validação. O smoke real isolado com texto sintético terminou com falha de conexão à API (exit code 1); não é contado como validação bem-sucedida do provedor e não houve fallback para Ollama.
- O worker Yahoo foi temporariamente pausado no banco antes da inicialização para que a tentativa automática inicial retornasse “paused” sem consultar a caixa; seu estado anterior foi restaurado, o marco `2026-10-02T20:43:34.394255` e o intervalo de 900 segundos foram preservados. Não houve sincronização manual nem inspeção de conteúdo real.
- Validação manual da conversa por voz e navegação em navegador não foi feita; os testes de voz são automatizados e o status da API foi verificado por HTTP.

## Relatórios técnicos DOCX/PDF — 2026-10-06

- O modelo `doc_templates/relatorio_tecnico_template.docx` usa os dados de cliente cadastrados e os campos explícitos dos eventos efetivos do chamado. Correções append-only entram na prévia como informação vigente; o evento original continua no histórico.
- `/web/services/{id}/relatorio/previa` é somente leitura. Campos ausentes aparecem marcados e editáveis, e a confirmação explícita é necessária antes de gerar os arquivos. Ajustes afetam apenas o snapshot do relatório, não cadastro/histórico técnico.
- A confirmação grava uma linha imutável ligada ao chamado e à ação confirmada, com IDs/fingerprint dos eventos de origem; não cria nem altera eventos técnicos. A etapa administrativa “relatório” é atualizada por trilha própria sem evento técnico associado; as referências são opcionais no schema para representar corretamente essa separação. O identificador idempotente permite reconciliar retries e manter versões anteriores.
- DOCX e PDF são escritos em diretório exclusivo por chamado. A conversão usa LibreOffice do host quando disponível; no launcher da 8013 nativa, caso contrário, foi configurada a imagem local existente como conversor efêmero com rede desabilitada, filesystem de container somente leitura e apenas a pasta temporária do documento montada para entrada/saída. Nenhum serviço externo participa.
- Testes automatizados isolados: serviço, rotas, histórico e conversão com mock — **17 passed** no grupo focado. Os dois testes opt-in criaram e converteram um relatório inteiramente sintético com a imagem local — **2 passed**. Isso valida a geração e conversão com componentes reais locais, não uma caixa de e-mail nem a qualidade técnica de um relatório real.
- Suíte Python completa após a mudança: **623 passed, 13 skipped**. `ruff check` nos arquivos alterados, `compileall` e `git diff --check` passaram; os avisos da suíte são depreciações existentes de FastAPI/Starlette/SQLAlchemy.
- Schema: `service_technical_reports` é uma tabela aditiva criada por `Base.metadata.create_all`; as três chaves estrangeiras usam `ON DELETE RESTRICT`. PostgreSQL 16 descartável em loopback aceitou o schema e as constraints; nenhum dado do banco padrão foi usado nessa prova.
- O conteúdo é dado operacional e fica no PDF/DOCX e no snapshot estruturado, não em logs de conversão. Não houve consulta ou sincronização Yahoo.
- O PostgreSQL `propostas_db` foi copiado antes da escrita para `/tmp/adbalancas-8013-report-backup.0wG4I0/propostas_db.dump` (141307 bytes, permissão `0600`, verificado por `pg_restore --list`, SHA-256 `9f9850f2365b1ab0457d060a5222a937d5e62d83aaf070fd5c8e3e8014980b0a`). O banco temporário PostgreSQL 16 foi removido após validar criação repetida, FKs `RESTRICT`, unique constraints e gatilho de imutabilidade.
- A única tabela ausente no schema principal era `service_technical_reports`; nenhuma coluna de compatibilidade estava pendente. A aplicação criou a tabela de forma aditiva no startup. Nenhum chamado/relatório foi inserido ou alterado na validação da 8013.
- A 8013 foi reiniciada no mesmo loopback; PID observado **19957**. `/healthz`, Assistente, Serviços, Quadro e Propostas retornaram HTTP 200. O endpoint de prévia com um ID sintético inexistente retornou 404, como esperado. O PostgreSQL permaneceu saudável em `127.0.0.1:5433`.
- Antes do restart, a sincronização Yahoo foi pausada somente no estado local e restaurada ao valor anterior depois da checagem. O marco `2026-10-02T20:43:34.394255` e `last_attempt_at=2026-10-06T17:53:37.638022` foram preservados. A startup encontrou a pausa antes da busca IMAP; não houve consulta/sincronização manual ou automática nem mudança nas mensagens.
- O launcher detectou a imagem local aprovada para conversão porque o host não possui `soffice`. A conversão sintética real foi exercitada pelo container sem rede; somente um DOCX sintético foi montado. Não foi solicitada geração num chamado operacional na 8013.
- A interface visual do DOCX foi inspecionada com conteúdo sintético; a página de prévia e o fluxo completo de confirmação foram cobertos pelo TestClient com SQLite isolado. Não fiz navegação manual no navegador da 8013 porque a base principal não contém chamado sintético e não inseri dados artificiais nela. Esse teste visual integrado ao navegador permanece pendente.

## Integração com o Assistente — 2026-10-07

- `preparar_relatorio_tecnico` é um comando estruturado disponível ao Gemini e ao Ollama. A intenção clara de gerar relatório restringe a rodada à ferramenta de relatório; o backend filtra cliente/referência no banco sem diferenciar acentos, prioriza um ID explícito e trata IDs fora de faixa como não encontrados. Carrega no máximo 11 candidatos para detectar excesso, mostra até 10 chamados recentes e pede refinamento quando necessário.
- Uma chamada única cria uma ação pendente com snapshot da prévia, fingerprint e chave idempotente. Os campos são exibidos no histórico do chat, incluindo ausências. A edição visual usa o endpoint da ação e correções por conversa usam o contrato `corrigir_previa_relatorio_tecnico`; ambos rotacionam a confirmação.
- Após confirmação, `AssistantService` chama `service_report_service.generate_report`, o gerador já usado pela tela. O DOCX/PDF são disponibilizados pelos endpoints existentes como links no chat. Repetir a confirmação reconcilia o mesmo relatório.
- A trilha administrativa pode completar a etapa `report` sem fabricar um evento do chamado. `service_workflow_transitions.service_event_id` e `service_technical_reports.document_event_id` aceitam `NULL`; a migração é idempotente e preserva os vínculos/linhas anteriores. SQLite usa reconstrução das duas tabelas com cópia integral e verificação de FKs; PostgreSQL usa somente `DROP NOT NULL` nas duas colunas.
- Os testes automatizados sintéticos cobrem resolução ambígua e continuação, campos faltantes, correção/token renovado, cancelamento sem arquivo, confirmação, retry, uso pelo caminho `source=voice`, edição visual via endpoint e links DOCX/PDF. **Não use estes resultados como teste manual de microfone ou navegador com fala real.**
- Validação final em 2026-10-07: suíte Python completa **638 passed, 13 skipped**; testes JavaScript **36 passed** em três arquivos executados separadamente; PostgreSQL 16 temporário confirmou aplicação repetida da migração e nullable nas duas referências. `compileall`, `node --check`, lint selecionado (`F,E4,E7,E9,I`) e `git diff --check` passaram. `ruff check` sem seleção continua apontando regras legadas de estilo/complexidade em arquivos do projeto.
- Backup novo do PostgreSQL padrão antes do restart/migração: `/tmp/adbalancas-report-chat-backup.ZTB9O1/propostas_db.dump`, 148923 bytes, formato custom validado por `pg_restore --list`, SHA-256 `b0a8d6d5ecb9ab34bb79791bc345ff67e59fb42a1ba5a86eac072a52d7dc90ff`.
- A 8013 foi reiniciada no mesmo checkout/loopback e iniciou com provedor Gemini. Health check, Hoje (`/`), Assistente, Serviços, Quadro, Propostas e Mensagens retornaram HTTP 200. A migração de compatibilidade foi aplicada; as referências de evento estão nullable. Contagens de clientes, tarefas, propostas, lançamentos, mensagens e histórico de serviço permaneceram iguais ao pré-restart. O container PostgreSQL existente permaneceu saudável.
- O marco Yahoo `2026-10-02T20:43:34.394255` foi preservado. Nenhuma sincronização manual foi solicitada; o worker existente executou o ciclo automático de startup da configuração já ativa. A última execução passou a `2026-10-07T00:52:45.638574`, com contagem 12; a caixa isolada continuou com 32 registros e as tarefas permaneceram em 24. Não registrei nem relatei conteúdo de mensagens.
- A tela foi verificada por HTTP, não por navegador interativo. Não foi criado chamado sintético no PostgreSQL principal e não foi enviado pedido ao Gemini via conversa operacional. Portanto a experiência visual interativa, confirmação/download no navegador e microfone/voz na 8013 continuam pendentes de validação humana; os fluxos de texto e voz estão cobertos por testes automatizados isolados.
