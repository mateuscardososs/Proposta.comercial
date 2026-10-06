# Consulta de tarefas do Assistente

Atualizado em 2026-10-06.

## Comportamento

- Pedidos inequívocos de organização/consulta da agenda ou do quadro, como “organize
  minha agenda”, “olhe o quadro de tarefas e diga o que devo fazer hoje” e “mostre
  minhas tarefas abertas”, chamam o backend diretamente. Não dependem de o Ollama
  selecionar `consultar_tarefas`.
- A consulta usa a sessão SQLAlchemy e `board_service.get_tasks`, sem limite de resultados.
  `get_task_day_plan` em `app/services/today_service.py` é a projeção compartilhada pela
  resposta do Assistente e pela seção “Plano de tarefas para hoje” na página inicial.
  Inclui todas as tarefas abertas, também futuras e sem prazo; tarefas concluídas ficam
  fora. Não lê conteúdo de e-mail nem altera registros.
- A ordem é: vencidas (por vencimento mais antigo), prazo de hoje, urgência explícita
  quando não vencida/de hoje, execução concluída com etapa administrativa pendente,
  execução em andamento, próximos prazos (mais próximo primeiro), tarefas sem prazo e,
  por último, tarefas aguardando cliente sem outra condição mais forte. Dentro da mesma
  data, urgência explícita precede a ordem do quadro. Cada item informa status, prazo,
  prioridade sugerida, cliente cadastrado ou nome informado com vínculo pendente, quando
  existentes, e o motivo verificável da posição.
- O quadro não armazena um campo próprio de prioridade. `Prioridade sugerida` é derivada
  de marca explícita no título/descrição e não é gravada; na ausência dela aparece como
  “Não definida”. Não se deduz urgência apenas do status ou da proximidade do prazo.
  Datas ausentes aparecem como “sem prazo”; nenhum horário ou duração é inventado. Se não
  houver tarefa vencendo hoje, isso é dito e as demais pendências abertas continuam
  listadas. “Não há tarefas abertas” só é retornado após a consulta real confirmar a lista
  vazia.
- A página Hoje apresenta todos os itens do plano, agrupados por faixa de prioridade, em
  vez de limitar a exibição a cinco tarefas. A área permanece uma lista sequencial, não
  um calendário com blocos horários.
- O modelo de tarefas atual não tem relações formais de dependência nem estimativa de
  duração/horário de trabalho. A resposta explicita essa limitação e usa somente estados
  já registrados; não inventa dependências.
- A intenção conhecida é detectada pelo backend antes da inferência de ferramentas. Assim,
  Gemini e Ollama chegam ao mesmo plano determinístico; falhas de um provedor não acionam
  fallback nem alteram essa consulta.
- A consulta é somente leitura e não muda status, prazo, responsável ou cliente. Criar ou
  alterar tarefa continua usando o fluxo existente de confirmação.

## Testes

Os casos em `tests/test_today_service.py`, `tests/test_assistant_service.py`,
`tests/test_assistant_provider_parity.py` e `tests/test_today_routes.py` usam SQLite
isolado e títulos/clientes sintéticos. Cobrem ordenação e motivos, vencidas, hoje, futuro,
sem prazo, estados, cliente vinculado e vínculo pendente, mais de 50 itens, quadro vazio,
consulta sem escrita, página Hoje sem truncamento, frases naturais, continuidade por voz
(mesmo texto/serviço com `source="voice"`) e caminho determinístico com Gemini e Ollama.
O tempo real da transcrição no microfone, TTS audível e retorno contínuo da captura não é
validado por esses testes.

## Validação da interface

A API e os testes da interface automatizados confirmam a consulta. A verificação manual
no navegador/microfone permanece pendente quando não houver sessão de navegador
controlável disponível; HTTP 200, testes de serviço e captura simulada não comprovam
microfone nem fala audível.
