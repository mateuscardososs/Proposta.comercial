# Projeção dos dados do relatório técnico — plano

> Executar por subagent-driven-development com caracterização e revisão. Sem commits.

**Objetivo:** separar os helpers de composição de fatos registrados da consulta e geração transacional de relatórios.

**Arquitetura:** `service_report_projection.py` recebe chamado/eventos já carregados e converte para campos, timeline, snapshot e fingerprint. O serviço original conserva DTOs, consulta, validação de conclusão, prévia, geração/renderização, confirmação, arquivos e reconciliação. Aliases mantêm consumidores existentes.

**Tecnologias:** Python/Pydantic/pytest existentes; sem novas dependências.

## Restrições globais

- Branch refactor/promotion-contacts, HEAD a193941; preservar mudanças locais da etapa15 e commits externos. Não repetir etapas concluídas.
- Não ler configs privadas, documentos/dados operacionais ou executar integrações reais.
- Não criar commit/push/merge, migrar banco, mudar schema/configuração, instalar dependências ou iniciar/reiniciar instâncias.
- Preservar mensagens, regex, dicionários/ordem, datas, defaults, fingerprint, IDs e timelines. Não mudar regras de relatório ou resolver defeitos preexistentes nesta extração.
- Não alterar os corpos de build_preview, generate_report, _render_context ou operações de arquivo/transação. Assinaturas e alias históricos permanecem.
- Uma suíte Python por vez, banco e artefatos sintéticos. Não remover testes/arquivos nem enfraquecer asserts.

## Task16 — composição de dados já carregados

Arquivos: modificar app/services/service_report_service.py; criar app/services/service_report_projection.py e tests/test_service_report_projection.py.

Mover literalmente dicionários FIELD_LABELS, EVENT_LABELS, NARRATIVE_LABELS e oito funções:

```python
_normalize_label(value: str) -> str
_parse_narrative(description: str) -> dict[str, str]
_verification_from_event(description: str) -> str
_format_date(value: date | None) -> str
_serialize_source(call: ServiceCall, effective_events) -> dict[str, object]
_fingerprint(source: dict[str, object]) -> str
_fields_model(values: dict[str, object]) -> ServiceTechnicalReportFields
_missing_fields(fields: ServiceTechnicalReportFields) -> list[str]
```

O módulo novo não recebe Session, consulta banco, lê arquivos ou importa o serviço original. Imports de tipos ORM podem ser TYPE_CHECKING; dados de produção chegam carregados pelo get_service_call existente. Não copiar DTOs ou mover _render_context, evitando dependência circular. Os dicionários são compartilhados por identidade, não cópias. Aliases por módulo+atribuição no original, sem wrappers genéricos e sem supressões de lint.

- [x] Caracterizar antes da extração, através dos helpers atuais: labels com acento/case, repetição/linhas vazias e labels desconhecidos; verificação resolvida/pendente/ausente e observação; cliente/endereço e campos faltantes; cronologia recebida, precedência de fatos mais recentes, data explícita versus inspeção sem conclusão; IDs de todos os eventos, inclusive correções, ordenados; fingerprint igual para reordenação de chaves mas alterado por fato/evento novo; campos desconhecidos ignorados e ordem dos campos ausentes. Expected literal independente de produção, usando objetos sintéticos carregados.
- [x] Rodar antes tests/test_service_report_projection.py, tests/test_service_report_service.py, tests/test_service_report_routes.py, tests/test_assistant_service_report.py, tests/test_service_history_immutability.py.
- [x] Mover oito corpos/três dicionários literalmente, preservar aliases/identidade e imports usados pelo serviço original. Comparar AST das funções restantes contra snapshot imediato pré16 (não reverter etapa15).
- [x] Repetir conjunto. Conferir relatório com campos faltantes, token/fingerprint obsoleto, retry, perda de resposta de commit, imutabilidade e download pelos testes existentes. Conversor e provedores simulados; opt-in reais não ativados.
- [x] Ruff completo comparativo app/scripts/tests, fatal/compile/diff; revisão de especificação, qualidade e branch.
- [x] Fechar com suíte completa isolada,36JS, hashes OpenAPI/DDL/auth, documentação e ledger. Sem ativação da8013.

Fechamento:40/1antes41/1depois;9novos;903passed13skipped6905warnings56.83s,
36JS. Revisão spec/quality/branch Approved,8helpers3dicts+21demais AST iguais.
Ruff223mesmodistribuição,OpenAPI/DDL/authpreservados;semprodução/publicação.
Relatório:docs/refatoracao-projecao-relatorio.md.

Launcher seguro (alterar apenas a lista de testes):

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "-ra"]))'
```

Baseline anterior894Python/13skips,36JS,223Ruff. A camada transacional ficará
coesivamente no serviço, mesmo que ainda extensa. Esta etapa não promete
compactar código total nem melhorar conteúdo técnico dos relatórios.
