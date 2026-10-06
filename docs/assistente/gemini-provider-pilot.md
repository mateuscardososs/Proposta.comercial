# Piloto opcional do provedor Gemini

## Estado e escopo

O assistente mantém Ollama como padrão. `LLM_PROVIDER=gemini` seleciona o adaptador remoto; não há fallback automático. A chamada é feita somente pelo FastAPI em HTTPS para a API Gemini. O adaptador recebe a declaração das ferramentas já autorizadas no aplicativo e devolve uma chamada estruturada, validada pelos mesmos contratos Pydantic e verificações de escopo/grounding usados no fluxo existente. Ele não recebe conexão ao banco nem acesso a shell ou arquivos. Confirmações antes de gravações permanecem obrigatórias. STT (faster-whisper) e TTS (Piper) não dependem do provedor de texto.

O modelo padrão configurável no piloto é `gemini-3.1-flash-lite`; em 6 de outubro de 2026 a documentação oficial o listava como opção estável. Confira [a lista de modelos](https://ai.google.dev/gemini-api/docs/models) e [a página oficial de preços e tratamento de dados](https://ai.google.dev/gemini-api/docs/pricing) antes de usar: disponibilidade, preço, quotas e termos mudam. Não interprete essa escolha como aprovação para enviar dados da AD Balanças.

## Chave e dados

A chave anteriormente colada na conversa está comprometida e não pode ser reutilizada. Revogue-a no console do provedor e crie uma chave nova em projeto/conta autorizado. O backend lê apenas a variável `GEMINI_API_KEY`, envia-a em cabeçalho TLS (`x-goog-api-key`) e não inclui seu valor em URL, telemetria, respostas ou logs. A falha de autenticação é reportada sem corpo bruto da API.

Para desenvolvimento local isolado, `.env.gemini.local` está explicitamente ignorado pelo Git. Crie-o copiando apenas o exemplo versionado ou criando um arquivo vazio, depois edite localmente com um editor; acrescente os valores sem colá-los em comandos, no histórico do shell ou em arquivos versionados:

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=<chave_nova_guardada_localmente>
GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_CONNECT_TIMEOUT=3
GEMINI_READ_TIMEOUT=60
```

O marcador acima é ilustrativo, não uma chave válida. `.env.example` mantém `GEMINI_API_KEY` vazio. Para iniciar uma cópia nativa isolada (depois de preencher localmente `.env.gemini.local`) e manter seu banco/documentos em diretório temporário exclusivo:

```bash
TEST_DIR="$(mktemp -d /tmp/ad-balancas-gemini.XXXXXX)"
APP_ENV_FILE=.env.gemini.local \\
DATABASE_URL="sqlite:///$TEST_DIR/assistant.db" \\
OUTPUT_DIR="$TEST_DIR/output" \\
APP_HOST=127.0.0.1 APP_PORT=8014 APP_RELOAD=false \\
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8014
```

Confirme que a porta está livre antes de iniciar. O exemplo cria diretório novo e usa somente banco/documentos sintéticos; não aponta para os serviços em uso. Para Docker Compose, o processo lê as variáveis do ambiente/arquivo local e injeta a chave no container; evite imprimir `docker compose config`, pois esse comando pode expandir valores. Use apenas pergunta sintética enquanto valida credenciais, conectividade e contrato.

Antes de usar conteúdo real, a empresa deve criar a chave nova, selecionar uma conta e um plano cujos termos e controles de dados sejam aprovados para conteúdo empresarial e decidir quais categorias podem ser enviadas. A documentação de preços atual distingue uso gratuito de pago no tratamento dos dados: no nível gratuito os dados podem ser utilizados para melhorar produtos, enquanto os termos do pago são diferentes. Confirme o texto e as condições vigentes diretamente na [documentação oficial](https://ai.google.dev/gemini-api/docs/pricing); não envie e-mails, dados financeiros, clientes ou documentos reais até essa aprovação. Uso da API pode gerar cobrança e está sujeito a quota/rate limit.

Consulte também [as práticas oficiais de segurança de chaves](https://ai.google.dev/gemini-api/docs/api-key). Não coloque uma chave em código, testes, documentação, `.env.example`, ticket ou commit. Rotacione/revogue imediatamente qualquer chave exposta.

## Seleção e retorno ao local

Com uma chave aprovada disponível apenas no ambiente local, selecione `LLM_PROVIDER=gemini` e reinicie somente o processo/instância de teste. O nome é configurado por `GEMINI_MODEL`; limites por `GEMINI_CONNECT_TIMEOUT` e `GEMINI_READ_TIMEOUT`. O identificador inicial é mantido em um único padrão `Settings`, não espalhado pela lógica.

Para retornar ao comportamento local, defina `LLM_PROVIDER=ollama` (ou remova a variável, pois Ollama é o padrão) e configure `OLLAMA_BASE_URL` e `OLLAMA_MODEL`. O adaptador Gemini não faz fallback se a chave estiver ausente, quota acabar ou API falhar.

## Testes

Os testes normais usam `httpx.MockTransport` e chaves sintéticas; não consomem API nem fazem chamadas externas. O teste real opcional `tests/test_assistant_gemini_live.py` só é executado se `RUN_GEMINI_SMOKE_TEST=1` e `GEMINI_API_KEY` estiver configurada. Ele envia somente uma pergunta sintética, sem contexto empresarial. Exemplo de opt-in (não inclua o valor da chave no comando):

```bash
RUN_GEMINI_SMOKE_TEST=1 .venv/bin/pytest -q tests/test_assistant_gemini_live.py
```

Se a condição não estiver cumprida, o teste é marcado como ignorado. O teste não valida qualidade em português para operações reais, adequação contratual da conta, nem tratamento de conteúdo de empresa.
