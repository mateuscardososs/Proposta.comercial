# Validacao de latencia e qualidade

Data: 01/10/2026. A bateria usou o Ollama real e um SQLite temporario recriado para
cada caso. Nenhum banco, documento ou volume operacional foi acessado. Os relatorios
brutos ficaram em `/tmp/assistant-benchmark-before.json` e
`/tmp/assistant-benchmark-final-verified.json` e nao fazem parte da aplicacao.

## Ambiente

- MacBook Air Apple M5, 10 nucleos, arm64, 16 GB de RAM e 148 GiB livres.
- macOS 26.6.2; Python 3.12.14 no `.venv`.
- Ollama 0.35.0 em `127.0.0.1:11434`.
- `qwen3:4b-instruct-2507-q4_K_M`, Q4_K_M, download local de 2,5 GB.
- Fuso operacional `America/Recife`.

Nao houve troca nem download de modelo.

## O que passou a ser medido

Cada inferencia registra espera na fila, duracao HTTP, duracao total do Ollama,
carregamento, avaliacao do prompt, geracao, tokens de entrada e saida, quantidade de
mensagens/caracteres, tamanho dos contratos, resultado validado e categoria de reparo.
O servico registra tambem as ferramentas efetivamente executadas. STT e TTS retornam
espera na fila, processamento e total separadamente.

Esses registros nao contêm prompts completos, respostas rejeitadas, raciocinio interno,
audio, token de confirmacao ou segredo. A telemetria da conversa fica em
`assistant_messages.details_json` para auditoria local.

## Antes e depois

Cada caso foi executado duas vezes com os mesmos dados sinteticos. `Tempo` e o total do
caso; continuidade tem duas mensagens e criacao/correcao tem tres. `Inf.` e o numero de
inferencias no caso.

| Caso | Antes mediana / pior | Depois mediana / pior | Acerto antes -> depois | Inf. antes -> depois |
|---|---:|---:|---:|---:|
| Conversa geral | 4,21 / 6,49 s | 1,41 / 1,89 s | 2/2 -> 2/2 | 1 -> 1 |
| Continuidade e mudanca de assunto | 6,49 / 6,72 s | 5,24 / 5,39 s | 2/2 -> 2/2 | 2 -> 2 |
| Consulta com recomendacao | 7,61 / 7,78 s | 4,18 / 4,58 s | 0/2 -> 2/2 | 2 -> 1 |
| Criacao e correcao | 3,73 / 3,87 s | 4,34 / 4,49 s | 2/2 -> 2/2 | 2 -> 2 |
| Tecnica: tara | 3,23 / 3,42 s | 4,83 / 4,92 s | 1/2 -> 2/2 | 1 -> 1 |
| Tecnica: calibracao e verificacao | 4,13 / 4,58 s | 2,99 / 3,15 s | 0/2 -> 2/2 | 1 -> 1 |

No resultado final, a mediana por mensagem ficou entre 1,41 e 4,83 s; o pior turno foi
4,92 s. Assim, esses casos comuns ficaram abaixo da meta inicial de 5 s depois da
transcricao. Isso nao e garantia para toda pergunta. O primeiro caso da linha de base
incluiu 1,79 s de carregamento do modelo e chegou a 6,49 s; com o modelo carregado,
`load_duration` ficou proximo de 1 ms.

O prompt inicial caiu de aproximadamente 2.310--2.323 tokens para 1.492--1.504 nos
casos gerais medidos. Os contratos iniciais cairam de 5.866 para 4.106 caracteres; a
redacao depois de consulta usou cerca de 493 caracteres de contrato. A fila ficou praticamente zerada na
bateria de um usuario, mas agora pode ser distinguida do processamento sob concorrencia.

## Correcoes de qualidade

- A consulta ampla com recomendacao e reconhecida deterministicamente pelo backend,
  consulta o quadro uma vez e usa uma inferencia somente para redigir a recomendacao.
- O backend aplica a ordenacao real de prioridade mesmo se o modelo omitir a opcao e
  fornece `priority_position`, atraso e distancia em dias como dados estruturados.
- Alegar que o quadro esta vazio sem consulta real passou a ser rejeitado como reparo
  factual, nao cosmetico.
- Consequencias comerciais nao presentes na consulta sao removidas da resposta gerada;
  o ajuste fica auditavel como `grounding_adjustment`, sem disparar outra inferencia.
- Contexto duplicado e contratos que nao podem ser usados no estado atual foram removidos.
- Confirmacao e cancelamento inequívocos continuam deterministicos, sem inferencia.
- A geracao passou a ter limite configuravel (`OLLAMA_MAX_OUTPUT_TOKENS=180`).
- Perguntas tecnicas correspondentes recebem fatos locais revisados; o modelo gera a
  redacao, mas nao e a fonte de validacao.

## Referencias tecnicas revisadas

- Tara, bruto e liquido: [OIML R 76-1, T.5.2](https://www.oiml.org/en/files/pdf_r/r076-1-e06.pdf).
- Calibracao e verificacao: [Inmetro, diferenca conforme o VIM](https://www.gov.br/inmetro/pt-br/acesso-a-informacao/perguntas-frequentes/acreditacao/qual-a-diferenca-de-calibracao-e-verificacao).

O conjunto ainda e pequeno. Para uma pergunta tecnica sem referencia correspondente, o
assistente deve declarar que nao ha fonte validada e evitar prescrever procedimento. A
validacao automatica confere pontos factuais minimos; um tecnico ainda precisa revisar
utilidade, contexto e seguranca de orientacoes antes de ampliar essa base.

## Streaming

Streaming nao foi implementado. Ele poderia antecipar a primeira frase visual e iniciar
TTS por frases completas, mas nao reduziria o tempo total e exigiria cancelamento e ordem
de audio adicionais. Como a reducao de prompt/inferencias levou todos os turnos desta
bateria a menos de 5 s e TTS ja era inferior a 0,7 s, o custo e o risco nao se justificaram
nesta etapa. O frontend continua exibindo processamento imediatamente e mostra texto antes
de solicitar sintese; envelopes internos e chamadas de ferramenta nunca seguem para TTS.

## Pendencias

- Teste humano no navegador: naturalidade, utilidade das recomendacoes, microfone real,
  pronuncia, eco e interrupcao.
- Medicao no Windows/Ryzen 7 3700U; nenhum numero do Mac foi extrapolado.
- Teste de concorrencia real com mais de um usuario, embora a fila limitada esteja coberta
  por teste automatizado.
- Ampliar referencias tecnicas somente apos revisao de fontes e de um responsavel tecnico.
- Se o Ryzen nao atingir a meta, comparar um modelo por vez usando este mesmo benchmark,
  medindo RAM, quantizacao, tokens/s, acerto, reparos, licenca e tamanho; nenhum candidato
  deve ser baixado sem nova avaliacao de recursos.

## Verificacoes finais

- Python: 228 passaram e 2 foram ignorados.
- JavaScript: 17 passaram.
- Ollama real: teste de integracao passou.
- Voz real: nove verificacoes passaram em
  `/tmp/assistente-voz-latencia-final-2.json`; primeira sintese 0,608 s, primeira
  transcricao 1,809 s e primeira interpretacao 1,905 s. Correcao e confirmacao
  deterministicas levaram 0,005 s e 0,006 s no backend.
- Instancia 8011 final: a consulta real selecionou `Relatorio atrasado Alfa`, status
  `Servico feito — falta nota/pedido`, vencida em 29/09/2026, posicao 1 e responsavel
  Ana. A inferencia levou 2,197 s, com 1.027 tokens de entrada, 88 de saida, 493
  caracteres de contrato, uma consulta executada e nenhum reparo. O banco isolado
  permaneceu com cinco tarefas.
