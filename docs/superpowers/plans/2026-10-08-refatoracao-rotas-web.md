# Separação das rotas web de clientes e propostas

> Etapa 9 da refatoração segura, executada após as etapas 6–8, com caracterização antes e revisão independente. Nenhum commit.

**Objetivo:** deixar `pages.py` responsável por Hoje/Mensagens/Usuários e registro de routers, retirando os handlers de Clientes e Propostas sem duplicar APIs existentes.

**Arquitetura:** routers web específicos, um helper existente de renderização compartilhado e aliases de compatibilidade em `pages`. API routers `clients`, `proposals`, `proposal_files`, autenticação e geradores permanecem intocados.

**Restrições:** preservar branch/localchanges/commits externos; não ler configurações privadas, dados operacionais ou integrações; nenhum restart, nova instância, migração, dependência ou mudança de regras. Usuários/login intocados. Nenhum arquivo/teste existente excluído. Usar `apply_patch` e launcher seguro. Não reescrever handlers ou unificar os fluxos de clonagem e geração.

## Etapa 9

Ownership:

- `app/routers/pages.py`;
- novos `app/routers/web_clients.py`, `app/routers/web_proposals.py`, `app/routers/web_rendering.py`;
- novo `tests/test_web_page_contracts.py`.

Interfaces:

- `web_rendering.render_template(request, template_name, context, *, status_code=200)`: função existente, corpo/assinatura idênticos;
- `web_clients.router`: cinco handlers existentes de `/web/clients` (lista, formulário novo, criação, detalhe, edição);
- `web_proposals.router`: handlers existentes de propostas e `/import-proposals`, helpers de default/prefill/payload/redirect/IDs.
- `pages.router` continua sendo o único ponto registrado em `main.py`; `include_router` nas posições originais preserva a ordem da tabela de rotas. Routers filhos sem `tags=["pages"]` para não duplicar tags herdadas do pai.

Manter nomes, decorators, argumentos, URLs, response types, exceções, ordenação, defaults, schemas, commits, chamadas e mensagens dos handlers. Aliases históricos de handlers/helpers em `pages` devem continuar acessíveis. `pages.settings` e `web_proposals.settings` devem usar o mesmo objeto de `get_settings` em cache para manter o monkeypatch existente de `default_km_value`; não inserir novos Settings construtores. Manter imports históricos efetivamente usados pelos testes e scripts (por exemplo `pages.board_service`). Não fazer os módulos filhos importarem `pages` (evitar ciclo); mover renderer para helper independente.

- [x] Caracterizar HTTP com banco sintético antes: criação/edição/detalhe de cliente e rejeição de nome ausente; importação com responsáveis ativos; lista/formulário/detalhe/revision redirect e 404 de proposta. Nenhum gerador real.
- [x] Executar `test_web_page_contracts.py`, `test_proposal_form.py`, `test_proposal_origin.py`, `test_authentication.py`, `test_template_characterization.py`, `test_today_routes.py` antes da extração. Guardar tabela de rotas/OpenAPI do código anterior sem startup.
- [x] Mover corpos/decorators literalmente e incluir routers nas posições anteriores. Sem wrappers para operações; aliases preservam entrada antiga.
- [x] Rodar mesmo conjunto depois, comparar AST de handlers/helper renderer e tabela de rotas/OpenAPI. Conferir argumentos de dependências com mesma identidade `get_db`.
- [x] Ruff completo novos arquivos e E9/F pages, compile/diff-check e revisão independente. Se B008/estilo anteriores forem movidos junto aos handlers literais, registrar essa transferência (não ocultar nem alterar assinaturas para fazer lint passar). E9/F deve passar; lint global comparativo não deve ganhar novos achados. Sem autofix global.

Launcher obrigatório, adaptar apenas lista de testes:

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "TEST_FILES_HERE"]))'
```

O fechamento executa suíte completa e JS uma vez após todas as etapas. Não é necessário testar novamente serviços reais que estão proibidos neste escopo. A ativação operacional permanece bloqueada pelo startup; manter esse fato separado da validação de código.

## Resultado

48 testes focados antes/depois, incluindo dois novos contratos HTTP; revisão independente aprovada. AST de 23 funções originais preservada, incluindo handlers retidos; tabela de rotas completa e OpenAPI iguais. get_db e settings mantêm identidade, sem import circular. pages.py caiu de650 para344linhas nesta etapa.

Onze B008 acompanham assinaturas existentes nos filhos; nenhum suppression ou alteração de assinatura. E9/F aprovado. O controller resolveu um I001 novo no teste OCR, retornando Ruff global a223 ocorrências da linha de base. Suíte integrada final812passed13skipped;36JS;compilação/diff-check/hashschema/auth aprovados. Nenhum runtime operacional iniciado. Resultado completo em docs/refatoracao-segura.md.
