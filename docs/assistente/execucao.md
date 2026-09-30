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
| `ASSISTANT_TIMEZONE` | `America/Recife` | Base para hoje, amanha e demais datas relativas. |
| `ASSISTANT_CONTEXT_MESSAGES` | `12` | Quantidade maxima de mensagens recentes enviada ao interpretador. |
| `ASSISTANT_REQUEST_LEASE_SECONDS` | `120` | Expiracao de requisicoes interrompidas antes de permitir retomada segura. |

Nao ha fallback para API paga ou servico externo.

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
export ASSISTANT_TIMEZONE=America/Recife
export ASSISTANT_REQUEST_LEASE_SECONDS=120
.venv/bin/python run.py
```

7. Abra `http://127.0.0.1:8000/web/assistente`.

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
$env:ASSISTANT_TIMEZONE = "America/Recife"
$env:ASSISTANT_REQUEST_LEASE_SECONDS = "120"
python run.py
```

O timeout maior e apenas um ponto inicial para a CPU do destino; deve ser reduzido ou aumentado com base em medicao real. Mantenha um unico modelo carregado e uma solicitacao de interpretacao por vez.

## Docker Desktop no Mac ou Windows

O Compose mantem FastAPI, PostgreSQL e LibreOffice em containers e espera o Ollama nativo no host:

```powershell
$env:OLLAMA_MODEL = "qwen3:4b-instruct-2507-q4_K_M"
docker compose up --build
```

Dentro do container, `OLLAMA_BASE_URL` assume `http://host.docker.internal:11434`. Essa rota ainda nao foi validada nesta etapa: o Ollama testado esta preso ao loopback do host, e o bridge do Docker Desktop pode nao alcanca-lo. Nao altere o Ollama para escutar em todas as interfaces sem uma avaliacao de firewall e autenticacao; execute o FastAPI nativamente ate definir uma configuracao Docker segura.

O Compose publica a aplicacao em `http://127.0.0.1:8000`. Alterar esse bind para `0.0.0.0` e bloqueado operacionalmente enquanto nao houver autenticacao.

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

## Diagnostico

- **Ollama indisponivel:** confirme que ele esta iniciado e que `OLLAMA_BASE_URL` aponta para o host local correto.
- **Modelo indisponivel:** compare `OLLAMA_MODEL` com `ollama list`.
- **Timeout:** teste o mesmo comando diretamente no Windows e use um modelo menor antes de aumentar indefinidamente o timeout.
- **Resposta invalida:** o backend rejeita a estrutura e nao executa nenhuma acao. Reformule a frase e registre o caso para a avaliacao do modelo.
- **Confirmacao sem resposta:** repita a confirmacao. O identificador da acao reconcilia uma tarefa ja gravada e evita duplicacao.
- **Requisicao presa em processamento:** aguarde a expiracao configurada por `ASSISTANT_REQUEST_LEASE_SECONDS` e repita com o mesmo `request_id`; uma resposta ja persistida e devolvida sem nova gravacao.
