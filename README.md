# Sistema interno — AD Balanças e Engenharia

Aplicação web interna para organizar o trabalho comercial e operacional da AD Balanças: clientes, propostas, tarefas, serviços, mensagens de e-mail e lançamentos financeiros. O sistema usa FastAPI, páginas renderizadas com Jinja2 e SQLAlchemy; os fluxos existentes foram ampliados gradualmente e não dependem de um frontend separado.

> **Segurança:** o projeto agora exige autenticação por sessão quando habilitado; a instância local 8013 deve permanecer na versão anterior até o primeiro administrador ser provisionado e seu login validado pelo procedimento interativo. Mantenha aplicação e PostgreSQL em `127.0.0.1`; não publique o serviço na rede ou na internet.

## O que o projeto faz

### Hoje e organização do trabalho

- A página inicial **Hoje** reúne tarefas atrasadas, com prazo próximo e originadas de e-mail, chamados de serviço em andamento ou com etapas administrativas pendentes e contas a pagar/receber que exigem atenção.
- Os itens são ordenados por critérios determinísticos, como atraso, prazo e estado do serviço, e incluem o motivo da prioridade. A tela é uma lista priorizada, não uma agenda com horários inventados.
- A área **Tarefas** oferece quadro Kanban para criar, editar, ordenar/mover e acompanhar tarefas, com prazo, responsável, cliente cadastrado ou nome livre ainda pendente de vinculação e, quando aplicável, ligação a uma proposta.

### Clientes, responsáveis e propostas

- Cadastro e edição de clientes, com dados comerciais e de contato; cadastro de usuários/responsáveis para associação a propostas e tarefas.
- Criação de propostas com identificação sequencial e revisão, cliente e responsável, objeto/equipamento, contato, local, deslocamento, alimentação, condição de pagamento, imposto, itens e cronograma.
- Histórico e consulta de propostas por cliente, sugestão de itens a partir do histórico, duplicação e criação de revisão.
- Geração de documento Word (DOCX) a partir de modelo editável e tentativa de conversão para PDF por LibreOffice. O Word gerado pode ser baixado, editado externamente e reenviado para atualização/geração do PDF; há também um fluxo de upload externo com prévia e confirmação.
- Importação assistida em lote de propostas legadas em PDF: primeiro pré-visualiza os dados extraídos; a persistência depende de confirmação.

### Acompanhamento de serviços

- Registro de um chamado por atendimento, com eventos append-only separados para visita/inspeção, início de execução, conclusão, verificação de retorno ou correção de informação.
- Inspeção não equivale a reparo: a execução técnica só fica concluída com evento explícito de conclusão.
- O histórico de eventos é preservado; correções são acrescentadas ao histórico e a projeção do estado atual é reconstruída de forma determinística.
- As etapas administrativas têm estados próprios: relatório, proposta, envio da proposta, nota fiscal e recebimento. Assim, serviço tecnicamente concluído pode continuar administrativamente aberto.
- Lembretes dessas etapas podem ser vinculados ao quadro. O sistema não gera nem envia propostas e não emite nota fiscal automaticamente.
- Após a conclusão técnica, a tela de detalhes e o Assistente por texto/voz permitem revisar campos do chamado e confirmar a geração de relatório técnico em DOCX e PDF. A conversa usa o mesmo serviço, modelo DOCX e rotas de download já existentes; não há um segundo gerador. Cliente/equipamento, problema, análise, trabalho, datas e verificações vêm do cadastro e dos eventos efetivos; ausências ficam destacadas para revisão, sem texto técnico inventado.
- O Assistente resolve apenas chamados concluídos; se houver mais de um, pergunta qual usar. A prévia pode ser editada no chat ou corrigida em linguagem natural. Toda correção troca o token de confirmação anterior. DOCX/PDF só são criados depois da confirmação, e os links de ambos aparecem na conversa.
- A confirmação grava um snapshot imutável, mantém referências aos eventos de origem e atualiza somente a etapa administrativa de relatório com histórico — sem acrescentar evento técnico nem alterar os existentes. Repetir a mesma solicitação ou confirmação reconcilia a ação; novas versões confirmadas preservam as anteriores. Relatórios são salvos em `output/service-reports/` e não são enviados automaticamente.

### Contas a pagar e a receber

- Cadastro e edição de lançamentos a pagar ou receber, com descrição, valor, emissão, vencimento, estado e data de pagamento/recebimento; associações disponíveis a fornecedor, cliente e proposta conforme o tipo.
- Separação entre itens em aberto, atrasados, pagos/recebidos e arquivados. Atraso depende de lançamento ainda pendente e vencimento anterior a hoje; um vencimento futuro permanece em aberto.
- Alterações relevantes e arquivamento são registrados no histórico. Lançamentos elegíveis são arquivados após 30 dias da data de pagamento/recebimento confirmada, sem exclusão definitiva.
- Não há pagamento bancário, baixa automática por e-mail ou emissão fiscal.

### E-mails e mensagens

- A página **E-mails e mensagens** mostra mensagens consultadas/sincronizadas, separando fila operacional, revisão e informativos, com categoria, evidências resumidas, prioridade sugerida e estado de sincronização.
- Existe provedor sintético para desenvolvimento e adaptador Yahoo via IMAP, configurável e desativado por padrão. O acesso Yahoo é somente leitura: seleciona pastas em modo read-only e usa leitura que não altera flags; não envia, move nem exclui mensagens.
- O sincronizador periódico é opcional e tem intervalo configurável. A sincronização inicia em um marco de ativação e usa identificadores estáveis para evitar duplicar mensagens e rascunhos em releituras/retries; não é uma importação irrestrita do histórico antigo.
- A classificação usa evidência do assunto/corpo para distinguir, entre outras categorias, solicitação de orçamento de cliente, cotação de fornecedor, pedido de compra, serviço, cobrança, nota fiscal, comprovante, resposta pendente e informativo. O corpo integral não é persistido no cache da caixa.
- A sincronização não cria tarefas nem lançamentos financeiros. Pedidos de orçamento (e outras categorias operacionais elegíveis) viram prévias/rascunhos revisáveis; a tarefa só é criada após confirmação explícita e preserva o vínculo idempotente com o e-mail. Cotação comercial enviada por fornecedor não é tratada como pedido de orçamento do cliente.
- Contas a pagar e notas recebidas podem gerar proposta estruturada de lançamento pendente. Valor, fornecedor, datas e número da nota só são preenchidos com evidência explícita; campos ausentes ou ambíguos ficam destacados, e uma nota recebida exige confirmar que existe obrigação a pagar. Só a confirmação explícita cria o lançamento e seu histórico; nenhuma conta é paga, baixada ou emitida automaticamente. Mensagens incertas permanecem na revisão.
- A extração determinística guarda apenas campos estruturados e evidências genéricas, não o corpo completo. O Gemini não acessa o banco nem autoriza gravações; ele não é necessário para classificar/extrair esses campos. Ler pelo Yahoo continua somente leitura.
- O painel não prova cobertura completa de Enviados: a avaliação de resposta pendente depende de essa pasta estar acessível e sincronizada. A marca “lido” é a flag do servidor, não prova que uma pessoa compreendeu a mensagem.

### Assistente por texto e voz

- A página **Assistente** mantém histórico e entende pedidos em português para consultar o quadro/agenda, consultar serviços/retornos e, se o leitor estiver configurado, consultar e-mails. Também prepara tarefas e registros de eventos/lembretes de serviço para confirmação; uma data de retorno confirmada cria uma tarefa vinculada ao evento, sem duplicar em retries.
- Após conclusão técnica, a tela do chamado e o Assistente por texto/voz oferecem a mesma prévia editável e confirmação para gerar relatório técnico DOCX/PDF; a proposta continua no próprio fluxo. Gemini/Ollama interpretam a solicitação, mas o serviço existente busca dados e gera os arquivos determinística e idempotentemente. A geração e a etapa administrativa não alteram eventos técnicos. Os links de download retornam no chat. A conversão usa LibreOffice configurado. No launcher local da 8013, se ele não estiver instalado no host, pode ser usado o conversor já existente na imagem local do projeto: é uma execução efêmera sem rede e com montagem apenas da pasta temporária daquele documento. Sem um conversor disponível, nenhum relatório é registrado. Documentos nunca são enviados automaticamente.
- O Gemini é o **interpretador de linguagem padrão** pela API; Ollama local permanece como alternativa selecionável. O provedor transforma fala transcrita ou texto em comando estruturado permitido e ajuda a formular respostas naturais. Nenhum deles acessa o banco diretamente ou grava dados por conta própria.
- Os pedidos conhecidos de consulta (por exemplo, agenda e algumas intenções de e-mail) também têm roteamento determinístico no backend. Quando necessário, a aplicação consulta os serviços e o banco reais; a resposta fica fundamentada nos resultados dessa solicitação, não em uma afirmação livre do modelo.
- Existe uma interface `AssistantProvider`, com adaptadores Gemini e Ollama selecionáveis por `LLM_PROVIDER`. Gemini é o padrão; para processamento exclusivamente local, defina `LLM_PROVIDER=ollama`. As regras de domínio e validações ficam na aplicação e não há fallback automático entre provedores. Gemini requer chave, conectividade externa e plano aprovado; o conteúdo enviado à API deixa de ser exclusivamente local.
- Comandos e argumentos são validados por esquemas tipados e por uma lista explícita de ferramentas. Não são aceitos SQL, shell ou execução de código gerado pelo modelo. Resposta estrutural inválida não autoriza uma gravação; o backend pode fazer uma única tentativa controlada de reparo e encerra com erro compreensível se ela falhar.
- Consultas de tarefa, serviço e e-mail são executadas por serviços específicos do backend. O assistente só deve dizer que consultou quando houver evidência de resultado, distinguindo sucesso, vazio confirmado, falha, parcial e capacidade não configurada.
- Criações manuais passam por rascunho e confirmação explícita antes de gravar; correções invalidam a confirmação anterior. A persistência usa identificadores de requisição/ação para reconciliar repetição e evitar duplicidade. Cliente ausente ou ambíguo não bloqueia a tarefa: mantém-se o nome informado, sem inventar cliente ou ID, e o vínculo fica pendente de revisão.
- O modelo do Assistente não envia e-mails, não altera mensagens, não paga/baixa contas e não emite nota fiscal. A aba Promoções tem transporte SMTP separado e só pode enviar depois de configuração própria e confirmação explícita da campanha.

### Promoções por e-mail

- A aba **Promoções** combina descrição livre com prompt-base fixo para gerar imagem, assunto e corpo usando Gemini. O período é opcional; a aplicação valida números e condições para reduzir risco de conteúdo comercial inventado.
- Imagem e mensagem têm prévias editáveis. A imagem pode ser regenerada com uma referência visual PNG/JPEG opcional ou substituída; o texto comercial continua revisável independentemente da arte.
- A ficha de cada cliente permite cadastrar contatos de campanha. Autorização começa desativada e exige e-mail válido, origem e data registrados; clientes antigos não são incluídos automaticamente. Revogações têm histórico append-only.
- Rascunho e seleção de destinatários não enviam nada. O envio requer `PROMOTION_SMTP_*` configurado separadamente do IMAP Yahoo, confirmação explícita e revalidação de consentimento. O resultado fica registrado por campanha e destinatário.
- Cada mensagem é individual. Repetições não reenviam destinatários concluídos; um resultado SMTP ambíguo fica para revisão, sem retry automático. Não existe envio de campanhas nos testes.
- Veja [documentação de campanhas](docs/promocoes-campanhas.md) para variáveis de ambiente, privacidade, migração, consentimento e limites.

#### Como a IA é usada

```text
Texto do navegador ───────────────────────────────┐
Microfone → STT local (faster-whisper) → texto ───┤
                                                  ↓
                                   FastAPI / Assistente
                     roteamento + histórico + capacidades disponíveis
                                                  ↓
                  Gemini API ou Ollama local via AssistantProvider
                    comando estruturado com argumentos validados
                                                  ↓
           ferramenta permitida → serviços da aplicação → banco real
                                                  ↓
                     validação de evidência e resposta em português
                                                  ↓
                    texto no chat → TTS local (Piper), se solicitado
```

O navegador conversa apenas com o FastAPI. É o backend que chama o Ollama e os serviços; o endereço do Ollama não é exposto ao navegador. No modo Docker, o endereço configurado pode usar `host.docker.internal`, mas a comunicação do Ollama com o host precisa ser testada para a instalação concreta. Não abra a porta `11434` para a rede.

Exemplos do que se pode pedir:

- “O que devo fazer hoje?” — consulta o quadro real e retorna uma ordem priorizada, sem alterar tarefas nem inventar blocos de horário.
- “Crie uma tarefa para revisar o relatório amanhã” — prepara os campos, resolve a data no fuso configurado e pede confirmação antes de salvar.
- “Fui à empresa Alfa, mas só fiz uma inspeção” — registra um rascunho de evento como inspeção; não declara reparo concluído.
- “Quais e-mails pedem orçamento?” — consulta o provedor de e-mail somente se ele estiver configurado e disponível; uma falha não é apresentada como caixa vazia.

#### Configuração do interpretador

Gemini é o provedor padrão; Ollama local continua disponível como alternativa. Com Gemini, o backend envia ao Google o texto da conversa e o contexto necessário para interpretar o pedido. A seleção por `LLM_PROVIDER` não altera roteamento determinístico, confirmações, serviços de banco nem ferramentas autorizadas. STT e TTS continuam independentes e locais. Não há fallback automático entre provedores.

O modelo não é fixado em vários pontos do código. Para Ollama, configure o nome exato que `ollama list` mostrar. Para o Gemini, configure `GEMINI_MODEL`; o valor inicial de referência é `gemini-3.1-flash-lite`, definido em um único padrão de configuração e sobrescrevível por ambiente. Antes de enviar dados reais da empresa, gere uma chave nova (a chave anteriormente colada deve ser considerada comprometida), confirme que a conta/projeto e o plano têm termos de tratamento de dados adequados ao uso empresarial e aprove o envio de conteúdo ao serviço externo. Não use plano gratuito com dados reais sem verificar seus termos: a documentação atual informa tratamento diferente de dados entre níveis. O smoke test, se usado, envia somente uma pergunta sintética.

| Variável | Padrão | Para que serve |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | Provedor de interpretação: `gemini` ou `ollama`. Valor inválido é rejeitado na configuração. |
| `GEMINI_API_KEY` | vazio | Chave lida no backend e enviada no cabeçalho HTTPS; nunca é retornada à interface ou registrada nos logs. |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | Modelo configurável. Consulte a lista oficial antes de atualizar o identificador. |
| `GEMINI_CONNECT_TIMEOUT` | `3` segundos | Limite para conexão à API Gemini. |
| `GEMINI_READ_TIMEOUT` | `60` segundos | Limite de espera pela API. |

Guarde uma chave nova em `.env.gemini.local` (explicitamente ignorado pelo Git) ou em um gerenciador de segredos do sistema. Edite o arquivo local com um editor, sem colocar o valor em comandos, histórico do shell ou argumentos de processo; `.env.example` mantém a chave vazia. Revogue a chave anteriormente exposta. Para iniciar o servidor com esse arquivo, use `APP_ENV_FILE=.env.gemini.local python run.py`. Para voltar ao modo local, defina `LLM_PROVIDER=ollama` e configure `OLLAMA_BASE_URL` e `OLLAMA_MODEL`. Ausência de chave, autorização inválida, modelo ausente, cota, timeout e resposta inválida são apresentados como erros; nunca há fallback silencioso.

O modelo Gemini usado como referência foi escolhido por ser apresentado pela documentação oficial como opção estável, leve e de baixo custo relativo; disponibilidade, preço, limites e termos podem mudar. Consulte [modelos oficiais](https://ai.google.dev/gemini-api/docs/models), [preços e níveis de dados](https://ai.google.dev/gemini-api/docs/pricing) e [boas práticas para chaves](https://ai.google.dev/gemini-api/docs/api-key) antes de cada adoção. O adaptador chama a API pelo backend via HTTPS, envia a declaração das ferramentas autorizadas e valida os argumentos novamente nos contratos Pydantic existentes; o modelo não recebe acesso ao banco, shell ou sistema de arquivos.

Para Ollama, configure o endereço e o modelo local:

| Variável | Padrão | Para que serve |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Endpoint local chamado pelo backend. |
| `OLLAMA_MODEL` | vazio | Modelo instalado que fará a interpretação; obrigatório para conversa com IA. |
| `OLLAMA_CONNECT_TIMEOUT` | `3` segundos | Limite para estabelecer conexão. |
| `OLLAMA_READ_TIMEOUT` | `60` segundos | Limite inicial para aguardar uma inferência. |
| `OLLAMA_MAX_OUTPUT_TOKENS` | `180` | Limita o tamanho da saída por inferência. |
| `ASSISTANT_TIMEZONE` | `America/Recife` | Fuso usado para “hoje”, datas relativas e consultas temporais. |
| `ASSISTANT_CONTEXT_MESSAGES` | `12` | Limita quantas mensagens recentes entram no contexto. |
| `ASSISTANT_MAX_TOOL_ROUNDS` | `2` | Limita consultas/ferramentas distintas numa rodada. |
| `ASSISTANT_REQUEST_LEASE_SECONDS` | `120` | Prazo de expiração/reconciliação de uma requisição interrompida. |

No Mac e Linux, além das variáveis de inicialização mostradas adiante, o servidor Ollama pode ser executado estritamente no loopback e sem recursos de nuvem:

```bash
OLLAMA_NO_CLOUD=1 \
OLLAMA_HOST=127.0.0.1:11434 \
OLLAMA_NUM_PARALLEL=1 \
OLLAMA_MAX_LOADED_MODELS=1 \
OLLAMA_CONTEXT_LENGTH=4096 \
ollama serve
```

Inicie esse comando somente se Ollama ainda não estiver rodando por outro processo. Em outro terminal, inicie o FastAPI com `OLLAMA_BASE_URL` e `OLLAMA_MODEL`. Confirme a instalação com `ollama list`; a página `/web/assistente` permanece acessível quando o provedor está indisponível, mas mostrará falha ao tentar uma inferência. O backend diferencia serviço fora do ar, modelo ausente, timeout e resposta inválida.

Uma configuração de modelo documentada para teste no Mac foi `qwen3:4b-instruct-2507-q4_K_M` (4B, Q4_K_M, cerca de 2,5 GB, Apache-2.0). Isso é uma referência reproduzível, não um padrão obrigatório nem garantia de qualidade/desempenho no Windows. Leia [`docs/assistente/execucao.md`](docs/assistente/execucao.md) e a validação antes de escolher ou baixar um modelo. No destino Ryzen 7 3700U, considere CPU sem GPU dedicada e meça latência diretamente; velocidade no Apple Silicon não prevê a velocidade no Windows.

Instalação nativa indicada nos documentos do projeto:

```bash
brew install --cask ollama-app
ollama list
# Opcional: só se este for o modelo escolhido e houver espaço suficiente.
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

No Windows, instale Ollama nativamente e confira o modelo com `ollama list`. Não baixe automaticamente vários modelos nem trate o modelo de referência como exigência. Para executar Ollama estritamente local, use `OLLAMA_NO_CLOUD=1` e `OLLAMA_HOST=127.0.0.1:11434` no processo que inicia o servidor; não inicie um segundo `ollama serve` se o serviço já estiver ativo.

#### Voz local: STT e TTS

- **STT (fala para texto):** faster-whisper, com modelo `small` multilíngue, idioma português, execução CPU/INT8. É carregado localmente pelo FastAPI.
- **TTS (texto para fala):** Piper 1.8.0 com a voz brasileira `pt_BR-faber-medium`; o sintetizador fica atrás de um adaptador substituível.
- **Fluxo contínuo:** o usuário inicia uma conversa, o navegador detecta fala e silêncio, envia o trecho ao backend, mostra a transcrição no histórico como mensagem normal, recebe a resposta, reproduz a fala sintetizada e retoma a escuta. O usuário encerra a sessão explicitamente; confirmações de ações continuam obrigatórias.
- Áudio é temporário durante processamento e removido depois; não é salvo como histórico. Transcrição e resposta são mensagens de conversa e ficam persistidas no banco. Telemetria guarda metadados técnicos, não gravação ou raciocínio interno.
- Transcrição e síntese rodam fora do event loop em workers limitados, com limites de duração, tamanho, concorrência e timeout. Falhas de STT/TTS são reportadas sem deixar a conversa presa; repetição de fala não repete a ação nem a solicitação conversacional.
- As dependências Python opcionais estão em `requirements-voice.txt`; os modelos são downloads locais separados. O script `scripts/download_assistant_voice_models.py` baixa o modelo `Systran/faster-whisper-small` e a voz Piper para `.models/assistant_voice`, verifica a voz e limita o total do download a 2 GB. O startup não baixa modelos automaticamente.
- Licenças e versões verificadas: faster-whisper e Whisper small (MIT), Piper (GPL-3.0-or-later), voz Faber (dataset CC0/repositório MIT), Ollama (MIT) e modelo Qwen citado (Apache-2.0). O uso atual é interno; eventual distribuição futura exige rever as obrigações, especialmente as do Piper. Detalhes e referências estão em [`docs/assistente/validacao-voz-local.md`](docs/assistente/validacao-voz-local.md).

Principais variáveis de voz (`VOICE_ENABLED=true` é o padrão nativo; no Compose é `false`):

| Variável | Padrão | Uso |
|---|---|---|
| `VOICE_MODEL_DIR` | `.models/assistant_voice` | Diretório privado dos modelos locais. |
| `VOICE_WHISPER_MODEL` | `small` | Modelo de transcrição faster-whisper. |
| `VOICE_WHISPER_DEVICE` / `VOICE_WHISPER_COMPUTE_TYPE` | `cpu` / `int8` | Execução CPU, sem pressupor GPU. |
| `VOICE_LANGUAGE` | `pt` | Idioma esperado para a fala. |
| `VOICE_PIPER_MODEL_PATH` | `pt_BR-faber-medium.onnx` | Arquivo de voz TTS. |
| `VOICE_MAX_UPLOAD_BYTES` / `VOICE_MAX_DURATION_SECONDS` | 8 MiB / 30 s | Limites de entrada conferidos durante upload e decodificação. |
| `VOICE_TRANSCRIPTION_TIMEOUT_SECONDS` / `VOICE_SYNTHESIS_TIMEOUT_SECONDS` | 60 s / 30 s | Limites de espera de STT/TTS. |
| `VOICE_SILENCE_MS` / `VOICE_IDLE_TIMEOUT_SECONDS` | 1800 ms / 120 s | Detecção do fim da fala e encerramento por inatividade. |

Após instalar as dependências de voz, baixe os modelos explicitamente no ambiente virtual:

```bash
.venv/bin/python scripts/download_assistant_voice_models.py
```

O teste automatizado local documentado executou áudio sintético através de faster-whisper, Ollama e Piper com dados fictícios e SQLite temporário. Isso não equivale a teste com voz humana no navegador: esse aceite, assim como medição no Ryzen/Windows e uso de voz dentro de Docker, permanece separado e deve ser consultado no relatório de validação antes de declarar esses ambientes prontos.

O teste real controlado do Ollama documentado cobre um caso específico de interpretação; não demonstra, sozinho, qualidade de conversa geral, cobertura de todos os pedidos ou velocidade em outro computador. Testes automatizados com provedor simulado validam regras e integração do backend, não o modelo real.

## O que não está implementado

- Integração com WhatsApp (incluindo WhatsApp Business Platform), calendário externo ou envio de respostas por e-mail.
- Envio automático de e-mail, alteração de mensagens, pagamento/baixa financeira automática ou emissão de nota fiscal.
- Autenticação/autorização efetiva para proteger as páginas e APIs. O cadastro de usuários é usado como dado de responsável, não como um sistema de login.
- Agenda com blocos de horário ou duração estimada; hoje é uma lista priorizada sem inventar horários.

## Tecnologias e componentes

- Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2 e Pydantic Settings.
- Jinja2, HTML/CSS/JavaScript do próprio projeto.
- PostgreSQL para execução com Docker Compose; SQLite é o padrão da execução nativa quando `DATABASE_URL` não é definido.
- `docxtpl`/`python-docx` para DOCX e LibreOffice headless para PDF; no launcher local da 8013, a imagem de conversão pode ser selecionada por `TECHNICAL_REPORT_PDF_CONVERTER_IMAGE` e executada localmente, sem rede. `pdfplumber` lê PDFs legados.
- Gemini API por padrão ou Ollama local alternativo para interpretação; faster-whisper e Piper locais são opcionais para voz.
- Yahoo IMAP opcional para leitura de e-mail.

## Requisitos

- Python 3.12.
- Para gerar PDF: LibreOffice instalado. No launcher local da 8013, a imagem local existente do projeto pode servir como conversor isolado, se disponível; para outra execução, configure `LIBREOFFICE_CMD` ou `TECHNICAL_REPORT_PDF_CONVERTER_IMAGE`. A conversão é limitada a 120 segundos e não usa serviços externos.
- Para o assistente: Gemini por padrão exige `GEMINI_API_KEY`, acesso à rede e modelo configurado em `GEMINI_MODEL`; alternativamente, Ollama em execução com modelo local em `OLLAMA_MODEL`.
- Para voz: dependências de `requirements-voice.txt` e arquivos de modelo STT/TTS locais. Consulte [`docs/assistente/execucao.md`](docs/assistente/execucao.md) e [`docs/assistente/validacao-voz-local.md`](docs/assistente/validacao-voz-local.md) para preparação e limites.
- Para usar PostgreSQL via Compose: Docker com Docker Compose.

## Execução nativa em macOS/Linux

Na raiz deste repositório:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Configure a chave em `.env.gemini.local` ou em um gerenciador de segredos local e use:

```bash
APP_ENV_FILE=.env.gemini.local APP_HOST=127.0.0.1 APP_PORT=8000 python run.py
```

Isso mantém o serviço na máquina local. Para rodar sem enviar conversas à nuvem, selecione `LLM_PROVIDER=ollama` e configure o endereço/modelo Ollama.

Acesse `http://127.0.0.1:8000/`. Verificação de saúde: `/healthz`; documentação interativa da API: `/docs`.

Para instalar as dependências Python opcionais de voz no ambiente virtual:

```bash
python -m pip install -r requirements-voice.txt
```

Os modelos de voz são arquivos locais separados das dependências. Não há um nome de modelo Ollama fixo: avalie tamanho, licença e recursos do computador de destino antes de baixar. Para configurar e validar o assistente local, siga os documentos em `docs/assistente/`.

### Configuração opcional do Yahoo

Por padrão, o provedor de e-mail e a sincronização ficam desativados. Para usar um arquivo de configuração privado fora do `.env` padrão:

1. Crie localmente `.env.yahoo.local` na raiz do repositório — o arquivo é ignorado pelo Git.
2. Preencha nele as variáveis de provedor e credenciais IMAP necessárias; nunca cole credenciais em comandos compartilhados, issues ou logs.
3. Inicie selecionando esse arquivo:

```bash
APP_ENV_FILE=.env.yahoo.local python run.py
```

Habilite a integração apenas quando realmente quiser iniciar consulta/sincronização. Consulte [`docs/assistente/desenho-email.md`](docs/assistente/desenho-email.md), [`docs/assistente/pendencias-revisaveis-email.md`](docs/assistente/pendencias-revisaveis-email.md) e [`docs/assistente/piloto-email-tarefas.md`](docs/assistente/piloto-email-tarefas.md). O modo deve permanecer somente leitura.

## Execução nativa no Windows

No PowerShell, na raiz do repositório:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:APP_HOST = "127.0.0.1"
$env:APP_PORT = "8000"
$env:APP_ENV_FILE = ".env.gemini.local"
$env:APP_HOST = "127.0.0.1"
$env:LLM_PROVIDER = "gemini"
$env:ASSISTANT_TIMEZONE = "America/Recife"
python run.py
```

O destino Windows não deve depender de GPU dedicada. Gemini requer rede e plano apropriado; alternativamente, o modelo Ollama, Whisper e Piper precisam ser escolhidos/testados nesse hardware. Veja [`docs/assistente/execucao.md`](docs/assistente/execucao.md).

## Execução com Docker Compose

O Compose fornece PostgreSQL 16 e a aplicação com LibreOffice. A porta do banco e a porta web são publicadas no loopback (`127.0.0.1`). Ajuste as variáveis de ambiente de acordo com `docker-compose.yml`; não use as credenciais padrão de desenvolvimento em operação com dados reais.

```bash
docker compose up --build -d
docker compose ps
```

Por padrão, acesse `http://127.0.0.1:8000/`; verifique `/healthz`. Para encerrar sem remover os dados:

```bash
docker compose down
```

Os dados do PostgreSQL ficam no volume `postgres_data`; arquivos gerados ficam em `output/` e o modelo de proposta em `doc_templates/`. **Não use `docker compose down -v` em um ambiente com dados a preservar:** isso remove o volume do banco.

No Docker, Gemini requer `GEMINI_API_KEY` entregue com segurança ao container. Para alternativa Ollama, `OLLAMA_BASE_URL` normalmente aponta para `http://host.docker.internal:11434`, pois o Ollama roda no host; não publique a porta do Ollama. STT/TTS exigem dependências e modelos acessíveis no processo/container; voz vem desativada por padrão no Compose.

## Rotas úteis

- `/` — Hoje
- `/web/board` — quadro de tarefas
- `/web/services` — chamados e serviços
- `/web/mensagens` — e-mails/mensagens e estado da sincronização
- `/web/assistente` — conversa por texto e, se configurada, voz
- `/web/proposals` — propostas
- `/web/clients` — clientes
- `/web/contas-a-pagar` e `/web/contas-a-receber` — financeiro
- `/web/users` — cadastro de responsáveis
- `/import-proposals` — importação assistida de propostas PDF
- `/healthz` e `/docs` — saúde e API

## Dados, privacidade e operação segura

- Antes de conectar banco com dados reais ou atualizar uma instalação, faça e verifique um backup e confirme `DATABASE_URL`, diretórios de arquivos e o endereço de bind.
- A execução nativa usa `propostas.db` SQLite por padrão. O Compose usa PostgreSQL; a URL pode ser substituída por configuração local.
- O startup cria tabelas ausentes e aplica verificações de compatibilidade previstas pelo código. Faça backup antes de atualizar um banco existente; não trate isso como substituto de um processo formal de migração/rollback.
- Não exponha `.env`, `.env.yahoo.local`, backups, `output/`, áudios, arquivos de modelo ou documentos com dados de clientes ao Git ou a serviços externos.
- O histórico de conversa e metadados necessários ao fluxo ficam no banco. O sistema não deve registrar áudio ou credenciais em logs; mensagens de e-mail são armazenadas como projeção mínima, sem corpo integral.
- O login protege as rotas e os downloads, mas não implementa papéis: todo usuário ativo autenticado tem acesso equivalente. Localhost restringe a interface de rede, mas não substitui autorização granular para computador compartilhado.

## Testes

Com o ambiente virtual ativo:

```bash
PYTHONPATH=. .venv/bin/pytest -q
node --test tests/js/*.test.mjs
```

No Windows, use `python -m pytest -q` no lugar do caminho Unix `.venv/bin/pytest`. Testes com provedor sintético não validam uma conta Yahoo real nem a qualidade do modelo Ollama; essas integrações precisam de validação local controlada, documentada separadamente.

## Documentação relacionada

- [`docs/assistente/`](docs/assistente/) — configuração, desenho e relatórios de validação do assistente, voz e e-mail.
- [`docs/assistente/especificacao-produto-evolucao.md`](docs/assistente/especificacao-produto-evolucao.md) — capacidades existentes e evolução planejada.
- [`docs/assistente/plano-evolucao.md`](docs/assistente/plano-evolucao.md) — fases futuras; plano não significa funcionalidade já implementada.
- [`docs/autenticacao.md`](docs/autenticacao.md) — login, CSRF, proteção de arquivos e bootstrap do administrador.
- `docs/superpowers/` — especificações e planos históricos de mudanças.
