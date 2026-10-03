# Consulta de tarefas do Assistente

Atualizado em 2026-10-03.

## Comportamento

- Pedidos inequívocos de organização/consulta da agenda ou do quadro, como “organize
  minha agenda”, “olhe o quadro de tarefas e diga o que devo fazer hoje” e “mostre
  minhas tarefas abertas”, chamam o backend diretamente. Não dependem de o Ollama
  selecionar `consultar_tarefas`.
- A consulta usa a sessão SQLAlchemy da aplicação e `board_service.get_tasks`, a mesma
  origem do quadro, sem limite de resultados. Inclui todo status não concluído, inclusive
  tarefas atrasadas, de hoje, futuras, sem prazo, aguardando cliente e tarefas vinculadas
  a serviço/e-mail. Não lê ou altera conteúdo de e-mail.
- A ordem sugerida considera marcação explícita de urgência no texto da tarefa, prazo
  vencido, prazo de hoje, status administrativo de serviço, execução em andamento, prazo
  futuro, tarefa sem prazo e, por último, espera de cliente. A resposta informa uma razão
  curta verificável para cada posição.
- O quadro não armazena um campo próprio de prioridade. `Prioridade sugerida` é derivada
  de texto/status/prazo e não é gravada. Datas ausentes aparecem como “sem prazo”; nenhum
  horário ou duração é inventado. Se não houver tarefa vencendo hoje, isso é dito e as
  pendências abertas continuam listadas. “Não há tarefas abertas” só é retornado após a
  consulta real não encontrar status aberto.
- A consulta é somente leitura e não muda status, prazo, responsável ou cliente. Criar ou
  alterar tarefa continua usando o fluxo existente de confirmação.

## Testes

Os casos em `tests/test_assistant_service.py` usam SQLite temporário e títulos/clientes
sintéticos. Cobrem frases naturais reconhecidas, vários estados e prazos, tarefas sem
prazo, urgência explícita, mais de 50 tarefas, quadro realmente vazio e a mesma consulta
com `source="voice"`. O tempo real da classificação da voz no microfone não é validado
por esses testes; o texto transcrito segue o mesmo roteamento determinístico.

## Validação da interface

A API e os testes da interface automatizados confirmam a consulta. A verificação manual
no navegador/microfone permanece pendente quando não houver sessão de navegador
controlável disponível; HTTP 200, testes de serviço e captura simulada não comprovam
microfone nem fala audível.
