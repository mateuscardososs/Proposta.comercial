# Evolucao do assistente conversacional

## Diagnostico

A implementacao anterior tratava toda mensagem como um comando. O prompt exigia exatamente uma ferramenta, `responder_conversa` tinha um papel estreito e uma consulta terminava em uma lista montada pelo backend. O modelo nunca recebia o resultado da consulta para interpreta-lo. Isso limitava relatos livres, explicacoes, pedidos com mais de uma intencao e retomadas de contexto.

O historico recente ja era persistido por conversa, mas o rascunho de tarefa pendente nao era enviado ao provedor como estado estruturado. Na voz, a resposta textual ja aparece antes da sintese; os principais riscos observados sao o corte de pausas naturais e a leitura de Markdown, identificadores e diagnosticos tecnicos.

## Alternativas consideradas

1. **Ciclo conversacional limitado (escolhida).** O modelo responde naturalmente ou pede uma ferramenta validada. Consultas somente de leitura podem ser executadas e devolvidas ao modelo para uma resposta fundamentada. O numero de rodadas e limitado.
2. **Um plano com varias ferramentas em uma unica resposta.** Reduz chamadas, mas mistura planejamento e fatos ainda nao consultados e mostrou-se mais fragil para o modelo local pequeno.
3. **Loop de agente aberto.** E mais flexivel, porem aumenta latencia e risco de repeticao, especialmente no destino sem GPU dedicada.

## Desenho aprovado

O backend continua sendo a unica fronteira com o sistema e o Ollama permanece local. Em cada mensagem:

1. carrega o historico recente e o estado estruturado do ultimo rascunho;
2. pede ao modelo uma resposta natural ou uma ferramenta permitida;
3. valida os argumentos da ferramenta;
4. para uma consulta, resolve cliente, responsavel e datas no backend e consulta os servicos reais;
5. devolve ao modelo um resultado estruturado e auditavel;
6. aceita uma resposta natural fundamentada, outra consulta distinta dentro do limite ou a preparacao de uma tarefa;
7. para qualquer gravacao, preserva o fluxo unico de rascunho, confirmacao, idempotencia e reconciliacao.

Sao permitidas no maximo duas consultas por mensagem e tres chamadas ao modelo. Consultas repetidas sao interrompidas. Quando nao houver consulta ou acao necessaria, texto natural e uma saida valida e nao precisa ser embrulhado em `responder_conversa`.

Resultados de ferramentas sao dados nao confiaveis para o modelo, nao instrucoes. A resposta final nao pode introduzir identificadores, datas ou status de tarefas ausentes dos resultados, nem alegar uma operacao que nao foi executada. Se a sintese falhar na validacao, o backend mostra o resultado deterministico da consulta; nenhuma gravacao e repetida.

O contexto permanece restrito ao identificador da conversa. Nao ha memoria global nem entre usuarios. Referencias ambiguas devem gerar uma pergunta, nunca uma lembranca inventada.

## Voz

A pausa de fim de fala continua configuravel e passa a ter um padrao mais tolerante. A resposta aparece na tela antes da sintese. O texto falado remove Markdown, links, identificadores tecnicos e detalhes de diagnostico; listas extensas continuam resumidas em voz e completas na tela.

Streaming de texto e sintese por frases nao sera adicionado nesta entrega: o endpoint do Ollama atual responde de uma vez e a sintese local medida anteriormente e curta em comparacao com a inferencia. Fragmentar audio aumentaria problemas de ordenacao e cancelamento sem atacar o gargalo principal.

A interrupcao por voz durante a reproducao tambem nao sera habilitada. Sem cancelamento de eco confiavel, o proprio audio pode ser transcrito como confirmacao. O botao **Interromper audio** permanece, e o controle de geracao descarta respostas ou audios atrasados ao encerrar a conversa.

## Limites preservados

O assistente nao envia mensagens, nao registra atendimentos, nao opera documentos, notas ou financeiro e nao altera nem exclui tarefas existentes. Ele pode, contudo, conversar sobre essas situacoes, organizar ideias e redigir textos sem afirmar que executou a funcao indisponivel.
