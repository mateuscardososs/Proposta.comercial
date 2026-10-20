# Parser comercial de PDFs — plano

> Executar com subagent-driven-development, caracterização antes e revisão independente. Não executar commits.

**Objetivo:** separar interpretação comercial pura da leitura dos backends PDF.

**Arquitetura:** `proposal_pdf_parser.py` recebe somente texto, concentra os dataclasses de preview/payload e as heurísticas atuais. `pdf_import_service.py` mantém os backends, fallbacks, bytes/safe, logger e aliases históricos. O router de importação não muda; confirmação e persistência continuam nos serviços existentes.

**Tecnologias:** Python/Decimal/Pydantic/pytest existentes. Nenhuma nova dependência.

## Restrições globais

- Continuar na branch refactor/promotion-contacts; preservar HEAD externo a193941 e demais alterações.
- Não ler configuração privada, dados/documentos operacionais ou fazer chamadas reais a integrações.
- Não iniciar/reiniciar aplicação, banco ou outros processos. Não aplicar migração, alterar schema/dependência/limites ou criar commit/push/merge.
- Preservar mensagens, defaults, tipos, warnings, ordem, heurísticas e regex. Não melhorar a interpretação de PDFs como parte desta refatoração.
- Preservar API pública parse_pdf_text/parse_pdf_bytes/parse_pdf_bytes_safe, classes e hierarquia de exceções e os pontos de patch dos extratores.
- Testes com banco/documentos/textos sintéticos; uma suíte Python por vez. Não remover testes/arquivos nem enfraquecer asserts.

## Task 15 — separar parser comercial puro

Arquivos: app/services/pdf_import_service.py; novo app/services/proposal_pdf_parser.py; novo tests/test_proposal_pdf_parser.py.

Interfaces:

```python
parse_pdf_text(text: str, filename: str = "") -> ParsedProposalData
ParsedProposalItem.as_preview() / .to_schema()
ParsedScheduleRow.as_preview() / .to_schema()
ParsedProposalData.to_preview() / .to_proposal_payload(client_id, user_id)
```

Mover literalmente três dataclasses, as duas exceções e funções `_normalize_text`, `_parse_decimal`, `_find_label_value`, `_find_first_candidate_client`, `_extract_section`, `_parse_schedule_rows`, `_parse_item_rows`, `_extract_payment_days`, `_extract_tax_percent`, `parse_pdf_text`. As exceções podem pertencer ao parser puro, reexportadas por identidade no módulo original, evitando novo módulo de um único símbolo. Nenhum helper do parser pode importar pdf_import_service, configuração, banco ou backend PDF.

No módulo original, conservar literalmente seis funções de extração e os wrappers parse_pdf_bytes/parse_pdf_bytes_safe; aliases de todas as classes/funções movidas preservam seus nomes. parse_pdf_bytes continua chamando o símbolo público parse_pdf_text no módulo original, mantendo o ponto de substituição. Logger permanece no original. Nenhum backend é carregado antecipadamente.

- [x] Caracterizar antes: texto vazio/cliente ausente e exceções exatas; labels inline/linha seguinte e fallback; referência de contato; ausência de objeto/itens/cronograma com warnings ordenados; preview/payload com decimais e IDs; números brasileiros/ingleses, defaults e negativos; itens tabulares/bullets e cronograma com bullets/dias/horas/separadores; imposto e pagamento inline/linha seguinte. Expected independente de chamadas ao próprio parser.
- [x] Adicionar contrato HTTP sintético de importação: preview não cria cliente/proposta; confirmação usa usuário ativo existente e grava apenas via fluxo atual; erros preservados. Usar extrator simulado identificado como tal, sem geradores reais.
- [x] Rodar antes tests/test_proposal_pdf_parser.py, tests/test_pdf_no_text.py, tests/test_proposal_file_service.py, tests/test_proposal_file_routes.py, tests/test_assistant_document_search.py, tests/test_document_index_service.py.
- [x] Extrair literalmente, reexportar por módulo+atribuições explícitas para evitar PLC0414/F401; comparar AST das definições movidas e das oito funções mantidas.
- [x] Repetir mesmo conjunto; lint completo comparativo (diagnósticos anteriores podem mudar de arquivo, não de regra), fatal, compile/diff-check, revisão independente.
- [x] Fechamento: suíte completa isolada, JS, OpenAPI/DDL/auth, documentação e ledger. Não ativar instância.

Fechamento:106antes/depois e107com identidade adicional;894full/13skips,
6905warnings54.94s;36JS. Revisão spec/quality/branch Approved;15definições e8
funções preservadas;223Ruff,OpenAPI/DDL/auth iguais. Relatório:
docs/refatoracao-parser-pdf.md. Nenhuma ativação ou publicação.

Launcher seguro; trocar apenas lista de testes:

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "-ra"]))'
```

Baseline anterior:870Python/13skips,36JS,223Ruff no escopo app/scripts/tests.
Etapa14 concluída não deve ser repetida. A etapa15 não promete reduzir linhas
totais, mas separar interpretação pura de I/O e obter proteção de testes onde
as heurísticas legadas não tinham caracterização direta.
