# Refatoração da composição do relatório técnico — 11/10/2026

Branch `refactor/promotion-contacts`, HEAD de referência `a193941`.
Preservadas todas as alterações locais da etapa anterior de importação PDF.
Nenhum commit, push, merge, migração, configuração privada, integração real ou
reinício foi executado nesta rodada.

## Arquitetura e áreas auditadas

| Área | Classificação | Resultado / trabalho restante |
|---|---|---|
| Composição de fatos do relatório | Refatorada e validada | `service_report_projection.py`: oito helpers e três dicionários literais para campos, timeline, snapshot, dados ausentes e fingerprint. |
| DTOs, consulta, conclusão técnica e prévia | Mantidos porque pertencem ao fluxo existente | Permanecem no serviço original; validação de conclusão e carregamento do chamado não foram contornados. |
| Confirmação, geração/renderização DOCX/PDF, arquivos, transações e reconciliação | Mantidos por unidade de responsabilidade | Funções preservadas por AST; não dividir compensação de arquivo/commit entre donos diferentes. Nenhuma otimização desse núcleo foi tentada. |
| Assistente, interface, banco, autenticação e provedores | Não refatorados nesta etapa | Consumidores mantêm os mesmos aliases; validação manual e operacional continuam fora desta rodada. |

`service_report_service.py` passa de **628 para 512 linhas**; a projeção tem 146.
O conjunto passa de 628 para 658 linhas: não houve redução líquida. A composição
pode ser testada separadamente da geração e das transações, sem camada genérica.

O módulo de projeção recebe dados já carregados. Não recebe Session, consulta
banco, lê/grava arquivos ou importa o serviço original. O loader existente
carrega cliente e eventos com joinedload/selectinload. Objetos ORM arbitrários
com atributos não carregados podem provocar lazy-load; a extração não promete
pureza de ORM fora desse contrato e não alterou o loader.

Preservados: ordem/identidade dos dicionários, labels, regex, datas, campos vazios,
precedência recebida de eventos, todos os IDs de origem inclusive correções,
fingerprint e exports históricos. `build_preview`, `generate_report` e
`_render_context` mantêm seus corpos e decisões; a confirmação ainda antecede
geração e gravação. Vinte e uma funções/classes restantes têm AST idêntica.

## Validação e rastreabilidade

- Antes da extração: **40 passaram, um opt-in pulado**. Depois e com teste de
  identidade: **41 passaram, um pulado**, 1242 avisos preexistentes, 3,90s.
- Nove casos novos em `test_service_report_projection.py`: labels e narrativa,
  verificações resolvida/pendente/ausente, snapshot e timeline, precedência,
  inspeção sem data inventada de conclusão, correções/IDs, campos ausentes,
  fingerprint sensível a mudanças e identidade dos onze exports.
- Integração sintética existente: `test_service_report_service.py`,
  `test_service_report_routes.py`, `test_assistant_service_report.py` e
  `test_service_history_immutability.py`. Exercita prévia, confirmação obsoleta,
  retry, reconciliação após perda da resposta de commit, imutabilidade e downloads
  com SQLite temporário e conversores/provedores simulados.
- Suíte completa: **903 passaram, 13 pulados**, 6905 avisos de depreciação,
  **56,83s**. Baseline anterior 894/13; nove novos casos, sem falhas.
- **36 testes JS passaram**. Não houve teste manual com navegador/microfone.
- Revisão independente de especificação, qualidade e branch: PASS/Approved,
  sem achados bloqueantes. Também examinou o loader e consumidores do Assistente,
  além da compatibilidade com as etapas de contatos e parser PDF.
- OpenAPI/DDL PostgreSQL compilado: mesmos hashes, 97 rotas/34 tabelas.
  Compilação não é execução de migração ou teste em PostgreSQL real.
- Arquivos de autenticação mantêm os três hashes anteriores. Nenhum schema,
  permissão ou configuração de IA/e-mail foi alterado.
- Ruff comparativo `app scripts tests`: 223 ocorrências, mesma distribuição.
  Nenhuma supressão ou mudança de regra para fazer lint passar. Lint fatal,
  compilação e diff-check passaram; lint global não está limpo.
- Nenhum arquivo ou teste foi excluído, nem assert enfraquecido.

Launcher da suíte completa (ambiente virtual e sem leitura de .env):

```bash
PYTHONPATH=. APP_ENV_FILE=/dev/null RUN_GEMINI_SMOKE_TEST=0 RUN_OLLAMA_INTEGRATION=0 RUN_OLLAMA_LIVE=0 RUN_REPORT_DOCKER_CONVERTER_TEST=0 EMAIL_PROVIDER=disabled EMAIL_SYNC_ENABLED=false EMAIL_AUTO_TASK_CREATION_ENABLED=false .venv/bin/python -c 'from app.config import Settings; Settings.model_config["env_file"] = None; import pytest; raise SystemExit(pytest.main(["-q", "-ra"]))'
```

## Limites e situação operacional

Não foram usados dados de chamados, documentos ou mensagens reais; não houve
consulta Yahoo nem chamada Gemini/SMTP/STT/TTS real. Os testes não validam
conteúdo técnico de um atendimento real, conversão PDF real, concorrência
PostgreSQL ou experiência manual por voz.

A 8013 permanece parada, sem atualização. Seu bloqueio de administrador/chave
privada de sessão não foi contornado. A etapa de código está validada, mas
a refatoração integral e a ativação operacional não são declaradas concluídas.
