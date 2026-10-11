# Refatoração de contatos promocionais — 11/10/2026

Branch `refactor/promotion-contacts`, criada da `main` no commit `56cad4b`.
A publicação anterior permanece intacta. Esta rodada não executa commit, push,
merge, migração, startup, envio ou consulta de integração real.

## Responsabilidades e contratos

| Área | Classificação | Resultado / proteção |
|---|---|---|
| Contatos e consentimento | Refatorada e validada em testes focados | `routers/campaign_contacts.py` contém cadastro, atualização e histórico; quatro corpos movidos literalmente. |
| Token de formulário promocional | Refatorada e validada | `promotion_web_support.py` concentra o helper literal compartilhado, sem estado novo ou dependência circular. |
| Rotas de campanha, geração e envio | Mantidas porque já são um fluxo separado | Continuam em `promotions.py`; dez funções não afetadas têm AST idêntica. Nenhuma geração Gemini ou envio SMTP real. |
| Autenticação, banco, serviços de campanha e interface | Não refatorados nesta rodada | Preservados; mudanças nessas áreas exigem outra etapa. Nenhuma justificativa para exclusão de arquivos ou testes. |

O router principal passa de **466 para 321 linhas**. O router filho tem 163
linhas e o suporte 11; o conjunto de produção passa de 466 para 495 linhas.
Portanto, a melhoria é separação de responsabilidades, **não redução líquida
do código**. Testes e documentação também acrescentam linhas de propósito.

Preservados: paths, nomes, ordem e tags de rotas, assinaturas e dependência
`get_db`, objeto cacheado de configurações, scopes de token, redirects303,
erros403/404/409/422, locks, flush/commit/rollback, consentimento desativado por
padrão, snapshots de endereço e eventos append-only. Aliases históricos dos
handlers/helpers/modelos continuam no módulo pai. Sem wrappers extras de HTTP.

## Testes e verificações

- 54 testes focados passaram antes e depois, com 302 avisos de depreciação
  preexistentes. Há 10 novos casos parametrizados; nenhuma função de teste antiga
  foi removida e nenhum assert foi suavizado.
- `test_campaign_contact_routes.py`: ausência de cadastro, token inválido,
  e-mail/data inválidos com rollback, duplicidade, consentimento inicial ausente,
  repetição de atualização, reautorização e revogação preservando endereço anterior.
  A fixture rejeita construção de gerador Gemini ou transporte SMTP.
- Conjunto de integração: `test_promotion_campaigns.py`, `test_authentication.py`
  e `test_web_page_contracts.py`, usando banco SQLite temporário e transportes
  sintéticos. Isso não valida concorrência/locks em PostgreSQL real.
- Revisão independente de especificação e da branch: PASS/Approved, sem achados
  bloqueantes. Cinco funções extraídas e dez restantes têm AST equivalente.
- 97 rotas/34 tabelas; hashes OpenAPI e DDL PostgreSQL compilado iguais à baseline.
  Compilar DDL não executa migração nem testa PostgreSQL.
- Hashes de auth.py, security/routes.py e test_authentication.py inalterados.
- 36 testes JS passaram. Não substituem navegador/microfone reais.
- Ruff no mesmo escopo `app scripts tests`: 223 ocorrências, distribuição igual
  à baseline. Dois B008 são assinaturas Depends já existentes, movidas para o
  filho; não foram ocultados com noqa nem alterados para satisfazer lint.
  `ruff check .` inclui outros arquivos e retorna 225; não é o mesmo comparativo.
- Compilação e `git diff --check` passaram.
- Suíte Python completa: **870 passaram, 13 pulados**, 6899 avisos de
  depreciação, 53,00 segundos. Baseline anterior: 860/13; dez casos acrescentados,
  sem falhas. Skips: dez de provedores reais opt-in, dois de conversores Docker
  opt-in e um dependente de LibreOffice ausente; não foram substituídos por mocks.

Launcher usado (Settings não lê .env):

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "-ra"]))'
```

## Limitações e operação

Nenhum arquivo ou teste excluído, nenhuma configuração privada lida/alterada,
nenhum dado operacional usado como fixture. Sem validação manual em navegador,
microfone, SMTP ou PostgreSQL real. A instância 8013 permanece parada; sua
ativação depende do provisionamento interativo de administrador e chave de sessão
já documentado, e não foi contornada para testar esta refatoração.
