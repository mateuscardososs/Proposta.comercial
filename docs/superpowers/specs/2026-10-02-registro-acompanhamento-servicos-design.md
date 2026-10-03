# Registro e acompanhamento de servicos — especificacao

**Data:** 2026-10-02
**Estado:** desenho aprovado; implementacao ainda nao iniciada

## Objetivo

Adicionar ao sistema da AD Balancas um registro operacional por chamado, com historico de eventos e acompanhamento independente da execucao tecnica e das etapas administrativas. O mesmo fluxo sera usado por texto e por voz, preservando confirmacao, historico, idempotencia e as restricoes das integracoes existentes.

Esta primeira versao registra e consulta fatos. Ela nao gera relatorios ou propostas, nao emite nota fiscal, nao altera contas, nao envia mensagens e nao modifica e-mails.

## Auditoria do fluxo atual

O sistema atual possui clientes, usuarios, propostas, tarefas do quadro, lancamentos financeiros e o historico do assistente. Nao existe entidade propria para chamado, visita, inspecao, execucao ou relatorio.

O quadro representa trabalho com um unico `Task.status`. Esse estado agregado nao consegue expressar simultaneamente que a execucao terminou, o relatorio esta pendente, a proposta aguarda aprovacao e o recebimento ainda nao ocorreu. `Proposal` e `Lancamento` tambem nao devem assumir esse papel: ambos possuem fluxos proprios que ficarao fora desta mudanca.

O fluxo conversacional existente oferece componentes que serao reutilizados:

- texto e voz chegam ao mesmo `AssistantService.handle_message`;
- `AssistantAction` guarda o rascunho, o token de confirmacao, o estado e o resultado;
- `AssistantRequest` reconcilia repeticoes e requisicoes interrompidas;
- clientes e responsaveis sao resolvidos pelos cadastros reais, com pergunta em caso de ambiguidade;
- `board_service.create_task` com `commit=False` permite criar lembretes dentro de uma transacao maior;
- a interface do assistente ja apresenta historico, confirmacao, sucesso e erro;
- o registro de capacidades e a validacao de evidencia impedem que o modelo alegue operacoes indisponiveis;
- a integracao Yahoo e somente leitura e continuara independente deste modulo.

O projeto nao usa Alembic. A inicializacao executa `Base.metadata.create_all` e a compatibilidade de alteracoes antigas e tratada em `app/db.py`. Como esta entrega usa somente novas tabelas, a migracao sera aditiva por `create_all`, acompanhada por teste contra um esquema anterior.

## Modelo de dominio

### Chamado

`ServiceCall` e o agregado principal. Cada chamado independente produz um registro independente, mesmo quando pertence ao mesmo cliente.

Campos previstos:

- identificador;
- cliente obrigatorio;
- resumo do chamado;
- data de abertura;
- `execution_status`: `not_started`, `in_progress` ou `completed`;
- `administrative_status`: `open` ou `closed`;
- instante da conclusao tecnica, quando houver;
- instante do encerramento administrativo, quando houver;
- conversa que originou o registro, quando aplicavel;
- datas de criacao e atualizacao.

`execution_status=completed` significa apenas que a execucao tecnica terminou. Nao significa que relatorio, proposta, nota fiscal ou recebimento foram resolvidos.

`administrative_status=closed` so sera possivel quando a execucao estiver concluida e todas as etapas administrativas estiverem explicitamente `completed` ou `not_applicable`. Estados `unknown`, `pending` ou `waiting_customer` impedem o encerramento.

### Eventos

`ServiceEvent` forma o historico append-only do chamado. Tipos iniciais:

- `call_received`;
- `visit_started`;
- `inspection`;
- `execution_started`;
- `execution_completed`;
- `note`;
- `correction`.

Cada evento possui data, descricao, chamado, origem conversacional e a `AssistantAction` confirmada que autorizou a gravacao. Existe no maximo um `ServiceEvent` por acao confirmada; `assistant_action_id` e unico. Quando uma unica acao altera varias etapas administrativas, ela continua produzindo um evento e produz uma transicao estruturada por etapa, todas ligadas ao mesmo evento e a mesma acao.

Quando for uma correcao, o evento referencia o fato corrigido. A correcao guarda de forma estruturada os campos substitutos informados — tipo, data e/ou descricao — alem do motivo textual. O evento original nunca e apagado ou sobrescrito. A apresentacao do historico mostra tanto o fato original quanto a cadeia de correcoes e identifica qual informacao prevalece.

Uma inspecao nao altera o estado da execucao para `completed`. Somente uma declaracao explicita de que a execucao terminou, confirmada pelo usuario, pode criar `execution_completed` e concluir tecnicamente o chamado.

### Etapas administrativas

`ServiceWorkflowStep` guarda uma linha por chamado e tipo de etapa:

- `report`;
- `proposal`;
- `proposal_sent`;
- `invoice`;
- `receipt`.

Cada etapa tem um estado independente:

- `unknown` — aplicabilidade ou situacao ainda nao informada;
- `not_applicable` — explicitamente dispensada;
- `pending` — aplicavel e ainda nao concluida;
- `waiting_customer` — depende de aprovacao ou retorno do cliente;
- `completed` — concluida segundo informacao confirmada pelo usuario.

Nao havera uma ordem obrigatoria entre as etapas. A proposta pode ocorrer antes ou depois da execucao e pode ser dispensada. Alterar o estado de uma etapa registra tambem um evento auditavel; nao cria ou modifica `Proposal`, documentos, nota fiscal ou `Lancamento`.

`ServiceWorkflowTransition` registra cada mudanca de etapa de forma append-only, com:

- chamado e tipo da etapa;
- estado anterior;
- estado novo;
- observacao confirmada, que pode ser vazia mas nunca nula;
- `ServiceEvent` que agrupou a acao;
- `AssistantAction` confirmada que autorizou a mudanca;
- data de criacao.

Uma acao pode gerar zero, uma ou varias transicoes. A combinacao `(assistant_action_id, step_type)` e unica: repetir a mesma confirmacao reconcilia as linhas existentes e nao duplica transicoes. O backend le o estado anterior da projecao atual, rejeita mudanca sem efeito (`previous_status == new_status`), grava todas as transicoes e atualiza `ServiceWorkflowStep` na mesma transacao. Nao ha uma maquina de estados com ordem fixa: qualquer mudanca para um estado diferente e permitida quando estiver explicitamente no rascunho confirmado. Assim, sequencias reais como `unknown -> pending -> waiting_customer` ficam integralmente auditaveis.

A integridade entre os registros nao depende apenas do servico: uma FK composta da transicao para `(service_event_id, service_call_id, assistant_action_id)` do evento garante que chamado, evento e acao sejam os mesmos, e outra FK composta para `(service_call_id, step_type)` garante que a transicao pertence a etapa projetada correspondente.

`ServiceWorkflowStep` e a projecao atual de cada etapa, nao o historico. Seu valor deve coincidir com a ultima `ServiceWorkflowTransition` efetiva daquela etapa.

Uma retificacao administrativa tambem e append-only: ela cria uma nova transicao a partir do estado atualmente projetado, com observacao que identifica a retificacao, sem editar a transicao anterior. Como as transicoes nao sao anuladas, a projecao administrativa de cada etapa e sempre o `new_status` da transicao mais recente daquela etapa, ordenada por criacao e ID. A correcao de um fato operacional nao desfaz silenciosamente transicoes administrativas gravadas pela mesma acao; qualquer retificacao dessas etapas deve estar declarada no novo rascunho confirmado e gerar suas proprias transicoes.

### Lembretes do quadro

`ServiceTaskLink` associa um chamado e, opcionalmente, uma etapa ou evento a uma tarefa real. Lembretes continuam sendo `Task` e serao criados exclusivamente por `board_service`.

Um lembrete nunca sera criado automaticamente. A oferta do assistente produz um segundo rascunho, com titulo, prazo, responsavel e etapa vinculada, que exige confirmacao independente. Uma confirmacao repetida devolve o resultado existente sem criar outra tarefa.

## Fluxo conversacional

### Registro inicial ou novo evento

1. O usuario relata um chamado, visita, inspecao, inicio ou conclusao de execucao.
2. O provedor local produz apenas um comando estruturado permitido.
3. O backend resolve o cliente e procura chamados compativeis.
4. O backend pergunta quando o cliente e ambiguo, quando ha mais de um chamado aberto compativel ou quando a conclusao tecnica nao foi afirmada com seguranca.
5. O backend prepara um rascunho, sem gravar o dominio.
6. A resposta apresenta cliente, chamado novo ou existente, tipo do evento, data absoluta, descricao, efeito tecnico, etapas administrativas informadas e campos desconhecidos.
7. A confirmacao valida persiste chamado, um evento para a acao, zero ou mais transicoes administrativas, as projecoes atuais e o vinculo com a acao numa unica transacao.
8. A resposta de sucesso informa o que foi registrado, o que esta pendente e o que depende do cliente.

Quando nenhuma data for falada, o backend propoe a data corrente no fuso `America/Recife`, mostra a data absoluta no rascunho e permite correcao antes da confirmacao. A data so e aceita como fato quando o usuario confirma o rascunho.

### Associacao a chamado existente

- `novo chamado` sempre inicia outro registro;
- uma referencia explicita a um chamado ou a um item mostrado na conversa tem prioridade;
- um unico chamado aberto compativel pode ser sugerido, mas a associacao aparece na confirmacao;
- mais de um chamado compativel exige uma pergunta curta;
- `esse servico`, `o segundo` e expressoes equivalentes usam apenas referencias apresentadas no historico da conversa;
- chamado concluido nao recebe novo evento operacional sem o usuario indicar reabertura ou correcao.

### Correcao

Antes da confirmacao, uma correcao atualiza o rascunho e invalida o token anterior. Depois da persistencia, uma correcao exige nova confirmacao e cria um `ServiceEvent` do tipo `correction`, com `supersedes_event_id` apontando para o fato efetivo corrigido. O evento anterior permanece consultavel.

As correcoes formam cadeias lineares. Uma correcao so pode apontar para o ultimo evento efetivo da cadeia, do mesmo chamado, e `supersedes_event_id` e unico para impedir ramificacoes. O tipo corrigido deve ser um tipo operacional, nunca `correction`. Uma correcao posterior pode apontar para a correcao anterior.

`ServiceCall.execution_status` e `technically_completed_at` sao projecoes, nao fontes historicas. Depois de qualquer evento ou correcao, o servico recompõe o estado a partir do log:

1. agrupa cada evento original com sua cadeia de correcoes;
2. usa a folha da cadeia e seus campos corrigidos como representacao efetiva do fato;
3. ordena os fatos efetivos por data efetiva e, em empate, pelo ID da folha;
4. considera apenas `execution_started` e `execution_completed` para a projecao tecnica;
5. sem fato efetivo de execucao, projeta `not_started`; se o ultimo fato de execucao for `execution_started`, projeta `in_progress`; se for `execution_completed`, projeta `completed` e sua data efetiva;
6. limpa `technically_completed_at` quando a projecao deixa de ser `completed`;
7. recalcula o encerramento administrativo usando a nova projecao tecnica e os estados atuais das etapas.

Portanto, corrigir `execution_completed` para `inspection` remove aquele fato da sequencia efetiva de execucao. Se existir um `execution_started` anterior, o estado atual volta para `in_progress`; se nao existir, volta para `not_started`. O evento original concluido e a correcao continuam visiveis no historico.

### Acompanhamento

Consultas podem filtrar por cliente, conclusao tecnica, situacao administrativa ou proxima pendencia. A resposta usa dados reais e distingue:

- execucao ainda nao iniciada;
- execucao em andamento;
- execucao tecnicamente concluida;
- etapas administrativas desconhecidas, pendentes, aguardando cliente, concluidas ou dispensadas;
- chamado administrativamente encerrado.

Nao ha notificacao autonoma nesta versao. Para um chamado em andamento, o assistente oferece criar um lembrete de acompanhamento no quadro. Consultas futuras tambem destacam chamados em andamento e etapas pendentes.

### Confirmacao e cancelamento

`confirmar_acao` e `cancelar_acao` continuam sendo os unicos controles de uma acao pendente. O contexto estruturado passa a aceitar rascunhos de tarefa, registro de servico, correcao de servico e lote de lembretes. Uma nova correcao invalida confirmacoes antigas.

Cancelamento encerra o rascunho sem criar chamado, evento, etapa ou tarefa.

## Ferramentas permitidas ao modelo

Novas ferramentas estruturadas:

- `consultar_servicos` — somente leitura;
- `registrar_evento_servico` — prepara um rascunho para chamado novo ou existente;
- `corrigir_registro_servico` — corrige rascunho pendente ou prepara evento de correcao;
- `criar_lembretes_servico` — prepara tarefas vinculadas, sem persisti-las antes da confirmacao.

O modelo nao recebe SQL, shell, acesso a arquivos nem ferramentas genericas. IDs retornados pelo modelo nunca sao aceitos sem validacao no banco e no contexto da conversa.

As capacidades `service_read` e `service_write` serao marcadas como disponiveis. Criacao de proposta/documento, emissao fiscal, escrita financeira e escrita de e-mail permanecem indisponiveis. A validacao de evidencia so permite afirmar consulta ou registro de servico quando a ferramenta correspondente produziu evidencia na solicitacao ou quando a resposta identifica claramente um resultado historico.

## Servicos e limites de arquitetura

`service_record_service` concentrara regras de dominio, consultas e persistencia transacional. O controlador conversacional apenas resolvera o comando, preparara a confirmacao e formatara o resultado. Rotas HTTP e paginas nao duplicarao regras de estado.

A primeira versao inclui paginas simples, no visual existente:

- lista de chamados, mostrando cliente, estado tecnico, estado administrativo e proxima pendencia;
- detalhe do chamado, com etapas, historico cronologico e links para lembretes do quadro.

Essas paginas serao somente leitura. Toda alteracao desta entrega passara pela conversa e pela confirmacao existente.

## Erros, recuperacao e idempotencia

- cliente inexistente ou ambiguo: pergunta curta, sem gravacao;
- chamado ambiguo: lista curta de opcoes, sem selecionar silenciosamente;
- ausencia de descricao ou tipo de evento confiavel: pergunta pelo dado realmente necessario;
- declaracao duvidosa de conclusao: manter estado atual e perguntar se a execucao terminou;
- token antigo depois de uma correcao: rejeitar como conflito;
- confirmacao repetida: devolver o mesmo chamado, evento ou tarefas;
- repeticao de uma acao com varias etapas: reconciliar o evento e todas as transicoes por `assistant_action_id`, sem aplicar a projecao novamente;
- repeticao do mesmo `request_id`: reconciliar pela resposta persistida;
- timeout apos `commit`: localizar a acao e o resultado persistido antes de nova tentativa;
- falha antes do `commit`: rollback integral;
- Ollama indisponivel: manter dados existentes intactos e exibir erro claro;
- afirmacao sem evidencia: rejeitar a resposta do modelo e usar tratamento seguro;
- etapa invalida para encerramento: manter chamado aberto e informar quais estados bloqueiam o encerramento.

Nenhum log tecnico guardara raciocinio interno do modelo, credenciais Yahoo ou conteudo integral de e-mail.

## Imutabilidade e restricoes de banco

`ServiceEvent` e `ServiceWorkflowTransition` sao registros imutaveis. As relacoes ORM nao usam `delete-orphan` nem cascata de exclusao para essas entidades. As FKs do historico para chamado, evento anterior, etapa e acao confirmada usam `ON DELETE RESTRICT`/`NO ACTION`; apagar um chamado, uma etapa projetada ou uma acao que possua historico deve falhar. Em SQLite, toda conexao deve habilitar `PRAGMA foreign_keys=ON`; sem essa configuracao, o contrato de restricao nao e considerado validado.

Para impedir exclusao ou alteracao direta das linhas historicas, a inicializacao instala guardas idempotentes no banco:

- SQLite: triggers `BEFORE UPDATE` e `BEFORE DELETE` com `RAISE(ABORT)` em `service_events` e `service_workflow_transitions`;
- PostgreSQL: funcao de trigger e triggers `BEFORE UPDATE OR DELETE` equivalentes nas duas tabelas.

O servico de dominio tambem rejeita objetos historicos presentes em `Session.deleted` ou com atributos modificados antes do flush. Essa defesa de aplicacao melhora a mensagem de erro; os triggers continuam sendo a garantia final para SQL direto. Correcoes e novas informacoes sempre criam linhas, nunca executam `UPDATE` ou `DELETE` no historico.

## Migracao e compatibilidade

A entrega adicionara somente as tabelas `service_calls`, `service_events`, `service_workflow_steps`, `service_workflow_transitions` e `service_task_links`, com indices, FKs restritivas, restricoes de unicidade e os triggers de imutabilidade. Nao serao alteradas as tabelas `tasks`, `proposals`, `lancamentos` ou as tabelas atuais do assistente.

`Base.metadata.create_all` criara as novas tabelas em bancos existentes. Um teste construira explicitamente o esquema anterior, gravara dados sentinela, executara a criacao aditiva e verificara que os dados antigos permanecem intactos.

Durante desenvolvimento e validacao, somente um banco SQLite isolado sera usado. O banco operacional nao sera iniciado com o novo codigo nesta etapa.

## Estrategia de testes

### Dominio

- inspecao preserva `execution_status=not_started`;
- execucao iniciada muda para `in_progress`;
- somente `execution_completed` explicitamente confirmado muda para `completed`;
- conclusao tecnica nao encerra administrativamente;
- proposta pode ser `pending`, `waiting_customer`, `completed` ou `not_applicable`, independentemente da ordem da execucao;
- uma acao que muda relatorio e proposta cria um evento e duas transicoes ligadas a mesma `AssistantAction`;
- a sequencia `unknown -> pending -> waiting_customer` preserva os dois estados anteriores nas transicoes e deixa a projecao em `waiting_customer`;
- relatorio pendente permanece visivel depois da conclusao tecnica;
- encerramento administrativo falha com etapas desconhecidas ou pendentes;
- correcao cria novo evento, preserva o anterior e recompõe a projecao tecnica;
- corrigir conclusao para inspecao resulta em `in_progress` quando ha inicio anterior e em `not_started` quando nao ha;
- `UPDATE` ou `DELETE` direto de evento/transicao falha no banco e apagar o chamado, a etapa projetada ou a acao confirmada nao remove o historico por cascata;
- lembretes sao vinculados ao chamado sem duplicacao.

### Conversa e persistencia

- cliente com nome ambiguo gera esclarecimento;
- varios chamados abertos geram esclarecimento;
- inspecao e execucao posterior entram no mesmo chamado como eventos distintos;
- chamado independente cria outro registro;
- rascunho mostra data absoluta e estados resultantes;
- cancelamento nao grava;
- confirmacao repetida e retry nao duplicam dados;
- criacao confirmada de lembretes usa tarefas reais;
- correcao invalida token anterior;
- respostas so alegam consulta ou gravacao com evidencia real;
- voz e texto chegam ao mesmo comando conversacional.

### Integracao e regressao

- esquema aditivo preserva clientes, tarefas, propostas e lancamentos existentes;
- paginas de lista e detalhe exibem estados e historico;
- links do assistente abrem chamado e tarefas;
- testes existentes de quadro, propostas, financeiro, e-mail e voz continuam passando;
- caixa Yahoo permanece somente leitura;
- Ollama real e validado apenas com clientes e chamados sinteticos;
- Whisper e Piper reais percorrem o mesmo fluxo em banco isolado;
- nenhum processo ou banco da porta 8000 e alterado.

## Criterios de aceitacao

1. “Fui a empresa Alfa, mas so fiz uma inspecao” produz rascunho de inspecao e, apos confirmacao, nao conclui a execucao.
2. Uma execucao posterior pode ser adicionada ao mesmo chamado como outro evento.
3. “Terminei o conserto” so conclui tecnicamente depois de resolver cliente/chamado e receber confirmacao explicita.
4. Conclusao tecnica pode coexistir com relatorio, proposta, nota ou recebimento pendentes.
5. Proposta pode ser necessaria, dispensada ou continuar desconhecida sem impor ordem fixa.
6. Cliente ou chamado ambiguo nunca e escolhido silenciosamente.
7. Correcao persistida nao apaga nem altera o evento original.
8. A correcao recompõe `execution_status`, `technically_completed_at` e o encerramento administrativo a partir dos fatos efetivos.
9. Cada mudanca administrativa registra etapa, estado anterior, estado novo, observacao, evento e acao confirmada; uma acao com varias etapas continua tendo um unico evento.
10. Eventos e transicoes nao podem ser atualizados ou excluidos por ORM, cascata ou SQL direto.
11. Cancelamento nao grava dados e confirmacao repetida nao duplica registros.
12. Lembretes so sao criados depois de confirmacao e aparecem vinculados no quadro e no chamado.
13. Consultas usam dados reais e respostas sem evidencia de execucao sao bloqueadas.
14. O fluxo funciona por texto e pelo pipeline de voz existente.
15. A instancia 8011 pode executar com banco e documentos sinteticos separados, mantendo Yahoo configurado e a porta 8000 intacta.

## Fora do escopo

- gerar ou enviar relatorios e propostas;
- emitir nota fiscal;
- criar ou alterar contas a pagar ou receber;
- enviar, excluir, mover ou marcar e-mail;
- baixar anexos;
- excluir chamados ou eventos;
- notificacoes autonomas em segundo plano;
- deploy, push ou migracao do banco operacional;
- microfone ou sintetizador novos — serao reutilizados os componentes atuais.
