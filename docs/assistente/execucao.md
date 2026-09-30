# Execucao do assistente local

## Limite de seguranca

O sistema atual nao possui login ou autorizacao efetiva. Por isso:

- o servidor nativo usa `127.0.0.1` por padrao;
- o Compose publica `127.0.0.1:8000`, nao todas as interfaces;
- o backend aceita como Ollama apenas `localhost`, enderecos de loopback ou `host.docker.internal`;
- o navegador chama somente o FastAPI; nunca chama o Ollama diretamente;
- esta versao nao deve ser publicada na internet nem exposta na rede da empresa.

As conversas, os comandos normalizados e as acoes ficam nas tabelas `assistant_conversations`, `assistant_messages` e `assistant_actions`. O sistema nao persiste raciocinio interno do modelo nem configuracoes do Ollama. Nao digite senhas, tokens ou outros segredos na conversa.

## Variaveis

| Variavel | Padrao nativo | Uso |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | API HTTP local do Ollama. |
| `OLLAMA_MODEL` | vazio | Nome exato de um modelo ja instalado. Obrigatorio para interpretar mensagens. |
| `OLLAMA_CONNECT_TIMEOUT` | `3` | Segundos para conectar. |
| `OLLAMA_READ_TIMEOUT` | `60` | Segundos para aguardar a interpretacao. |
| `ASSISTANT_TIMEZONE` | `America/Recife` | Base para hoje, amanha e demais datas relativas. |
| `ASSISTANT_CONTEXT_MESSAGES` | `12` | Quantidade maxima de mensagens recentes enviada ao interpretador. |

Nao ha fallback para API paga ou servico externo.

## Mac de desenvolvimento

1. Instale o Ollama pelo instalador oficial e inicie a aplicacao.
2. Antes de baixar um modelo, confira o tamanho publicado e a memoria livre. O Mac inspecionado tem 16 GB; nao use o desempenho dele como criterio unico para a instalacao Windows.
3. Escolha um modelo `instruct` com saida estruturada. Comece avaliando a faixa de 3–4B quantizada.
4. Somente depois de verificar tamanho e recursos, instale o modelo escolhido:

```bash
ollama pull <modelo-escolhido>
```

5. Configure e inicie a aplicacao:

```bash
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_MODEL='<modelo-escolhido>'
export OLLAMA_CONNECT_TIMEOUT=3
export OLLAMA_READ_TIMEOUT=60
export ASSISTANT_TIMEZONE=America/Recife
python3 run.py
```

6. Abra `http://127.0.0.1:8000/web/assistente`.

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
python run.py
```

O timeout maior e apenas um ponto inicial para a CPU do destino; deve ser reduzido ou aumentado com base em medicao real. Mantenha um unico modelo carregado e uma solicitacao de interpretacao por vez.

## Docker Desktop no Mac ou Windows

O Compose mantem FastAPI, PostgreSQL e LibreOffice em containers e espera o Ollama nativo no host:

```powershell
$env:OLLAMA_MODEL = "<modelo-escolhido>"
docker compose up --build
```

Dentro do container, `OLLAMA_BASE_URL` assume `http://host.docker.internal:11434`. Valide a conectividade no equipamento de destino. Nao altere o Ollama para escutar em todas as interfaces sem uma avaliacao de firewall e autenticacao; se o bridge do Docker Desktop nao alcancar o Ollama local, execute o FastAPI nativamente ate definir uma configuracao segura.

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
python -m pytest -q
```

Os testes normais usam provedor simulado ou transporte HTTP simulado. Eles validam contratos, regras e integracao da aplicacao, mas nao comprovam a qualidade de um modelo real.

Teste real controlado, somente quando Ollama e o modelo ja estiverem instalados:

```bash
RUN_OLLAMA_INTEGRATION=1 \
OLLAMA_MODEL='<modelo-instalado>' \
python -m pytest tests/test_assistant_ollama_live.py -q
```

Esse teste apenas pede a classificacao de uma consulta de tarefas; nao grava dados.

## Diagnostico

- **Ollama indisponivel:** confirme que ele esta iniciado e que `OLLAMA_BASE_URL` aponta para o host local correto.
- **Modelo indisponivel:** compare `OLLAMA_MODEL` com `ollama list`.
- **Timeout:** teste o mesmo comando diretamente no Windows e use um modelo menor antes de aumentar indefinidamente o timeout.
- **Resposta invalida:** o backend rejeita a estrutura e nao executa nenhuma acao. Reformule a frase e registre o caso para a avaliacao do modelo.
- **Confirmacao sem resposta:** repita a confirmacao. O identificador da acao reconcilia uma tarefa ja gravada e evita duplicacao.
