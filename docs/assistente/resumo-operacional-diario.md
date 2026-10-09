# Resumo operacional diário do Assistente

## Comportamento

Pedidos como “Bom dia, o que preciso fazer hoje?”, “Organize minha agenda” e
“O que devo fazer hoje?” acionam uma consulta determinística antes da interpretação
do provedor de texto. A leitura funciona pelo mesmo fluxo de mensagens do Assistente;
voz usa a transcrição já recebida, mostra a resposta e envia uma versão concisa ao TTS.
Gemini/Ollama não escolhem as fontes nem recebem instrução para inventar fatos.

O resumo usa o fuso `ASSISTANT_TIMEZONE` e registra data/hora da consulta. A lista de
tarefas reutiliza `get_task_day_plan`, a mesma projeção ordenada que sustenta Hoje;
inclui todas as tarefas abertas, separando prazo vencido, prazo de hoje, próximas e
sem prazo. A agenda usa `build_daily_schedule`; sem janelas de trabalho configuradas,
nenhum horário é presumido como livre. Blocos e compromissos são sugestões de leitura,
sem salvar snapshots nem alterar tarefas.

Também são consultados chamados em execução ou com etapa administrativa pendente,
mensagens já armazenadas no cache local e contas pendentes a pagar/receber vencidas
ou com vencimento nos próximos sete dias. Lançamentos arquivados ou pagos/recebidos
ficam de fora. Consultar o resumo não grava alterações.

## Estado das fontes

Cada consulta tem seu próprio estado e link de origem. Falha em uma fonte não substitui
os resultados das demais. Estados possíveis incluem consulta concluída, vazia,
parcial/desatualizada, falha, indisponível e disponibilidade não configurada.

E-mail é lido exclusivamente de `inbox_emails` e `email_sync_states` já persistidos.
O resumo não conecta ao IMAP, não aciona sincronização e não modifica flags. Uma fonte
de e-mail sem ciclo concluído, com erro/parcialidade ou cache fora da janela de
atualidade configurada aparece como indisponível/parcial; totais do cache não são
apresentados como prova de caixa vazia. O texto não inclui assuntos nem conteúdo de
mensagens; informa quantidades operacionais/para revisão e oferece link para a página
de mensagens.

Financeiro e serviços usam consultas existentes do backend; a aplicação compõe os
resultados de forma determinística e sanitiza erros por fonte, sem expor mensagens de
exceção ou conteúdo de e-mail. A resposta visual traz os itens, motivo, prazos e links;
a resposta falada prioriza quantidades e avisa quando há fonte incompleta.

## Validação automatizada

```bash
PYTHONPATH=. .venv/bin/pytest tests/test_assistant_daily_brief.py tests/test_today_service.py tests/test_daily_schedule_service.py tests/test_assistant_service.py -q
```

Os testes usam o banco SQLite de testes isolado e dados sintéticos. Eles verificam
quadro vazio, tarefas atrasadas e de hoje, blocos sem disponibilidade presumida,
e-mail parcial, indisponibilidade de uma fonte, contas vencidas/próximas, consulta
por voz e ausência de alterações nos registros consultados. Eles não validam a
experiência manual de microfone, captura de silêncio ou áudio no navegador.
