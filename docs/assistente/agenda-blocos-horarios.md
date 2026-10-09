# Agenda sugerida com blocos de horário

Atualizado em 2026-10-06.

## Comportamento

- `get_task_day_plan()` continua sendo a única fonte e ordenação das tarefas abertas, usada
  por Hoje e pelo Assistente. `build_daily_schedule()` consome essa projeção e não consulta
  um conjunto paralelo nem altera tarefas.
- A agenda só aloca em janelas de disponibilidade semanal cadastradas. Sem disponibilidade
  para aquele dia, não presume tempo livre e apresenta as tarefas em “Não alocadas”.
- Cada tarefa pode guardar uma duração estimada opcional entre 1 e 1440 minutos. Se vazia,
  usa o padrão editável em `/web/agenda/config` (60 minutos ao iniciar o recurso). A página,
  Assistente e snapshot identificam sempre a duração como estimativa.
- Janelas podem ser repetidas em qualquer dia da semana. Intervalos e compromissos fixos
  podem ser semanais ou específicos de uma data. Não são movidos; aparecem na sugestão e
  bloqueiam tempo de trabalho.
- O planejador escolhe o primeiro intervalo contínuo que comporte a estimativa, respeitando
  o tempo local atual em `America/Recife`, as janelas, bloqueios e a sequência compartilhada
  por atraso, prazo, urgência explícita e status. Não inventa duração, horas extras,
  deslocamentos ou dependências. Itens que não cabem trazem motivo.
- A proposta do Assistente e a voz são a mesma resposta determinística. O Gemini/Ollama não
  escolhe horários; somente pode interpretar ou explicar a saída real do planejador.

## Persistência e confirmação

Visualizar ou gerar uma sugestão é leitura somente: não grava snapshot, não altera tarefa e
não cria evento em calendário externo. O usuário precisa pedir explicitamente “salve a
agenda”; o Assistente mostra data, quantidade de blocos, não alocadas e se existe uma versão
anterior. Ação só persiste após a confirmação existente.

Cada `AssistantAction` executada cria um `DailyScheduleSnapshot` com `version` crescente,
data, JSON de blocos/bloqueios/não alocadas, ação autorizadora e chave idempotente única.
Um retry da mesma ação retorna o snapshot existente. Uma versão nova exige confirmação e
usa compare-and-swap da versão anterior; se outra gravação ocorreu desde a prévia, a ação
expira com esclarecimento, sem substituir a versão nova. Snapshots são append-only, com
proteção ORM e triggers SQLite/PostgreSQL contra update/delete. O snapshot anterior continua
visível em Hoje no histórico.

## Schema e rollback

Não há Alembic neste projeto. No startup já existente, `Base.metadata.create_all()` cria as
quatro tabelas novas (`daily_schedule_preferences`, `work_availability_windows`,
`fixed_commitments`, `daily_schedule_snapshots`) sem recriar as atuais. A rotina de
compatibilidade adiciona `tasks.estimated_duration_minutes` como coluna nullable; registros
atuais continuam sem duração e passam a usar a estimativa padrão somente ao gerar agenda.
Os triggers de imutabilidade dos snapshots são adicionados pela mesma rotina de guardas já
usada pelo schema.

O teste SQLite valida adição da coluna nullable, criação de tabelas, preservação de dados de
tarefa e guardas de histórico. O PostgreSQL isolado deve ser validado antes de reiniciar a
instância principal. O rollback PostgreSQL está em
`scripts/migrations/20261006_agenda_horarios_rollback_postgresql.sql`: precisa ser executado
com a aplicação parada, antes de voltar ao código anterior, e recusa remover qualquer
configuração, estimativa ou snapshot para não destruir dados novos. Não executar rollback
no banco operacional sem backup validado.

## Configuração e testes

Abra `Hoje` → **Configurar agenda**. Salve minutos padrão, adicione as janelas semanais e
adicione intervalos/compromissos semanais ou avulsos. Na edição/criação de tarefa, duração
individual é opcional.

Frases cobertas incluem “organize minha agenda”, “o que devo fazer hoje?” e “salve a agenda”.
O último caso produz cartão de confirmação e não salva antes do aceite. Dizer “cancela” ou
usar Cancelar deixa o snapshot intacto. Ao salvar outra vez no mesmo dia, o Assistente exige
uma confirmação nova e preserva as versões antigas.

`tests/test_daily_schedule_service.py`, `tests/test_agenda_routes.py`,
`tests/test_assistant_service.py`, `tests/test_today_routes.py` e
`tests/test_assistant_schema_compatibility.py` cobrem ordenação, mais de 50 tarefas,
ausência de disponibilidade, janelas, intervalos, compromissos avulsos, estimativas, falta
de espaço, leitura sem escrita, criação/replace/cancelamento/retry de snapshots, histórico
append-only e apresentação Hoje/voz.

Esta feature não cria eventos em Google Calendar/Outlook. As páginas web continuam restritas
ao uso local; ainda não há autenticação efetiva.
