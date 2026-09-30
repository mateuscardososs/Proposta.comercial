# Assistente operacional local — arquitetura e plano de implementacao

> **Status:** texto e opcao 1 de voz local implementados na branch local `docs/assistente-local-plano` em 2026-09-30. O desenho detalhado da voz esta em `docs/superpowers/specs/2026-09-30-assistente-voz-local-design.md` e a evidencia em `docs/assistente/validacao-voz-local.md`.

**Objetivo:** criar, primeiro, uma conversa por texto com IA local capaz de consultar prioridades e criar tarefas reais no quadro; depois reutilizar o mesmo nucleo para entrada e saida por voz.

**Arquitetura proposta:** o modelo interpreta linguagem natural e devolve um comando tipado, mas nao acessa o banco nem executa regras de negocio. Um servico da aplicacao valida o comando, consulta ou altera tarefas usando SQLAlchemy e exige confirmacao para gravacoes. O interpretador fica atras de uma interface substituivel, com Ollama como primeiro adaptador e possibilidade de API futura.

**Stack atual e prevista:** Python, FastAPI, Pydantic, SQLAlchemy, Jinja2, PostgreSQL/SQLite, Docker Compose, Ollama via API HTTP local e testes com pytest.

## 1. Escopo e restricoes

Decisoes mantidas neste plano:

- comecar sem API paga e sem dependencia de GPU dedicada;
- usar Ollama como primeiro candidato de interpretacao;
- entregar texto antes de transcricao e sintese de voz;
- preservar FastAPI, Jinja2, banco, paginas, servicos e identidade visual existentes;
- nao reescrever o frontend nem migrar de framework;
- nao implementar e-mail, emissao fiscal ou acesso externo nesta etapa;
- nao permitir que o modelo escreva SQL, invoque rotas arbitrarias ou decida sozinho uma mutacao;
- nao tratar servico executado como sinonimo de documentacao concluida, faturamento emitido ou pagamento recebido;
- manter o fluxo de Word: o assistente deve, no futuro, apontar ou receber documentos, nao substituir a preferencia do usuario por edita-los no Word.

Esta analise nao abriu `.env`, nao iniciou os servicos com o banco real, nao alterou `propostas.db`, volumes Docker, documentos ou dados operacionais.

## 2. Estado verificado do repositorio

### Git e instrucoes

- Nao existe `AGENTS.md` no repositorio nem nos diretorios ancestrais aplicaveis pesquisados.
- O repositorio real fica em `/Users/mateuscardoso/dev/pai/Proposta.comercial`.
- O checkout estava limpo em `main`, no commit `0baa95c`, alinhado a `origin/main` no momento da inspecao.
- Foi criada apenas a branch local `docs/assistente-local-plano`. Nao houve push nem commit.

### Verificacoes executadas em 2026-09-30

- Ambiente: macOS `arm64`, Apple M5, 16 GB de memoria; Python do sistema `3.14.5`.
- Docker `29.4.3` e Docker Compose `v5.1.3` estao disponiveis.
- `docker compose ... config --quiet`, com arquivo de ambiente vazio e sem subir containers, validou o Compose.
- A suite foi executada fora da raiz do projeto, com SQLite e diretorios temporarios: **104 testes passaram, 1 foi ignorado**.
- A aplicacao foi iniciada fora da raiz do projeto com banco SQLite e diretorios temporarios; `GET /healthz` respondeu `200` com `{"status":"ok"}`.
- O Ollama nao esta instalado no Mac atual. Nenhum modelo, prompt, latencia ou qualidade de interpretacao foi testado.
- O boot e os testes produziram avisos de deprecacao do `FastAPI.on_event`, de `datetime.utcnow`, da assinatura antiga de `TemplateResponse` e do Python 3.14. Eles nao impediram a execucao, mas devem ser tratados separadamente e nao misturados ao MVP.

## 3. Arquitetura atual identificada no codigo

### Aplicacao e interface

- `app/main.py` cria uma unica aplicacao FastAPI, registra os routers e configura Jinja2 e o mount estatico de `/output`.
- As paginas HTML sao renderizadas no servidor. O design system esta concentrado principalmente em `app/templates_web/base.html`; o quadro reutiliza JavaScript proprio em `_kanban_drag.html`.
- Os routers cobrem paginas gerais, clientes, usuarios, propostas, arquivos de proposta, importacao, quadro e financeiro.
- O dashboard em `/` agrega financeiro, tarefas e propostas por meio de `dashboard_service`.

### Dados e persistencia

- SQLAlchemy 2.0 usa `SessionLocal` e injecao `get_db`.
- O padrao local, quando nao ha configuracao externa, e SQLite em `propostas.db`.
- O Docker Compose usa PostgreSQL 16 e mantem o banco em volume nomeado.
- O startup chama `Base.metadata.create_all()` e uma compatibilidade manual limitada para colunas de proposta; nao ha Alembic.
- Os principais modelos sao `Client`, `User`, `Proposal`, `ProposalItem`, `ProposalScheduleItem`, `Task` e `Lancamento`.

### Tarefas e prioridades ja existentes

- `Task` ja contem titulo, descricao, status, prazo, ordem e vinculos opcionais com cliente, proposta e responsavel.
- O quadro possui cinco estados:
  - `a_fazer`;
  - `em_andamento`;
  - `servico_feito_falta_nota_pedido`;
  - `aguardando_cliente`;
  - `concluido`.
- `board_service` ja lista, cria, edita, exclui e move tarefas.
- A criacao web ja usa `TaskCreate`; a movimentacao usa `TaskMove` por `POST /api/tasks/{id}/move`.
- O dashboard ja calcula tarefas atrasadas e contagens de `a_fazer` e `em_andamento`.

### Documentos e financeiro

- Propostas possuem geracao de DOCX com `docxtpl`, conversao PDF com LibreOffice, clonagem, revisao e upload/reupload externo de Word/PDF.
- `Lancamento` representa contas a receber e a pagar, com estados `pendente` e `pago` e vinculos opcionais a cliente e proposta.
- Nao existe entidade especifica para relatorio de servico, pedido do cliente, nota fiscal ou estado documental por etapa.
- Nao existe vinculo direto entre uma tarefa e um lancamento.

### Autenticacao e seguranca

- Ha cadastro de usuarios e campo `senha_hash`, mas nao ha login, sessao, dependencia de usuario autenticado nem autorizacao nas rotas inspecionadas.
- As senhas atuais usam SHA-256 direto, sem algoritmo especifico para senha ou salt, e o startup cria um usuario padrao com senha conhecida quando a tabela esta vazia.
- As rotas mutaveis atuais nao apresentam protecao CSRF.
- Por isso, este MVP deve continuar estritamente local/interno. Autenticacao adequada e requisito anterior a qualquer exposicao externa, que ja esta fora do escopo desta etapa.

### Testes

- Os testes substituem banco e diretorios por recursos temporarios e recriam o schema a cada caso.
- Existe cobertura de servicos e rotas para quadro, dashboard, financeiro, documentos, upload e origem de propostas.
- Nao ha testes de integracao PostgreSQL, teste de navegador completo, contrato de provedor de IA nem avaliacao de linguagem natural.

## 4. Componentes que podem ser reutilizados

| Componente | Reuso proposto |
|---|---|
| `app/db.py` e `get_db` | Transacao e sessao para consultas e comandos do assistente. |
| `Task` e relacionamentos | Fonte real das tarefas; nenhuma base paralela para o assistente. |
| `TaskCreate`, `TaskRead`, `TaskMove` | Base dos contratos, depois de restringir status e validar referencias. |
| `board_service` | Unico caminho para criar e, em fases posteriores, mover tarefas. Deve ser endurecido antes de ser exposto ao interpretador. |
| `dashboard_service` | Padrao de consulta agregada e ponto de partida para a definicao de prioridades. |
| Clientes, usuarios e propostas | Resolucao deterministica dos nomes e vinculos citados na conversa. |
| FastAPI e Jinja2 | Pagina de conversa e endpoints sem introduzir SPA ou outro framework. |
| `base.html` | Navegacao, tokens, componentes e estilos visuais existentes. |
| Pydantic | JSON Schema para saida estruturada do Ollama e validacao dupla da resposta. |
| pytest e fixture SQLite | Testes deterministas sem acessar dados reais ou exigir Ollama ativo. |
| Compose existente | Aplicacao, PostgreSQL e LibreOffice continuam como estao; Ollama fica inicialmente como processo nativo do host. |

## 5. Lacunas que precisam ser tratadas

### Antes ou dentro da primeira entrega

1. `TaskBase.status` e `TaskMove.status` aceitam qualquer string; os estados devem ser um `Literal`/enum unico compartilhado.
2. `board_service.create_task` nao valida se cliente, proposta e usuario existem nem se a proposta pertence ao cliente informado.
3. Nao ha endpoint JSON para criacao de tarefa. O assistente deve chamar um caso de uso/servico, e nao simular o formulario web.
4. A ordem atual de `get_tasks` e alfabetica por status, nao uma regra operacional de prioridade.
5. Nao existem configuracoes, health check, timeout ou tratamento de indisponibilidade do Ollama.
6. `httpx` esta apenas nas dependencias de desenvolvimento, mas sera necessario em runtime se o adaptador usar HTTP direto.
7. Nao existe contrato de interpretador que permita trocar Ollama por API futura.
8. Nao existe confirmacao/idempotencia para uma acao proposta pela IA.
9. Nao existe pagina de conversa, historico temporario da sessao nem mensagens de erro voltadas ao usuario.
10. Nao existe conjunto de frases de avaliacao em portugues para medir acerto do interpretador.

### Para o objetivo operacional completo, depois do MVP

1. Um unico `Task.status` nao representa, de forma independente, execucao, relatorio, proposta/aprovacao, pedido, nota e recebimento.
2. `servico_feito_falta_nota_pedido` informa um risco agregado, mas nao diz exatamente qual documento falta.
3. O sistema nao modela relatorio de servico nem nota fiscal; o pagamento existe como lancamento, mas sem ligacao direta com a tarefa.
4. Nao ha trilha completa de quem confirmou cada comando do assistente.
5. Nao ha transcricao, sintese, captura de microfone, cancelamento de fala ou tratamento de ruido.
6. Nao ha autenticacao real. Isso bloqueia acesso externo e deve permanecer explicitamente fora da primeira etapa.

## 6. Alternativas avaliadas

### A. Interpretacao estruturada e execucao deterministica — recomendada

O Ollama recebe a frase e um JSON Schema pequeno. Ele devolve apenas uma intencao tipada, por exemplo `consultar_tarefas`, `criar_tarefa`, `pedir_esclarecimento` ou `fora_do_escopo`. O backend resolve entidades, aplica regras, pede confirmacao e somente entao usa `board_service`.

Vantagens: menor superficie de erro, funciona com modelos menores, permite testes sem modelo, facilita trocar o provedor e impede acesso livre do LLM ao banco. Desvantagem: cada nova capacidade precisa de um comando explicitamente implementado.

### B. Loop de agente com chamadas de ferramentas

O modelo escolhe e encadeia ferramentas de consulta e escrita. E mais flexivel para conversas longas, mas aumenta latencia, variacao entre modelos, consumo de memoria e risco de chamadas indevidas. Nao e a melhor base para o Ryzen sem GPU nem para a primeira operacao real.

### C. Regras e expressoes sem modelo

Seria leve e previsivel, mas entenderia poucas formas de falar e nao validaria a decisao de usar IA local como base da futura voz.

**Decisao proposta:** alternativa A. Ela usa o modelo somente para compreender linguagem; as regras continuam Python e SQLAlchemy.

## 7. Arquitetura alvo

```text
Pagina Jinja2 de conversa
        |
        v
Router FastAPI do assistente
        |
        v
Servico de aplicacao / orquestrador
   |                |                 |
   v                v                 v
Interpretador    Regras e         Registro de acao
(interface)      resolucao        pendente/executada
   |
   +-- Ollama HTTP local (primeiro adaptador)
   +-- API externa (adaptador futuro, fora do MVP)

O servico de aplicacao usa board_service e consultas SQLAlchemy.
O interpretador nunca recebe Session, modelo ORM ou credencial do banco.
```

### Contrato do interpretador

O contrato deve receber mensagens de conversa limitadas e devolver um dos comandos validados por Pydantic:

- `consultar_tarefas`: filtros opcionais por status, prazo, cliente, responsavel e limite;
- `consultar_prioridades`: sem texto SQL e com regra de ordenacao definida pela aplicacao;
- `criar_tarefa`: titulo e campos opcionais extraidos como texto/data, ainda sem persistir;
- `pedir_esclarecimento`: campo ausente ou entidade ambigua;
- `fora_do_escopo`: pedido nao suportado na entrega atual.

O adaptador Ollama deve usar `POST /api/chat`, `stream=false`, temperatura baixa e `format` com JSON Schema. A resposta e validada novamente por Pydantic. JSON invalido, timeout, modelo ausente ou Ollama indisponivel resultam em mensagem clara e **nenhuma mutacao**.

### Resolucao e regras

- O modelo pode extrair o nome falado de cliente, responsavel ou proposta, mas o backend resolve IDs.
- Correspondencia unica pode ser usada; zero ou multiplas correspondencias exigem esclarecimento.
- Se houver proposta, o cliente deve ser derivado ou conferido contra ela.
- Status, datas, limites e tamanho de texto sao validados fora do modelo.
- O modelo recebe apenas o contexto necessario. A lista completa do banco e documentos nao devem ser enviados ao prompt.

### Confirmacao e idempotencia

- Consultas sao executadas imediatamente.
- Criacao retorna uma previa com os campos normalizados e botoes **Confirmar** e **Cancelar**.
- A previa e registrada como uma acao pendente com identificador unico; a confirmacao muda a acao e cria a tarefa na mesma transacao.
- Repetir a mesma confirmacao devolve a tarefa ja criada, sem duplicar.
- Nao e necessario armazenar a transcricao completa. O registro pode guardar comando normalizado, resultado, estado e timestamps, reduzindo exposicao de conversa.

### Regra inicial de prioridade proposta

Esta regra precisa ser aprovada pelo responsavel de negocio antes da implementacao:

1. servicos em `servico_feito_falta_nota_pedido`, porque representam o risco principal de trabalho executado sem documentacao/faturamento;
2. demais tarefas vencidas e nao concluidas;
3. tarefas `em_andamento`, por prazo e ordem;
4. tarefas `a_fazer`, por prazo e ordem;
5. `aguardando_cliente`, mostradas separadamente para acompanhamento, sem serem tratadas como execucao imediata;
6. `concluido` somente quando solicitado.

O assistente nao deve afirmar que uma tarefa esta paga, faturada ou documentada apenas porque o servico foi feito ou o card foi concluido.

## 8. Menor primeira entrega proposta

### Incluido

- Nova pagina `/web/assistente`, integrada a navegacao e ao visual atual.
- Campo de texto, historico apenas da sessao da pagina, indicador de processamento e mensagens de erro.
- Conversa em portugues para:
  - "O que e prioridade hoje?";
  - listar tarefas atrasadas ou por estado;
  - procurar tarefas por cliente ou responsavel;
  - preparar criacao de tarefa com titulo, descricao, prazo, estado e vinculos opcionais;
  - confirmar ou cancelar a criacao;
  - abrir a tarefa criada no quadro.
- Ollama local atras de uma interface de provedor.
- Criacao na mesma tabela `tasks`, visivel imediatamente em `/web/board`.
- Testes deterministas do contrato, regras, servico, rotas e idempotencia.
- Um conjunto pequeno de avaliacao manual/automatizada com frases reais em portugues.

### Nao incluido

- microfone, transcricao ou voz sintetizada;
- mover, editar, concluir ou excluir tarefas por conversa;
- criar propostas, relatorios, notas ou lancamentos;
- ler conteudo de DOCX/PDF para responder;
- e-mail, emissao fiscal, acesso remoto ou app movel;
- autonomia para executar uma sequencia de ferramentas;
- RAG, banco vetorial ou fine-tuning.

Essa fatia comprova o ponto mais arriscado — interpretar fala natural futura em comandos seguros sobre dados reais — sem misturar audio, documentos e financeiro.

## 9. Arquivos previstos para a primeira entrega

Estrutura sugerida, ainda nao criada:

| Arquivo | Responsabilidade |
|---|---|
| `app/assistant/contracts.py` | Comandos, respostas e tipos independentes de provedor. |
| `app/assistant/interpreter.py` | `Protocol`/interface do interpretador. |
| `app/assistant/ollama.py` | Cliente HTTP, timeout e traducao da API Ollama para o contrato. |
| `app/assistant/service.py` | Orquestracao, resolucao de entidades, previa, confirmacao e respostas. |
| `app/routers/assistant.py` | Pagina e endpoints finos, sem regra de negocio. |
| `app/templates_web/assistant.html` | Interface textual usando o design system existente. |
| `app/models.py` | Registro minimo de acao pendente/executada para confirmacao idempotente. |
| `app/schemas.py` | Enum de status e contratos HTTP que pertencem a API da aplicacao. |
| `app/services/board_service.py` | Validacao de referencias e consultas de prioridade reutilizaveis. |
| `app/config.py` | Provider, URL, modelo, timeout e limites, todos configuraveis. |
| `app/main.py` | Inclusao do router do assistente. |
| `app/templates_web/base.html` | Um link de navegacao, sem redesenho. |
| `requirements.txt` | Cliente HTTP de runtime, se `httpx` for mantido. |
| `docker-compose.yml` | Somente variaveis da aplicacao para alcancar Ollama no host; nao incluir modelo ou segredo. |
| `tests/test_assistant_contracts.py` | Validacao de comandos e rejeicao de saida invalida. |
| `tests/test_assistant_service.py` | Regras, ambiguidades, confirmacao e nao duplicacao. |
| `tests/test_assistant_routes.py` | HTML/API e comportamento quando Ollama falha. |
| `tests/test_assistant_ollama.py` | Contrato HTTP simulado, sem baixar ou executar modelo. |
| `tests/fixtures/assistant_cases.json` | Frases em portugues com intencao e campos esperados, sem dados pessoais reais. |
| `README.md` | Instalacao, configuracao, health check e operacao no Mac/Windows. |

O registro de acao e uma tabela nova. Como o projeto nao usa migracoes, `create_all` a cria em instalacoes existentes; qualquer alteracao posterior em colunas precisara de uma estrategia explicita de migracao. Nao se deve ampliar `ensure_schema_compatibility` de forma improvisada.

## 10. Etapas de implementacao

### Etapa 0 — aprovar contrato operacional

- Validar a ordem de prioridades acima com o usuario.
- Reunir 20–30 frases anonimizadas que ele realmente usaria.
- Definir vocabulario dos cinco estados e como falar datas relativas.
- Fixar que toda criacao exige previa e confirmacao.

**Saida verificavel:** exemplos aprovados e criterios de prioridade sem ambiguidade.

### Etapa 1 — endurecer o dominio de tarefas

- Centralizar os estados validos em um tipo unico.
- Validar cliente, responsavel, proposta e consistencia proposta/cliente.
- Criar uma consulta de prioridades deterministica, com limite e ordenacao estavel.
- Adicionar testes antes das mudancas e preservar os fluxos web existentes.

**Saida verificavel:** quadro atual continua funcionando e comandos invalidos nao chegam ao banco.

### Etapa 2 — contrato independente e adaptador Ollama

- Criar os comandos Pydantic e a interface do interpretador.
- Implementar Ollama por HTTP sem acoplar o restante da aplicacao ao SDK.
- Adicionar configuracao, timeout, health check e erros seguros.
- Testar o adaptador com transporte HTTP simulado.

**Saida verificavel:** um interpretador falso e o Ollama implementam o mesmo contrato; trocar um pelo outro nao altera servicos ou regras.

### Etapa 3 — caso de uso conversacional seguro

- Orquestrar interpretacao, consultas, resolucao de nomes e formatacao da resposta.
- Persistir a acao pendente e confirmar criacao de forma transacional/idempotente.
- Nao registrar prompt completo nem dados desnecessarios em logs.
- Limitar tamanho de mensagens, quantidade de contexto e numero de resultados.

**Saida verificavel:** testes de servico consultam e criam uma unica tarefa com interpretador falso, inclusive sob confirmacao repetida.

### Etapa 4 — pagina e endpoints

- Adicionar router, pagina Jinja2 e link na navegacao.
- Reutilizar componentes e estilos do `base.html`.
- Exibir previa, confirmacao, cancelamento, indisponibilidade e link para o quadro.
- Nao adicionar microfone nesta etapa.

**Saida verificavel:** fluxo completo via `TestClient` e verificacao manual no navegador local.

### Etapa 5 — qualificacao do modelo e instalacao

- Instalar Ollama no Mac e avaliar modelos `instruct` quantizados na faixa de 3–4B primeiro.
- Executar o mesmo conjunto de frases no Mac e no Windows de destino.
- Escolher e fixar o modelo pelo resultado no Windows, nao pelo desempenho no M5.
- Documentar download, espaco em disco, inicializacao, URL e diagnostico.
- Nao baixar modelo automaticamente durante o startup da aplicacao.

**Saida verificavel:** relatorio de acuracia e latencia no equipamento de destino, com modelo e quantizacao fixados.

### Etapa 6 — voz local opcional — implementada

- Manter a API interna recebendo texto; STT sera apenas outro produtor de texto.
- Manter a resposta textual; TTS sera apenas outro consumidor dessa resposta.
- Avaliar motores locais CPU-friendly no Windows com o mesmo criterio de latencia e privacidade.
- Adicionar botao de gravar, cancelamento, estado visual e confirmacao falada/visual sem mudar as regras de tarefa.

**Saida verificavel:** ativar ou desativar audio nao muda interpretador, regras nem persistencia.

Implementacao entregue: captura via `MediaRecorder`, VAD local no navegador,
faster-whisper e Piper atras de protocolos, executor limitado fora do event loop,
validacao de container/tamanho/duracao, politica especial para comandos curtos,
reproducao interrompivel e protecao contra retomada depois de encerrar. A transcricao
usa o mesmo endpoint textual e o mesmo `AssistantService`; nao existe segundo caminho
de criacao. Teste humano no navegador e teste de desempenho no Ryzen permanecem como
criterios de aceite operacional, nao como mudanca de arquitetura.

## 11. Criterios de aceitacao da primeira entrega

### Funcionais

1. "O que e prioridade hoje?" retorna apenas tarefas existentes, na ordem aprovada, com ID/titulo, estado, prazo e vinculos disponiveis.
2. Uma consulta vazia informa que nao ha tarefas; nao inventa exemplos como se fossem dados reais.
3. "Crie uma tarefa para ..." apresenta previa e nao altera o banco antes da confirmacao.
4. Confirmar cria exatamente uma tarefa e ela aparece no quadro; repetir a confirmacao nao duplica.
5. Cancelar nao cria tarefa.
6. Cliente, proposta ou responsavel ambiguo gera pergunta de esclarecimento.
7. Estado, data ou referencia invalida e rejeitada por regra da aplicacao, independentemente da resposta do modelo.
8. Pedidos para enviar e-mail, emitir nota ou realizar outra acao fora do escopo sao recusados claramente.
9. Ollama indisponivel, timeout ou JSON invalido gera erro recuperavel e zero mutacoes.
10. Nenhuma resposta equipara servico feito a relatorio, proposta, nota ou pagamento concluidos.

### Arquitetura e qualidade

1. Testes de servico nao dependem do Ollama; usam um interpretador falso.
2. O adaptador Ollama pode ser substituido por outro provider sem alterar as regras ou os routers.
3. O modelo nao recebe acesso ao ORM, SQL, filesystem ou endpoints genericos.
4. Logs tecnicos nao contem conversa completa nem dados pessoais desnecessarios.
5. Todos os testes atuais continuam passando, alem dos novos testes.
6. O Compose continua valido e o boot funciona com Ollama disponivel ou desabilitado.
7. A pagina respeita o design existente e funciona por teclado, com foco e mensagens acessiveis.
8. Nao ha mudanca nos fluxos de proposta, DOCX/PDF, importacao ou financeiro.

### Qualificacao local

1. O conjunto aprovado de frases deve atingir pelo menos 90% de intencoes corretas e 100% de seguranca: nenhuma mutacao sem confirmacao.
2. No Windows de destino, depois de aquecido, a meta inicial e mediana de ate 10 s e p95 de ate 20 s para interpretar comandos curtos; se nao atingir, reduzir o modelo antes de ampliar hardware.
3. Memoria total da maquina deve manter margem para Windows, PostgreSQL, LibreOffice e navegador; nao aceitar configuracao que cause paginacao sustentada.
4. O modelo fica carregado no maximo em uma instancia e a aplicacao limita concorrencia de interpretacao.

## 12. Mac de desenvolvimento versus Windows de destino

| Tema | Mac Apple Silicon M5 atual | Windows Ryzen 7 3700U, 20–24 GB, sem GPU dedicada |
|---|---|---|
| Arquitetura | `arm64`, memoria unificada e aceleracao Apple. | `x86_64`; planejar inferencia por CPU, mesmo se houver grafico integrado. |
| Memoria observada/prevista | 16 GB verificados neste Mac. | 20–24 GB informados; mais capacidade, mas CPU muito menos favoravel para LLM. |
| Ollama | Aplicacao nativa; o site oficial exige macOS 14 ou posterior. Ainda nao instalado. | Aplicacao nativa oficial para Windows 10 ou posterior. Nao depender de WSL. |
| Desempenho | Bom para iterar, mas nao serve como referencia de producao. | E o ambiente que decide modelo, contexto, timeout e concorrencia. |
| Aplicacao | Pode rodar nativa com SQLite para desenvolvimento ou via Compose. | Preferir Compose existente para FastAPI/PostgreSQL/LibreOffice e Ollama nativo no host. |
| Conectividade | App nativa usa `127.0.0.1:11434`; container usa endereco do host. | Container deve alcancar o Ollama do host, normalmente por `host.docker.internal`; validar bind e firewall sem expor a API na rede. |
| Paths | Paths POSIX e binario nativo do LibreOffice se executar fora do container. | Paths e PowerShell diferem; dentro do container permanecem Linux e `/usr/bin/soffice`. |
| Inicializacao | Ollama e app podem ser iniciados manualmente no desenvolvimento. | Documentar ordem de startup e recuperacao apos reinicio; nao assumir usuario tecnico. |
| Modelos | Downloads e caches nao devem entrar no Git ou imagem Docker. | Reservar SSD: modelos ocupam varios GB; fixar `OLLAMA_MODELS` se necessario. |

Orientacao pratica: comecar por um modelo quantizado de 3–4B com bom portugues e saida estruturada. Um modelo maior pode caber em RAM, mas isso nao significa que tera latencia aceitavel no 3700U. A escolha final exige benchmark no destino.

## 13. Como iniciar o sistema atual

### Caminho identificado no README e no codigo: Docker Compose

```powershell
docker compose up --build
```

Depois, acessar `http://localhost:8000/` e `http://localhost:8000/healthz`. O Compose inicia PostgreSQL, aguarda o health check e executa `python /app/run.py`; o container tambem inclui LibreOffice.

**O que foi verificado:** a configuracao Compose foi validada com `config --quiet`.

**O que nao foi executado:** `docker compose up --build`, pois isso poderia usar configuracao/volumes persistentes e tocar dados reais.

### Caminho nativo identificado e testado de forma isolada

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python run.py
```

No macOS, a ativacao equivalente e `source .venv/bin/activate`. O projeto declara Python 3.12 no README e na imagem Docker; o boot isolado tambem funcionou no Python 3.14.5 instalado neste Mac, mas os avisos de deprecacao reforcam que Python 3.12 deve continuar como baseline reproduzivel ate uma atualizacao deliberada.

O teste de boot feito nesta analise usou SQLite e diretorios descartaveis fora do projeto. Isso confirma o comando e o health check, nao confirma conexao com o PostgreSQL ou geracao LibreOffice deste checkout.

## 14. Fontes externas consultadas

- [Ollama para macOS](https://ollama.com/download/mac): requisito atual de macOS 14 ou posterior.
- [Ollama para Windows](https://ollama.com/download/windows): instalacao nativa e requisito atual de Windows 10 ou posterior.
- [API de chat do Ollama](https://docs.ollama.com/api/chat): `POST /api/chat`, tools, formato JSON/JSON Schema, timeout e keep-alive disponiveis no contrato.
- [Structured Outputs do Ollama](https://docs.ollama.com/capabilities/structured-outputs): schema Pydantic/JSON Schema e validacao estruturada.
- [Tool calling do Ollama](https://docs.ollama.com/capabilities/tool-calling): capacidade disponivel, deliberadamente adiada para evitar um loop autonomo no MVP.

## 15. Proximo passo recomendado

Revisar e aprovar tres pontos antes de implementar:

1. a regra de prioridade da secao 7;
2. o fluxo obrigatorio de previa e confirmacao;
3. 20–30 frases anonimizadas que representem a forma real de falar do usuario.

Com isso aprovado, a primeira implementacao deve comecar pela Etapa 1, com testes do dominio de tarefas, e nao pela instalacao do modelo ou pela interface de voz.
