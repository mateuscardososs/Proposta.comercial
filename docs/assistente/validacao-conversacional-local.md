# Validacao conversacional local

> Atualizacao: a rodada de desempenho e referencias tecnicas de 01/10/2026 esta em
> `docs/assistente/validacao-latencia-qualidade.md`. Ela substitui os numeros de latencia
> e as limitacoes sobre `tara` registradas abaixo, que permanecem como linha de base historica.

Data: 30/09/2026 no Mac; os testes atravessaram a meia-noite UTC, mas o fuso operacional permaneceu `America/Recife`. Toda validacao usou SQLite e arquivos em `/tmp/ad-balancas-conversational.xFP65K`. Nenhum banco, documento ou volume operacional foi acessado.

## Ambiente

- MacBook Air Apple M5, 10 nucleos, arm64, 16 GB de RAM.
- 146 GiB livres durante a validacao.
- Ollama nativo 0.35.0, limitado a `127.0.0.1:11434`.
- Modelo existente `qwen3:4b-instruct-2507-q4_K_M`, Q4_K_M, 4B, cerca de 3,2 GB carregados, Apache 2.0.
- faster-whisper small em CPU/int8 e Piper `pt_BR-faber-medium`.
- FastAPI isolado em `127.0.0.1:8011`.
- Clientes ficticios `Alfa Industria`, `Alfa Servicos` e `Empresa Beta`; responsaveis ficticios `Carlos` e `Ana`.

Nao foi baixado nem comparado outro modelo.

## Resultados reais com Ollama

| Cenario | Resultado final | Latencia |
|---|---|---:|
| Relato longo de visita, ajuste e documentos pendentes | Organizou somente os fatos informados e perguntou o cliente, sem tentar registrar atendimento. | 3,58 s |
| Planejamento de relatorio, proposta e retorno | Sugeriu uma ordem e manteve o contexto da Alfa. | 9,87 s |
| Redacao curta, sem envio | Redigiu a mensagem e nao executou envio. | 3,04 s |
| Consulta real seguida de prioridade | Consultou o quadro, repetiu a ferramenta uma vez, foi contido pelo limite e produziu recomendacao fundamentada na terceira chamada. | 22,91 s |
| Pergunta geral simples | Respondeu sem ferramenta. | 4,67 s |
| Mudanca de assunto e retomada limpa | Depois de explicar outro tema, distinguiu corretamente que a ordem anterior era sugestao do assistente, nao escolha do usuario. | 1,92 s na retomada |
| Cliente ambiguo | Listou `Alfa Industria` e `Alfa Servicos`, sem inventar ID. | 3,02 s |
| Correcao de cliente e prazo | Completou o rascunho e mostrou 02/10/2026 antes da confirmacao. | 10,13 s antes do parser direto final |
| Confirmacao repetida | Criou a tarefa `#5` uma vez; a repeticao reconciliou a mesma tarefa. | 0,012 s / 0,004 s |
| Funcao de atendimento indisponivel | Bloqueou conversao silenciosa em tarefa e informou que nada foi executado. | 2,66 s |

As respostas e resultados de consulta ficaram vinculados a cada conversa. Resultados estruturados de ferramentas foram persistidos em `details_json`; tokens de confirmacao continuaram fora do historico.

## Erros encontrados e correcoes

1. O fluxo antigo obrigava toda mensagem a chamar uma ferramenta. Texto natural passou a ser uma saida valida.
2. A consulta terminava em lista fixa. O backend agora devolve o resultado estruturado ao modelo e permite ate duas consultas e tres chamadas totais.
3. O modelo repetiu a mesma consulta em vez de sintetizar. Uma ultima rodada sem `consultar_tarefas` produz a resposta; a consulta nao e executada novamente.
4. O modelo chegou a ecoar `HISTORICO_JSON` e outros marcadores internos. Provedor e servico agora rejeitam esse vazamento.
5. Em um relato, o modelo inventou calibracao, preco, periodicidade e anexos. O prompt passou a separar fatos do usuario, resultados reais e sugestoes; a repeticao produziu resposta sem esses detalhes.
6. O modelo atribuiu ao usuario uma sugestao anterior do assistente. A autoria ficou explicita no envelope; uma conversa nova distinguiu corretamente sugestao de decisao.
7. O modelo tentou converter `registrar atendimento` em criacao de tarefa e depois prometeu a criacao apenas em texto. A fronteira deterministica bloqueia atendimento, financeiro, exclusao, envio e emissao; uma resposta fora do escopo precisa declarar a limitacao.
8. `Na verdade, depois de amanha` foi respondido como conversa, sem corrigir o rascunho. Correcoes explicitas de prazo com rascunho pendente agora usam diretamente o parser validado do backend.
9. Cancelamento de rascunho em `needs_clarification` falhava. Esse estado agora pode ser corrigido ou cancelado sem criar tarefa.

## Voz real e desempenho

O teste de integracao usou audio sintetico do Piper, decodificacao e transcricao reais, FastAPI, Ollama e banco temporario:

- primeiro TTS: 0,603 s; seguintes: 0,053 s e 0,022 s;
- STT: 1,794 s, 0,911 s e 0,874 s;
- primeira interpretacao: 2,010 s;
- correcao deterministica do prazo: 0,005 s;
- confirmacao e persistencia: 0,007 s;
- audio invalido e silencio foram rejeitados;
- cancelamento por fala nao criou tarefa;
- confirmacao repetida nao duplicou a tarefa.

A pausa de fim de fala passou de 1200 para 1800 ms e permanece configuravel. A resposta textual aparece antes do TTS. Markdown, links, IDs de tarefa e diagnosticos tecnicos sao removidos do texto falado. Streaming e sintese por frases nao foram implementados: a medicao mostrou TTS abaixo de 0,7 s, enquanto as chamadas multiplas ao modelo chegaram a 22,91 s; fragmentar o audio nao atacaria o gargalo principal e aumentaria o risco de reproducao fora de ordem.

Interrupcao por voz durante reproducao nao foi habilitada porque nao ha cancelamento de eco confiavel. O botao **Interromper audio** permanece. Os testes JavaScript confirmam que encerrar incrementa a geracao, libera o microfone e descarta transcricao, resposta ou audio atrasados.

## Limitacoes observadas

- O modelo atual errou uma pergunta geral sobre `tara`, descrevendo-a como massa de calibracao. Conversa geral funciona, mas conhecimento tecnico nao consultado nao deve ser tratado como fonte confiavel.
- A consulta com recomendacao exigiu tres inferencias e levou 22,91 s no Mac. O Ryzen nao foi testado e nenhuma estimativa foi feita a partir do Mac.
- A primeira tentativa de planejamento ainda foi verbosa. O prompt melhorou concisao, mas o modelo 4B nem sempre segue o tamanho pedido.
- Uma conversa antiga contaminada por resposta incorreta produziu uma frase contraditoria antes da correcao; uma conversa nova passou. Nao ha resumo de longo prazo nem memoria entre sessoes.
- Nao houve navegador controlavel nesta sessao. Aparencia, permissao de microfone humano, eco real e clique no botao continuam pendentes para teste manual.

Antes de trocar o modelo, recomenda-se comparar o atual com um unico candidato maior em um teste controlado, registrando download, RAM, licenca e latencia no Ryzen. Nenhum modelo adicional foi baixado nesta etapa.

## Testes automatizados

- Python: 214 passaram e 2 foram ignorados.
- JavaScript: 17 passaram.
- Ollama ao vivo: classificacao de consulta passou.
- Voz real: todos os nove checks do runner passaram em `/tmp/ad-balancas-conversational.xFP65K/voice-validation-final.json`.

## Roteiro manual

1. Abra `http://127.0.0.1:8011/web/assistente` e recarregue sem cache.
2. Conte um relato longo com uma pausa natural no meio; confira que a fala nao e cortada antes de 1,8 s de silencio.
3. Peca ajuda para organizar o relato e depois para redigir uma mensagem, deixando claro que nao deve enviar.
4. Consulte tarefas e peca uma prioridade; confira os dados contra o quadro.
5. Prepare uma tarefa, corrija cliente ou prazo e confirme. Repita `Pode criar` e confira uma unica tarefa.
6. Durante a reproducao, clique **Interromper audio**; depois clique **Encerrar conversa** e confirme que microfone e audio nao retomam.
7. Diga `registre um atendimento`: deve informar a limitacao e nao criar rascunho nem tarefa.
