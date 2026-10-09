# Apresentação documental e extração DOCX — plano de implementação

> Para execução: usar subagent-driven-development, caracterização antes e revisão por etapa. Sem commits.

**Objetivo:** separar apresentação do resultado de busca e leitura XML de DOCX das responsabilidades de consulta e persistência.

**Arquitetura:** helpers puros recebem resultados documentais ou bytes de pacote previamente validado. O Assistente conserva a busca autorizada, histórico e transações; proposal_file_service conserva validação de upload, segurança do pacote, análise comercial e persistência.

**Tecnologias:** Python, FastAPI, Pydantic, ZIP/XML padrão, pytest; nenhuma dependência nova.

## Restrições globais

- Preservar branch refactor/safe-modularization e todas as alterações locais anteriores. HEAD inicialmente ba245e2, avançou externamente para b32c784 durante a preparação; não criado pelo agente.
- Não ler configurações privadas, não acessar dados operacionais, não chamar Gemini/Yahoo/SMTP/STT/TTS reais.
- Não reiniciar instâncias, aplicar migrações, alterar schema, instalar dependências, criar commit/push/merge ou excluir arquivos/testes.
- Preservar URLs, schemas, mensagens, citações, ordem de leitura, tratamento de erros, limites e efeitos de flush/commit.
- Uma suíte Python por vez, banco temporário e configuração sem .env.

## Etapa 12 — apresentação da busca documental

Arquivos: app/assistant/service.py; novo app/assistant/document_presentation.py; novo tests/test_assistant_document_presentation.py.

Interface: `present_document_search(conversation_id: int, result: DocumentSearchResult) -> AssistantReply`; `document_ocr_limitation(result) -> str`.

- [x] Caracterizar o método atual com resultados sintéticos: evidência com página e seção, limite de dois trechos falados, zero documentos, todos ilegíveis, ausência de evidência, parcial, OCR indisponível com motivos. Comparar message/spoken_message/document_items/limitations, sem OCR real.
- [x] Rodar teste novo e tests/test_assistant_document_search.py, tests/test_document_index_service.py, tests/test_assistant_provider_parity.py antes da extração.
- [x] Mover literalmente o bloco após a busca e o helper OCR. `_execute_document_query` conserva a chamada `search_proposal_documents(self.db, output_dir=self.output_dir, query=query)` antes de `present_document_search(conversation_id, result)`; helper estático histórico permanece alias. Novo módulo não faz I/O, consulta ou imports do orquestrador.
- [x] Repetir os mesmos testes, conferir AST dos métodos não afetados e validar Ruff/compilação/diff. Revisão independente.

Resultado: 76 testes focados antes/depois, dez casos novos; 60 métodos não
afetados com AST idêntica; revisão spec PASS/quality Approved. 385 avisos de
depreciação SQLAlchemy preexistentes. Nenhuma chamada de integração real.

## Etapa 13 — leitura textual DOCX

Arquivos: app/services/proposal_file_service.py; novo app/services/docx_text.py; novo tests/test_docx_text.py.

Interface pura: `extract_validated_docx_text(payload: bytes) -> str`; `extract_validated_docx_sections(payload: bytes) -> list[tuple[str,str]]`; `_xml_text(xml_bytes: bytes) -> str`. Recebe exclusivamente pacotes validados pelo serviço público; não deve ser usado diretamente por rotas.

- [ ] Caracterizar pelo serviço público a ordem literal documento→headers ordenados→footers ordenados, seções com títulos e prefixos, parágrafos sem título, tabela, XML inválido e segurança antes da extração. Preservar os testes de limites que substituem constantes no serviço atual.
- [ ] Rodar tests/test_docx_text.py, tests/test_proposal_file_service.py, tests/test_proposal_file_routes.py, tests/test_document_index_service.py, tests/test_assistant_document_search.py antes.
- [ ] Mover somente leitura ZIP/XML e namespaces para docx_text. Os wrappers públicos primeiro chamam `_validate_docx_package(payload)` e depois o extrator puro. Preservar aliases NS/WORD_NS/TAG_ATTRIBUTE e `_xml_text` no serviço; analyze_word_reupload continua usando os mesmos valores. Não mover limites, exceções comerciais, upload, criação de revisão, cópia, cleanup ou commit. Para evitar dependência circular, a exceção de validação pode ficar em módulo neutro `document_errors.py`, com alias de identidade no serviço e import no extrator; mover apenas a classe existente sem alterar hierarquia ou mensagens.
- [ ] Repetir o conjunto, comparar AST restante, Ruff/compilação/diff e revisão independente.

## Fechamento

- [ ] Suíte completa isolada, JS, lint global comparativo, compile e diff-check.
- [ ] OpenAPI/DDL/auth equivalentes; revisão consolidada e documentação/ledger atualizados.
- [ ] Rechecar apenas listener/healthz da 8013; não contornar os efeitos de startup.

Launcher seguro (trocar apenas a lista de testes):

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "-ra"]))'
```

Baseline de fechamento anterior: 836 Python passed/13 skipped, 36 JS, 223 ocorrências Ruff preexistentes. A instância 8013 está parada; inicialização pode alterar banco e consultar IMAP, por isso a atualização operacional permanece bloqueada neste escopo.

## Encerramento por solicitação do usuário

Em 09/10 o usuário encerrou novas refatorações e autorizou commit/push/merge.
A etapa 13 já estava extraída no disco; não foi descartada nem ampliada.
Validação do delta existente: 860 passed/13 skipped na suíte completa e 77
testes focados de extração/upload/apresentação. Revisão final independente
aprovada. Os checkboxes anteriores registram o roteiro original, interrompido
na etapa 13; publicação e ativação passam a ser procedimento separado.
