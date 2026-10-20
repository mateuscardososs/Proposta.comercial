# Refatoração do parser comercial PDF — 11/10/2026

Branch `refactor/promotion-contacts`, HEAD de referência `a193941`. Esse commit
externo incorporou a etapa anterior e foi preservado. Nesta rodada não houve
commit, push, merge, migração, instalação de dependências ou atualização da 8013.

## Arquitetura e responsabilidades

| Área | Classificação | Resultado e proteção |
|---|---|---|
| Interpretação comercial de texto | Refatorada e validada | `proposal_pdf_parser.py`: três dataclasses, duas exceções e dez funções puras, movidas literalmente. |
| Extração física e wrappers de bytes | Mantidos porque são um fluxo separado | `pdf_import_service.py`: seis extratores/fallbacks e dois wrappers, com AST idêntica; bibliotecas PDF continuam carregadas somente quando chamadas. |
| Importação HTTP, confirmação e persistência | Mantidas, sem reorganização nesta rodada | Router chama o wrapper público original; preview não grava, confirmação usa usuário ativo e os serviços de cliente/proposta existentes. |
| OCR, índice, geração documental, voz e login | Não refatorados nesta etapa | Contratos e arquivos preservados; não foi ampliado o escopo. |

O serviço original passa de **527 para 106 linhas**. O parser puro tem 420;
o conjunto passa de 527 para 526 linhas. A mudança separa interpretação de I/O,
mas **não representa redução significativa do código total**.

Preservados: assinaturas públicas, aliases históricos por identidade, hierarquia
de exceções, decimais/defaults, regex, mensagens, warnings ordenados, previews,
payloads e IDs, fallbacks, logger e pontos de substituição dos extratores.
`parse_pdf_bytes` continua resolvendo `parse_pdf_text` no módulo original.
O parser não importa configuração, banco, backend PDF nem o serviço original.
Nenhuma heurística foi melhorada oportunisticamente.

## Validação executada

- Caracterização anterior: **106 testes passaram**; após extração, os mesmos 106.
  Com teste adicional de identidade de exports, **107 passaram**, 378 avisos
  preexistentes, 8,00s na última execução focada.
- Há **24 casos novos** na suíte completa: textos vazios/cliente ausente,
  labels/fallback, referência de contato, valores brasileiros/ingleses/defaults/
  negativos, itens tabulares e bullets, cronograma, imposto/pagamento, warnings,
  preview/payload, identidade e pontos de patch.
- Contrato HTTP sintético usa router isolado e extrator simulado, mas executa
  o fluxo real de persistência em SQLite temporário: preview sem gravação,
  confirmação com responsável ativo e erros com as mesmas mensagens. Não é
  validação de leitura de um PDF real nem de uma proposta operacional.
- Suíte completa isolada: **894 passaram, 13 pulados**, 6905 avisos de
  depreciação, 54,94s. Baseline anterior 870/13, sem regressões.
- **36 testes JavaScript passaram**. Nenhuma alteração de interface/voz.
- Revisão independente de especificação e da branch: PASS/Approved, sem
  achados críticos/importantes. Quinze definições movidas e oito funções mantidas
  foram conferidas por AST; contatos da etapa anterior continuam compatíveis.
- OpenAPI e DDL PostgreSQL compilado: hashes inalterados, **97 rotas/34 tabelas**.
  Hashes dos três arquivos de autenticação preservados. Não houve conexão de
  testes ao PostgreSQL operacional; compilar DDL não valida execução no PostgreSQL.
- Ruff `app scripts tests`: **223 ocorrências**, mesma distribuição da baseline.
  Alguns diagnósticos migraram junto do código legado; não foram ocultados por
  noqa ou corrigidos com mudança funcional. Lint fatal, compilação e diff-check
  passaram. Não se declara lint global limpo.
- Nenhum arquivo, função de teste antiga ou assert foi removido/enfraquecido.

Comando completo (apenas ambiente virtual; sem leitura de .env):

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "-ra"]))'
```

## Limitações e operação

Sem documentos/e-mails reais nos testes, chamadas reais de IA, OCR/voz ou envio.
Não houve teste manual de importação na interface, microfone ou concorrência
no PostgreSQL. O parser mantém limitações de interpretação e defaults legados;
os testes caracterizam o comportamento atual, não comprovam precisão universal.

Os wrappers legados ainda registram nome de arquivo e detalhes de exceção em
falhas; essa política preexistente ficou intacta e merece revisão funcional
separada de privacidade. Não foram consultados logs operacionais nesta etapa.

A 8013 permanece sem listener; ativação continua dependente do administrador e
da chave de sessão privados. Não foi desabilitado login nem iniciado startup
que executasse backfill ou IMAP.
