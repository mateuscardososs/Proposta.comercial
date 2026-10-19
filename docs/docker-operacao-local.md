# Operação local da aplicação em Docker

## Senha do PostgreSQL no Compose

O Compose não possui senha padrão: ele falha durante a validação se
`POSTGRES_PASSWORD` não estiver configurada. Para uma instalação nova, crie um
arquivo local ignorado pelo Git, por exemplo `.env.postgres.local`, e preencha-o
no editor com a senha privada definida para o PostgreSQL. Restrinja as
permissões do arquivo e não coloque o valor em comandos, histórico do shell ou
documentação versionada. Use `docker compose --env-file .env.postgres.local`
em todos os comandos Compose.

Esse arquivo separado não é montado no container da aplicação. Em uma instalação
existente, mantenha o valor já usado na inicialização do volume e a URL privada
de conexão correspondentes; apenas editar a variável não altera a senha de um
banco já inicializado. Não tente rotacionar a credencial como parte de uma
atualização comum. Se o valor atual não estiver disponível, pare antes de
iniciar ou recriar serviços e recupere-o pelo procedimento privado aprovado.
Esta validação ocorre na leitura da configuração e não inicia containers nem
conecta ao banco.

## Topologia

- A aplicação publica `127.0.0.1:8013` e escuta `8000` dentro do container.
- O Compose usa o projeto `propostacomercial`, o container PostgreSQL `propostas_db`
  e o volume existente `propostacomercial_postgres_data`; a troca da aplicação
  usa `--no-deps` para não iniciar, parar ou recriar o banco.
- A conexão privada do launcher, que aponta para `127.0.0.1:5433`, é lida do
  arquivo privado e redirecionada em memória ao serviço Compose `db:5432`.
- `OUTPUT_DIR` persiste em `../local-data/adbalancas-8013/output`. O template de
  proposta local é montado em `../local-data/adbalancas-8013/doc_templates`; o
  modelo técnico versionado é montado somente para leitura em `doc_templates/`.
- O cache local de faster-whisper e o modelo/configuração Piper são montados em
  `/app/.models/assistant_voice`. `HF_HUB_OFFLINE=1` evita baixar modelos no
  início. O container instala faster-whisper, Piper, Tesseract com `por`,
  PDFium/pypdfium2 e LibreOffice.
- O container roda com UID/GID locais não root para acessar os volumes. No
  macOS, informe os valores de `id -u` e `id -g` ao iniciar. Em Windows, ajuste
  esses IDs para o usuário configurado no Docker Desktop.
- `.env` e `.env.yahoo.local` são montados somente para leitura em runtime; ambos
  são excluídos do build context. O processo carrega seus valores sem imprimi-los.
  A chave de sessão e a URL privada PostgreSQL são montadas como Docker secrets;
  a senha do banco não é copiada para a imagem. O container força Gemini e mantém
  o `GEMINI_MODEL` configurado.
- As opções seguras de sincronização Yahoo são lidas do arquivo privado
  `settings.json`; usuário, senha de aplicativo e provedor vêm de
  `.env.yahoo.local`. O leitor continua somente leitura.

## Primeiro acesso

Não há credencial padrão. Antes da primeira subida, rode no terminal local:

```bash
cd /Users/mateuscardoso/dev/pai/Proposta.comercial
export ADBALANCAS_UID="$(id -u)"
export ADBALANCAS_GID="$(id -g)"
docker compose --env-file .env.postgres.local -p propostacomercial up -d db
docker compose --env-file .env.postgres.local -p propostacomercial run --rm --no-deps --build --entrypoint python app -m scripts.bootstrap_first_admin
```

O comando executa o bootstrap em um container descartável, usando o PostgreSQL
existente e os mesmos secrets/configurações montados para a aplicação. Ele pede
nome e e-mail e recebe a senha com entrada oculta; grava somente o hash Argon2id.
Não digite a senha em um argumento de comando, arquivo ou nesta conversa. O
bootstrap também valida o fluxo local de login antes de permitir iniciar a app.
Execute-o apenas uma vez, quando ainda não existir administrador ativo.

## Iniciar e parar

No macOS, no terminal local, após o administrador inicial estar provisionado:

```bash
cd /Users/mateuscardoso/dev/pai/Proposta.comercial
export ADBALANCAS_UID="$(id -u)"
export ADBALANCAS_GID="$(id -g)"
docker compose --env-file .env.postgres.local -p propostacomercial up -d --no-deps --build app
```

Esse comando substitui o container antigo `propostas_app` pela imagem atual,
mantendo o container e o volume do PostgreSQL fora da operação. Para iniciar
todo o stack gerenciado pelo Compose após o bootstrap, use:

```bash
docker compose --env-file .env.postgres.local -p propostacomercial up -d --build
```

A definição do banco continua usando o volume existente
`propostacomercial_postgres_data`; o hash da configuração atual do serviço `db`
foi comparado com o container existente e está inalterado.

O diretório de documentos gerados continua sendo `./output`, o mesmo bind mount
usado pelo container antigo; os arquivos já existentes permanecem disponíveis.
Templates, modelos de voz e configurações locais também continuam em mounts
persistentes/privados.

Para parar somente a aplicação:

```bash
docker compose --env-file .env.postgres.local -p propostacomercial stop app
```

URLs locais: `http://127.0.0.1:8013/login` e
`http://127.0.0.1:8013/healthz`.

## Efeitos de inicialização e limites

O startup atual confere autenticação, executa `create_all`, compatibilidade de
schema e backfill de rascunhos de e-mail. A comparação de schema deve ocorrer
antes da ativação; o backup validado está no diretório privado de backups local.
Se a sincronização estiver habilitada nas configurações privadas, o worker
registra a ativação e faz uma sincronização automática assim que o app inicia,
seguida do intervalo configurado. Não é chamada manual. O SMTP de campanhas não
é iniciado pelo worker.

O container Linux não oferece Apple Vision. A busca de PDFs digitalizados usa
Tesseract local em português (`por`) e PDFium quando o executável, os dados de
idioma e o renderizador estão disponíveis; sem eles, o documento é reportado
como não pesquisável/parcial, sem instalação automática. O caminho Apple Vision
nativo do macOS permanece fora do container. A voz usa CPU, cache local existente, faster-whisper
e Piper; a imagem não baixa os modelos automaticamente.

O health check e a disponibilidade de pacotes/modelos não comprovam o login,
uma chamada Gemini, transcrição de áudio, síntese, OCR de um documento ou a
revisão visual da interface. Registre esses resultados separadamente após o
administrador completar o primeiro acesso.
