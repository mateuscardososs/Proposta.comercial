# Execucao do assistente local

## Limite de seguranca

O sistema atual nao possui login ou autorizacao efetiva. Por isso:

- o servidor nativo usa `127.0.0.1` por padrao;
- o Compose publica `127.0.0.1:8000`, nao todas as interfaces;
- o backend aceita como Ollama apenas `localhost`, enderecos de loopback ou `host.docker.internal`;
- o navegador chama somente o FastAPI; nunca chama o Ollama diretamente;
- esta versao nao deve ser publicada na internet nem exposta na rede da empresa.

As conversas, requisicoes, comandos normalizados e acoes ficam nas tabelas `assistant_conversations`, `assistant_requests`, `assistant_messages` e `assistant_actions`. O sistema nao persiste raciocinio interno do modelo nem configuracoes do Ollama. Nao digite senhas, tokens ou outros segredos na conversa.

## Variaveis

| Variavel | Padrao nativo | Uso |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | API HTTP local do Ollama. |
| `OLLAMA_MODEL` | vazio | Nome exato de um modelo ja instalado. Obrigatorio para interpretar mensagens. |
| `OLLAMA_CONNECT_TIMEOUT` | `3` | Segundos para conectar. |
| `OLLAMA_READ_TIMEOUT` | `60` | Segundos para aguardar a interpretacao. |
| `OLLAMA_MAX_OUTPUT_TOKENS` | `180` | Limite de geracao por inferencia; reduz respostas excessivas sem alterar as validacoes. |
| `ASSISTANT_TIMEZONE` | `America/Recife` | Base para hoje, amanha e demais datas relativas. |
| `ASSISTANT_CONTEXT_MESSAGES` | `12` | Quantidade maxima de mensagens recentes enviada ao interpretador. |
| `ASSISTANT_REQUEST_LEASE_SECONDS` | `120` | Expiracao de requisicoes interrompidas antes de permitir retomada segura. |
| `ASSISTANT_MAX_TOOL_ROUNDS` | `2` | Maximo de consultas reais distintas antes da resposta final. |

Nao ha fallback para API paga ou servico externo.

## Voz local opcional

A voz roda dentro do FastAPI por adaptadores substituiveis: faster-whisper converte
audio em texto e Piper converte a resposta textual em WAV. O texto continua
funcionando quando a voz esta desativada ou indisponivel. Audio bruto e gravado apenas
em arquivo temporario, validado durante a decodificacao e removido ao terminar.

Instale as dependencias somente na `.venv`:

```bash
.venv/bin/python -m pip install -r requirements-voice.txt
.venv/bin/python scripts/download_assistant_voice_models.py
```

O download instala apenas `Systran/faster-whisper-small` e
`pt_BR-faber-medium` em `.models/assistant_voice` (ignorado pelo Git), verifica o
hash da voz e aplica limite total de 2 GB. O startup nunca baixa modelos.

| Variavel | Padrao | Uso |
|---|---|---|
| `VOICE_ENABLED` | `true` nativo / `false` Compose | Habilita endpoints de voz sem afetar texto. |
| `VOICE_MODEL_DIR` | `.models/assistant_voice` | Cache local do Whisper. |
| `VOICE_WHISPER_MODEL` | `small` | Nome configuravel do modelo STT. |
| `VOICE_WHISPER_DEVICE` | `cpu` | Nao presume GPU. |
| `VOICE_WHISPER_COMPUTE_TYPE` | `int8` | Quantizacao CPU. |
| `VOICE_PIPER_MODEL_PATH` | arquivo Faber medium | Voz pt-BR configuravel. |
| `VOICE_PIPER_NOISE_SCALE` / `VOICE_PIPER_NOISE_W_SCALE` | omitidas | Controles do Piper; o runner usa `0` somente para audio sintetico reproduzivel. |
| `VOICE_MAX_UPLOAD_BYTES` | `8388608` | Limite contado durante o upload. |
| `VOICE_MAX_DURATION_SECONDS` | `30` | Limite conferido durante a decodificacao. |
| `VOICE_TRANSCRIPTION_TIMEOUT_SECONDS` | `60` | Espera maxima pelo STT. |
| `VOICE_SYNTHESIS_TIMEOUT_SECONDS` | `30` | Espera maxima pelo TTS. |
| `VOICE_SILENCE_MS` | `1800` | Silencio que encerra uma fala no navegador; valor mais tolerante a pausas naturais. |
| `VOICE_IDLE_TIMEOUT_SECONDS` | `120` | Libera microfone sem fala. |

Ha um worker e no maximo uma espera pendente por STT e por TTS. O terceiro trabalho
e rejeitado; timeout de uma requisicao nao libera o worker enquanto a biblioteca
nativa ainda estiver executando.

## Mac de desenvolvimento

1. Instale o Ollama nativo. Neste Mac foi usado `brew install --cask ollama-app`.
2. Antes de baixar um modelo, confira o tamanho publicado e a memoria livre. O Mac inspecionado tem 16 GB; nao use o desempenho dele como criterio unico para a instalacao Windows.
3. O modelo inicial validado e `qwen3:4b-instruct-2507-q4_K_M`: 4B, quantizacao Q4_K_M, download de 2,5 GB e licenca Apache 2.0.
4. Instale somente esse modelo inicial:

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

5. Para reproduzir a configuracao validada sem nuvem e sem bind externo, encerre a aplicacao grafica do Ollama se ela estiver servindo e inicie o servidor em um terminal:

```bash
OLLAMA_NO_CLOUD=1 \
OLLAMA_HOST=127.0.0.1:11434 \
OLLAMA_NUM_PARALLEL=1 \
OLLAMA_MAX_LOADED_MODELS=1 \
OLLAMA_CONTEXT_LENGTH=4096 \
ollama serve
```

6. Configure e inicie a aplicacao em outro terminal:

```bash
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M
export OLLAMA_CONNECT_TIMEOUT=3
export OLLAMA_READ_TIMEOUT=60
export OLLAMA_MAX_OUTPUT_TOKENS=180
export ASSISTANT_TIMEZONE=America/Recife
export ASSISTANT_REQUEST_LEASE_SECONDS=120
export VOICE_ENABLED=true
.venv/bin/python run.py
```

7. Abra `http://127.0.0.1:8000/web/assistente`.

Para uma instalacao nova completa no Mac:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-voice.txt
.venv/bin/python scripts/download_assistant_voice_models.py
```

Sem `OLLAMA_MODEL`, com Ollama parado ou com nome inexistente, a pagina continua abrindo e mostra um aviso claro ao enviar uma mensagem. Nenhuma tarefa e alterada.

## Windows de destino

O Ryzen 7 3700U deve ser tratado como CPU-only, mesmo que exista grafico integrado. O modelo deve ser escolhido pela latencia medida nessa maquina.

1. Instale o Ollama nativo para Windows 10 ou posterior.
2. Verifique tamanho do modelo e espaco no SSD antes do download. Se necessario, configure `OLLAMA_MODELS` para outro diretorio antes de iniciar o Ollama.
3. No PowerShell, para executar FastAPI nativamente:

```powershell
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "<modelo-escolhido>"
$env:OLLAMA_CONNECT_TIMEOUT = "3"
$env:OLLAMA_READ_TIMEOUT = "90"
$env:OLLAMA_MAX_OUTPUT_TOKENS = "180"
$env:ASSISTANT_TIMEZONE = "America/Recife"
$env:ASSISTANT_REQUEST_LEASE_SECONDS = "120"
$env:VOICE_ENABLED = "true"
.venv\Scripts\python.exe run.py
```

Preparacao equivalente no Windows x64:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-voice.txt
.venv\Scripts\python.exe scripts\download_assistant_voice_models.py
```

Os pacotes selecionados publicam wheels para macOS arm64 e Windows amd64. O Windows
continua configurado como CPU/INT8; nao presuma aceleracao pela GPU integrada. Meca
latencia e qualidade no Ryzen antes de uso operacional.

O timeout maior e apenas um ponto inicial para a CPU do destino; deve ser reduzido ou aumentado com base em medicao real. Mantenha um unico modelo carregado e uma solicitacao de interpretacao por vez.

## Docker Desktop no Mac ou Windows

O Compose mantem FastAPI, PostgreSQL e LibreOffice em containers e espera o Ollama nativo no host:

```powershell
$env:OLLAMA_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
docker compose up --build
```

Dentro do container, `OLLAMA_BASE_URL` assume `http://host.docker.internal:11434`. Essa rota ainda nao foi validada nesta etapa: o Ollama testado esta preso ao loopback do host, e o bridge do Docker Desktop pode nao alcanca-lo. Nao altere o Ollama para escutar em todas as interfaces sem uma avaliacao de firewall e autenticacao; execute o FastAPI nativamente ate definir uma configuracao Docker segura.

O Compose publica a aplicacao em `http://127.0.0.1:8000`. Alterar esse bind para `0.0.0.0` e bloqueado operacionalmente enquanto nao houver autenticacao.

A imagem Docker atual instala somente `requirements.txt` e deixa `VOICE_ENABLED=false`.
Para voz em container sera necessario instalar `requirements-voice.txt` na imagem e
montar `.models/assistant_voice` como volume somente leitura. Essa variante nao foi
validada. No Mac e no Windows, use FastAPI, Ollama e voz nativamente por enquanto.

## Banco e compatibilidade

As novas estruturas sao tabelas independentes. O startup existente executa `Base.metadata.create_all()`, que cria essas tabelas sem reescrever as tabelas operacionais. Nao houve alteracao de coluna em `tasks`, `clients`, `users`, `proposals` ou `lancamentos`.

Antes de instalar em dados reais:

1. faca backup do banco;
2. execute a suite em banco isolado;
3. suba uma copia de homologacao;
4. confirme criacao, repeticao da confirmacao e reinicio;
5. somente entao atualize a instalacao real.

## Testes

Suite completa, sempre fora do banco real:

```bash
.venv/bin/python -m pytest -q
```

Os testes normais usam provedor simulado ou transporte HTTP simulado. Eles validam contratos, regras e integracao da aplicacao, mas nao comprovam a qualidade de um modelo real.

Teste real controlado, somente quando Ollama e o modelo ja estiverem instalados:

```bash
RUN_OLLAMA_INTEGRATION=1 \
OLLAMA_MODEL='<modelo-instalado>' \
.venv/bin/python -m pytest tests/test_assistant_ollama_live.py -q
```

Esse teste apenas pede a classificacao de uma consulta de tarefas; nao grava dados.

Validacao real completa de voz, sempre com SQLite e arquivos temporarios:

```bash
.venv/bin/python scripts/validate_assistant_voice_local.py \
  --output /tmp/assistente-voz-validacao.json
```

Ela usa Piper, faster-whisper e Ollama reais, mas audio sintetico e dados ficticios.
Veja `docs/assistente/validacao-voz-local.md` para resultados e roteiro humano.

## Diagnostico

- **Ollama indisponivel:** confirme que ele esta iniciado e que `OLLAMA_BASE_URL` aponta para o host local correto.
- **Modelo indisponivel:** compare `OLLAMA_MODEL` com `ollama list`.
- **Timeout:** teste o mesmo comando diretamente no Windows e use um modelo menor antes de aumentar indefinidamente o timeout.
- **Resposta invalida:** o backend rejeita a estrutura e nao executa nenhuma acao. Reformule a frase e registre o caso para a avaliacao do modelo.
- **Confirmacao sem resposta:** repita a confirmacao. O identificador da acao reconcilia uma tarefa ja gravada e evita duplicacao.
- **Requisicao presa em processamento:** aguarde a expiracao configurada por `ASSISTANT_REQUEST_LEASE_SECONDS` e repita com o mesmo `request_id`; uma resposta ja persistida e devolvida sem nova gravacao.

## Instancia isolada de teste na porta 8011

A correcao conversacional foi deixada rodando somente em `127.0.0.1:8011`, com
banco e arquivos sinteticos. A aplicacao Docker antiga da porta 8000 permanece
separada. Para reproduzir exatamente a instancia de teste no Mac:

```bash
export APP_HOST=127.0.0.1
export APP_PORT=8011
export APP_RELOAD=false
export DATABASE_URL=sqlite:////tmp/ad-balancas-voice-manual.VnwzuO/manual-ready.sqlite3
export OUTPUT_DIR=/tmp/ad-balancas-voice-manual.VnwzuO/output-ready
export TEMPLATE_DOC_PATH=/tmp/ad-balancas-voice-manual.VnwzuO/doc_templates/proposta_template.docx
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M
export OLLAMA_CONNECT_TIMEOUT=3
export OLLAMA_READ_TIMEOUT=90
export ASSISTANT_TIMEZONE=America/Recife
export ASSISTANT_REQUEST_LEASE_SECONDS=30
export ASSISTANT_MAX_TOOL_ROUNDS=2
export VOICE_ENABLED=true
export VOICE_MODEL_DIR="$PWD/.models/assistant_voice"
export VOICE_WHISPER_MODEL=small
export VOICE_WHISPER_DEVICE=cpu
export VOICE_WHISPER_COMPUTE_TYPE=int8
export VOICE_LANGUAGE=pt
export VOICE_PIPER_MODEL_PATH="$PWD/.models/assistant_voice/pt_BR-faber-medium.onnx"
export VOICE_SILENCE_MS=1800
.venv/bin/python run.py
```

Abra `http://127.0.0.1:8011/web/assistente`. Depois de atualizar o codigo, use
`Cmd+Shift+R` no Mac ou `Ctrl+F5` no Windows para ignorar scripts em cache.

## Leitura local de e-mail

O padrão é `EMAIL_PROVIDER=disabled`. A demonstração isolada usa:

```bash
EMAIL_PROVIDER=synthetic
EMAIL_MAX_MESSAGES=30
EMAIL_CACHE_RETENTION_DAYS=14
EMAIL_BODY_PREVIEW_CHARS=4000
```

### Arquivo local da instância Yahoo na porta 8011

A instância isolada usa `.env.yahoo.local`, ignorado pelo Git e com permissão somente para o usuário
local. Preencha nesse arquivo apenas `EMAIL_IMAP_USERNAME` e `EMAIL_IMAP_APP_PASSWORD`. O provedor
já está definido como `imap_yahoo`. Não copie esses valores para `.env`, comandos, tickets ou logs.

Depois do preenchimento, inicie exclusivamente essa instância com:

```bash
./scripts/run_assistant_8011_yahoo.sh
```

O inicializador usa `APP_ENV_FILE` para o Pydantic ler o arquivo dentro do processo Python, sem
interpolar credenciais na linha de comando. Para a validação de serviços, mantém o banco e os
documentos separados em `/tmp/ad-balancas-services-8011`, escuta somente em `127.0.0.1:8011` e recusa
iniciar se os dois campos estiverem vazios. O banco anterior em
`/tmp/ad-balancas-conversational.xFP65K` não é removido nem reutilizado.

Para carregar somente registros sintéticos nesse novo banco, use explicitamente:

```bash
DATABASE_URL=sqlite:////tmp/ad-balancas-services-8011/app.sqlite3 \
SERVICE_VALIDATION_ALLOW_SYNTHETIC_SEED=1 PYTHONPATH=. \
.venv/bin/python scripts/seed_assistant_service_validation.py
```

O script rejeita qualquer outro caminho ou banco que não seja SQLite. A carga não acessa a caixa
Yahoo. Ela cria clientes com nomes parecidos, o responsável `Carlos Teste Sintético`, chamados e
tarefas identificados como sintéticos. A integração Yahoo continua configurada como somente leitura;
não foi consultada durante a validação do fluxo de serviços.

Para conectar o Yahoo posteriormente, use variáveis locais fora do Git:

```bash
EMAIL_PROVIDER=imap_yahoo
EMAIL_IMAP_HOST=imap.mail.yahoo.com
EMAIL_IMAP_PORT=993
EMAIL_IMAP_USERNAME='endereco-completo-da-conta'
EMAIL_IMAP_APP_PASSWORD='senha-de-aplicativo-gerada-no-Yahoo'
EMAIL_IMAP_TIMEOUT_SECONDS=10
EMAIL_MAX_MESSAGES=30
EMAIL_CACHE_RETENTION_DAYS=14
EMAIL_BODY_PREVIEW_CHARS=4000
```

Não use a senha comum da conta. A documentação atual do Yahoo indica senha de aplicativo para esse
tipo de cliente IMAP: [configuração IMAP](https://ca.help.yahoo.com/kb/SLN4075.html) e
[senha para aplicativo](https://help.yahoo.com/kb/SLN15241.html).

O adaptador abre `imap.mail.yahoo.com:993` com SSL, seleciona pastas em modo somente leitura e usa
`BODY.PEEK` apenas para cabeçalhos e uma seção textual limitada. Não há SMTP, abertura de links,
alteração de flags ou download deliberado de anexos. Entrada e Enviados são descobertas primeiro
pelos atributos especiais do servidor; nomes localizados são apenas fallback.

### Instância isolada de validação de serviços

Ollama estritamente local:

```bash
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=true ollama serve
```

Aplicação de teste (após verificar que o Ollama já está ativo e carregar os dados sintéticos):

```bash
cd /Users/mateuscardoso/dev/pai/Proposta.comercial
./scripts/run_assistant_8011_yahoo.sh
```

O inicializador seleciona a configuração Yahoo local sem imprimir os valores e usa:

```text
DATABASE_URL=sqlite:////tmp/ad-balancas-services-8011/app.sqlite3
OUTPUT_DIR=/tmp/ad-balancas-services-8011/output
TEMPLATE_DOC_PATH=/tmp/ad-balancas-services-8011/doc_templates/proposta_template.docx
APP_HOST=127.0.0.1 APP_PORT=8011 APP_RELOAD=false \
OLLAMA_BASE_URL=http://127.0.0.1:11434 \
OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M \
ASSISTANT_TIMEZONE=America/Recife
```

O script também mantém a voz local habilitada com os modelos já baixados.

Abra `http://127.0.0.1:8011/web/assistente`. A porta 8000 pertence à aplicação antiga e não faz
parte desta instância.

### Persistência e retenção

O histórico persiste a resposta apresentada e, por `EMAIL_CACHE_RETENTION_DAYS`, remetente, assunto,
data, flag de leitura, resumo limitado, classificação, referência opaca e limitações. Após a retenção,
os itens estruturados e as mensagens dentro do resultado da ferramenta são removidos; o texto da
conversa permanece. Não há cache separado nesta primeira versão: as consultas IMAP são delimitadas
por período e quantidade, então a caixa inteira não é relida nem enviada ao modelo. Credenciais nunca
são persistidas no banco, histórico ou telemetria.

### Roteiro posterior para a conta real

1. Gerar no Yahoo uma senha exclusiva para este aplicativo.
2. Guardar endereço completo e senha de aplicativo no `.env` local ou gerenciador de segredos.
3. Iniciar uma instância isolada com `EMAIL_PROVIDER=imap_yahoo` e banco temporário.
4. Conferir `/api/assistant/capabilities` antes da primeira consulta.
5. Consultar um período curto e comparar referências, datas e flags com o Outlook/Yahoo.
6. Verificar se o servidor expõe uma pasta com atributo `\\Sent`; sem ela, respostas pendentes
   continuam marcadas como inconclusivas.
7. Confirmar no Yahoo/Outlook que nenhuma mensagem mudou para lida.

Esse roteiro ainda não foi executado com a conta da empresa.

### Produção local da instância 8013 (estado em 03/10/2026)

A 8013 foi transferida do container de voz desativada para o processo nativo no Mac, usando o
ambiente virtual e os componentes locais já instalados. Consulte
[validacao-instancia-8013-voz.md](validacao-instancia-8013-voz.md) para causa, evidências e o
limite de validação manual.

Inicialização:

```bash
cd /Users/mateuscardoso/dev/pai/Proposta.comercial
PYTHONPATH=. .venv/bin/python scripts/run_assistant_8013_local.py
```

Tela: `http://127.0.0.1:8013/web/assistente`. Encerre com `Ctrl+C` no terminal do processo.
O iniciador restringe a aplicação ao loopback e valida Ollama/modelo, dependências/modelos de voz,
configurações Yahoo preservadas e banco `propostas_db`. A configuração de conexão fica fora do Git
em `../local-data/adbalancas-8013/private/`, com permissão `0600`; não a copie para `.env` nem a
imprima. A senha Yahoo continua exclusivamente no `.env.yahoo.local` ignorado pelo Git.

O serviço Compose de PostgreSQL mantém o mesmo volume, mas publica a porta em
`127.0.0.1:5433`; a 5432 do host estava ocupada por outro PostgreSQL local e não foi alterada.
Não inicie o container antigo `adbalancas-app-8013` enquanto o processo nativo estiver usando a
porta 8013.

O resumo operacional diário do Assistente consulta tarefas, agenda, serviços, cache de e-mail e
financeiro em modo somente leitura, com status independente para cada fonte. Comportamento,
privacidade, estados de fonte e testes estão em
[resumo-operacional-diario.md](resumo-operacional-diario.md).

A busca documental do Assistente consulta somente PDF/DOCX vinculados a propostas dentro de `OUTPUT_DIR`,
com respostas extrativas citando arquivo e página/seção. O conteúdo não é enviado ao provedor de IA nem
tratado como instrução. Escopo, limites do importador legado e validação estão em
[busca-documentos.md](busca-documentos.md).
