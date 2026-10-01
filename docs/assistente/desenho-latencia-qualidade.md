# Desenho de latencia e qualidade do assistente

## Objetivo

Medir e reduzir a latencia depois da transcricao sem remover validacoes de dados,
permissoes, confirmacao ou idempotencia. A medicao deve separar tempo total de
tempo percebido e nunca persistir prompts completos, segredos ou raciocinio interno.

## Telemetria segura

Cada chamada ao Ollama produz um registro estruturado com:

- espera pelo limitador de concorrencia;
- duracao HTTP e duracoes informadas pelo Ollama (total, carga, avaliacao do prompt e geracao);
- quantidade de mensagens e caracteres de contexto;
- tokens de entrada e saida informados pelo Ollama;
- resultado validado (nome da ferramenta ou resposta natural);
- categoria do reparo, quando houver, e o custo da tentativa rejeitada.

O servico agrega as inferencias da mensagem, registra as ferramentas realmente
executadas e persiste somente esses metadados em `details_json`. Texto integral de
prompt, resposta rejeitada, raciocinio e credenciais nao fazem parte da telemetria.

STT e TTS registram separadamente espera na fila e processamento. Os tempos ficam
nos campos JSON ou cabecalhos de resposta para diagnostico local; o audio nao e
persistido pelo assistente.

## Fluxo otimizado

1. Confirmacao e cancelamento inequívocos continuam deterministicos e sem inferencia.
2. A primeira inferencia pode conversar ou solicitar exatamente uma ferramenta permitida.
3. Uma consulta e executada uma unica vez para os mesmos argumentos na mesma mensagem.
4. Depois da consulta, o modelo recebe apenas os resultados reais e a capacidade de
   responder naturalmente; os contratos de mutacao nao sao reenviados.
5. Reparos ocorrem apenas por formato invalido, ferramenta fora do escopo ou alegacao
   factual insegura. Preferencias cosmeticas, como concisao, nao rejeitam uma resposta valida.
6. Criacao, correcao e confirmacao continuam no fluxo existente; sucesso so e anunciado
   depois do `commit`.

## Streaming

Ollama consegue transmitir texto, mas chamadas de ferramenta precisam ser validadas
antes de aparecer ao usuario. Nesta etapa, streaming so seria seguro na redacao final,
depois das consultas. Ele melhora o primeiro sinal visual e pode alimentar TTS por frases,
mas nao reduz o tempo total da inferencia e adiciona riscos de fala obsoleta apos encerrar
a conversa. A decisao de implementa-lo depende das medidas posteriores: primeiro sera
reduzido o numero de inferencias e o tamanho do prompt. Nenhum envelope interno ou
chamada de ferramenta sera enviado ao sintetizador.

## Avaliacao

Um executor isolado repete os mesmos casos antes e depois e calcula mediana, pior tempo,
acerto e inferencias. Os grupos sao conversa geral, continuidade com mudanca de assunto,
consulta com recomendacao, criacao com correcao e duvidas tecnicas.

Respostas tecnicas nao serao classificadas como corretas pelo conhecimento do modelo.
Cada caso precisa de uma fonte revisada. Sem fonte aplicavel, o resultado esperado e
declarar a limitacao e evitar instrucoes operacionais inventadas.

## Limites

- Meta inicial: respostas comuns em ate 5 segundos depois da transcricao no Mac.
- A meta nao autoriza remover verificacoes ou reduzir seguranca.
- Medidas do Mac nao estimam o desempenho do Ryzen.
- Qualidade auditada por regras automaticas ainda precisa de avaliacao humana da
  naturalidade, utilidade e pronuncia.

