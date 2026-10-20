# Separação de contatos promocionais — plano

> Executar com subagent-driven-development e revisão independente. Sem commits, push, merge ou atualização operacional nesta rodada.

**Objetivo:** separar cadastro/consentimento de contatos da geração e envio de campanhas, sem mudar comportamento.

**Arquitetura:** novo router `campaign_contacts.py` contém as duas rotas de contatos e seus helpers específicos. `promotions.py` conserva campanhas, geração, arquivos e SMTP, incluindo o router de contatos na posição original. Validação comum de formulário fica em `promotion_web_support.py`, evitando duplicação e imports circulares. Nenhuma regra nova.

**Tecnologias:** FastAPI/SQLAlchemy/pytest existentes, sem novas dependências.

## Restrições globais

- Branch refactor/promotion-contacts criada de main56cad4b; preservar arquivos e histórico.
- Não ler .env/configuração privada, nem usar dados operacionais nos testes.
- Não chamar Gemini, IMAP, SMTP, STT ou TTS reais; não iniciar/reiniciar instâncias.
- Não alterar schema, migrações, templates, JS, autenticação ou configurações.
- Preservar URLs, nomes/ordem/tags de rotas, schemas, códigos HTTP, redirects, mensagens e scopes de token.
- Preservar a ordem de consulta, lock, flush, commit e rollback; consentimento começa desativado e história permanece append-only.
- Não excluir testes/arquivos, nem suavizar asserts. Uma suíte Python por vez, somente banco temporário.

## Task 14 — router de contatos e consentimento

Arquivos: modificar app/routers/promotions.py; criar app/routers/campaign_contacts.py e app/routers/promotion_web_support.py; criar tests/test_campaign_contact_routes.py.

Interface: router filho sem tags próprias, incluído pelo router pai com tags promotions. Mesmas assinaturas `create_campaign_contact(client_id, request, db=Depends(get_db))` e `update_campaign_contact(client_id, contact_id, request, db=Depends(get_db))`. Helpers `_parse_contact_form(form, *, previous=None)` e `_register_consent_event(db, contact, *, event_type, source, occurred_at, email_snapshot=None)` movidos literalmente. Helper comum `_require_form_token(scope, form)` movido literalmente e exportado por alias nos dois módulos. `settings=get_settings()` continua sendo o mesmo objeto cacheado; aliases históricos dos handlers/helpers/modelos removidos dos imports do pai devem continuar disponíveis quando úteis à compatibilidade.

- [x] Caracterizar antes da extração via HTTP sintético: cliente/contato inexistente404, token inválido403, e-mail/data inválidos422, duplicidade409, contato novo sem opt-in/evento, reenvio da mesma atualização sem novos eventos, reautorização explícita e revogação mantendo snapshot anterior. Verificar Location303 e nenhum transporte externo instanciado.
- [x] Rodar conjunto antes com launcher abaixo: tests/test_campaign_contact_routes.py, tests/test_promotion_campaigns.py, tests/test_authentication.py, tests/test_web_page_contracts.py.
- [x] Mover os quatro corpos de contatos sem reescrever; trocar decorators para router filho. No pai, `router.include_router(campaign_contacts.router)` exatamente antes de promotions_page. Aliases históricos preservados, sem wrappers de HTTP e sem dependência circular.
- [x] Repetir o mesmo conjunto; comparar AST dos outros métodos, corpos extraídos e tabela de rotas/OpenAPI. Ruff completo nos novos módulos/testes, fatal nos modificados, compile e diff-check. Não corrigir regras anteriores oportunisticamente.
- [x] Revisão de especificação/qualidade e fechamento: suíte completa isolada,36JS, lint global comparativo, compilação, hashes OpenAPI/DDL/auth e documentação.

Fechamento:54before/after,10novos;870Python/13skips/6899warnings53.00s;36JS.
Revisão spec PASS/quality e branch Approved. Cinco funções extraídas/dez retidas
AST idênticas,97rotas/34tabelas e hashes OpenAPI/DDL/auth preservados. Ruff no
escopo app/scripts/tests mantém223; dois B008 migraram com as assinaturas.
Nada suprimido. Sem publicação ou reinício. Relatório:
docs/refatoracao-contatos-promocionais.md.

Launcher obrigatório; alterar somente lista de testes:

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "-ra", "tests/test_campaign_contact_routes.py", "tests/test_promotion_campaigns.py", "tests/test_authentication.py", "tests/test_web_page_contracts.py"]))'
```

Baseline anterior:860Python/13skips,36JS,223Ruffpreexistentes; confirmar comparativo nesta etapa. 8013 continua parada por ausência de administrador/chave privada de sessão. Não contornar esse bloqueio nesta refatoração.
