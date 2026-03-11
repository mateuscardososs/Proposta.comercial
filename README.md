# Propostas Comerciais - AD Balancas e Engenharia

Sistema interno para gerar propostas comerciais com historico em banco, emissao de DOCX via `docxtpl` e conversao para PDF via LibreOffice headless.

## O que o sistema faz

- Cadastro de clientes
- Cadastro de usuarios/responsaveis
- Criacao de propostas com itens dinamicos
- Campos financeiros da proposta:
  - condicao de pagamento (dias)
  - imposto percentual
- Cronograma dinamico por proposta
- Consulta de propostas recentes por cliente
- Clonagem de proposta
- Importacao em lote de propostas PDF legadas (preview + confirmacao)
- Geracao de:
  - DOCX (`docxtpl`)
  - PDF (LibreOffice headless)

## Stack

- Python 3.12
- FastAPI
- SQLAlchemy
- Pydantic Settings
- Jinja2
- docxtpl
- pdfplumber
- PostgreSQL (Docker)
- LibreOffice headless (Docker)

## Estrutura principal

```text
propostas_app/
  app/
  doc_templates/
    proposta_template.docx
  output/
  docker/
    entrypoint.sh
    wait_for_db.py
  Dockerfile
  docker-compose.yml
  .env.example
  requirements.txt
  run.py
```

## Configuracao por ambiente

A aplicacao le variaveis via `.env` (Pydantic Settings).

Variaveis principais:

- `DATABASE_URL`
- `LIBREOFFICE_CMD`
- `TEMPLATE_DOC_PATH`
- `OUTPUT_DIR`
- `APP_HOST`
- `APP_PORT`
- `APP_RELOAD`
- `DB_WAIT_TIMEOUT`
- `DB_WAIT_INTERVAL`

Copie `.env.example` para `.env` e ajuste se necessario.

## Rodando localmente sem Docker

1. Criar e ativar venv

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Instalar dependencias

```powershell
pip install -r requirements.txt
```

3. Executar

```powershell
python run.py
```

Aplicacao:

- Web: `http://127.0.0.1:8000/`
- Docs: `http://127.0.0.1:8000/docs`

## Docker (recomendado para desenvolvimento)

### 1. Preparar ambiente

No diretorio `propostas_app`, copie:

```powershell
Copy-Item .env.example .env
```

### 2. Subir stack completa

```powershell
docker compose up --build
```

Servicos:

- `app`: FastAPI + LibreOffice (conversao PDF no servidor)
- `db`: PostgreSQL

### 3. Acessar sistema

- Web: `http://localhost:8000/`
- Docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/healthz`

### 4. Parar stack

```powershell
docker compose down
```

Para remover volume do banco:

```powershell
docker compose down -v
```

## Persistencia de dados e arquivos

- Banco PostgreSQL: volume Docker `postgres_data`
- Arquivos gerados DOCX/PDF: bind mount `./output -> /app/output`
- Template DOCX: bind mount `./doc_templates -> /app/doc_templates`

Assim os arquivos permanecem apos reiniciar containers.

## LibreOffice no container

- O container instala LibreOffice via apt
- Comando padrao no Linux container: `/usr/bin/soffice`
- A app usa `LIBREOFFICE_CMD` quando definido
- Fallback de execucao tenta:
  1. valor de `LIBREOFFICE_CMD`
  2. `/usr/bin/soffice`
  3. `soffice`

Erro claro quando indisponivel:

- `"LibreOffice command not found. Tried: ... Install LibreOffice or set LIBREOFFICE_CMD."`

## Banco de dados e startup

- Compose usa PostgreSQL (`postgres:16-alpine`)
- `db` possui `healthcheck` com `pg_isready`
- `app` depende de `db` saudavel (`depends_on` com `condition: service_healthy`)
- `docker/wait_for_db.py` aguarda conectividade antes de iniciar FastAPI
- A criacao automatica de tabelas no startup foi mantida

## Fluxo funcional preservado

O comportamento existente foi mantido:

- criacao de proposta
- persistencia de itens e cronograma
- clonagem
- endpoint de propostas recentes
- geracao DOCX
- tentativa de geracao PDF com aviso em caso de falha

## Importacao de PDFs legados

- Pagina web: `/import-proposals`
- Endpoint API: `POST /api/import-proposals`
- Upload multiplo de arquivos PDF
- Modo preview (`confirm=false`) para revisar dados extraidos
- Modo confirmacao (`confirm=true`) para persistir propostas, itens e cronograma
- Cliente e vinculado por nome (case-insensitive); quando nao existir, e criado
- Propostas importadas entram no historico normal e no endpoint de recentes por cliente

## Troubleshooting

- App nao sobe e log mostra erro de conexao no banco:
  - verifique `DATABASE_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
  - confira se `db` esta healthy: `docker compose ps`

- PDF nao gera:
  - confira `LIBREOFFICE_CMD` no container (`/usr/bin/soffice`)
  - veja logs da app: `docker compose logs app`

- Arquivos gerados nao aparecem:
  - confirme volume `./output` e permissao de escrita

- Alterou o template e nao refletiu:
  - confirme `./doc_templates/proposta_template.docx`
  - o mount no compose aponta para `/app/doc_templates`

## Estrategia futura para importacao legada

Placeholder ja incluido em:

- `app/services/import_service.py`

Estrategias previstas:

- importacao manual assistida
- importacao via CSV
- parsing de DOCX legado
