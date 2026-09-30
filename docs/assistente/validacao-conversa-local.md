# Validacao da correcao conversacional local

Data: 30/09/2026. A validacao usou apenas a instancia isolada em
`127.0.0.1:8011`, bancos SQLite dentro de
`/tmp/ad-balancas-voice-manual.VnwzuO` e clientes ficticios. A aplicacao da
porta 8000, seu banco, documentos e volumes nao foram alterados.

## Causas confirmadas

1. O prompt obrigava toda mensagem a virar uma entre seis ferramentas
   operacionais. Saudacoes e perguntas sobre capacidades caiam em
   `consultar_tarefas`, produzindo a resposta inutil de quadro vazio.
2. Texto e voz eram inicializados pelo mesmo modulo inline. Uma falha ao
   carregar a voz podia impedir o registro dos eventos do chat.
3. O chat nao possuia timeout, leitura defensiva de JSON nem retry com o mesmo
   `request_id`; uma falha podia deixar a interface sem recuperacao clara.
4. O botao de voz aguardava `getUserMedia` sem indicador de nivel ou mensagens
   distintas para permissao negada, microfone ausente e dispositivo ocupado.
5. O Qwen pequeno alterna entre `tool_calls` nativo e o nome da ferramenta com
   JSON no texto. O segundo formato era rejeitado mesmo quando era seguro e
   validavel.
6. O historico como sequencia de turnos fazia o modelo repetir a ultima
   ferramenta. O historico passou a ser contexto JSON delimitado, com o pedido
   atual e a ultima resposta destacados.
7. Em uma explicacao de consulta, o modelo chegou a trocar `A fazer` por
   `Em andamento`. Datas, IDs e status de uma resposta conversacional sobre
   tarefas agora sao conferidos contra o resultado real antes da resposta.

## Ambiente e isolamento

- MacBook Air Apple M5, arm64, 16 GB de RAM.
- Ollama nativo 0.35.0 em `127.0.0.1:11434`, sem bind externo.
- Modelo `qwen3:4b-instruct-2507-q4_K_M`, Q4_K_M, 2,5 GB, Apache 2.0.
- FastAPI em `127.0.0.1:8011`.
- Banco deixado para teste manual:
  `/tmp/ad-balancas-voice-manual.VnwzuO/manual-ready.sqlite3`.
- Arquivos de teste:
  `/tmp/ad-balancas-voice-manual.VnwzuO/output-ready`.
- Clientes: `Alfa Servicos Teste` e `Alfa Servico Industrial Teste`.
- Voz local: faster-whisper small em CPU/int8 e Piper
  `pt_BR-faber-medium`.

## Casos reais executados

As chamadas 1 a 12 passaram pelo endpoint FastAPI real e pelo Ollama real. Os
tempos abaixo sao do Mac e nao estimam desempenho no Ryzen.

| Caso | Resultado real | Latencia observada |
|---|---|---:|
| Oi, boa tarde. | `Boa tarde! Como posso ajudar voce hoje?` | 1,065 s |
| Quem e voce? | Explicou consulta, criacao e correcao de rascunhos. | 2,428 s |
| Como pode ajudar? | Resposta natural com as capacidades atuais. | 4,847 s |
| Tarefas de hoje, quadro vazio | `Nao ha tarefas cadastradas...` | 0,866 s |
| Perdido com a organizacao | Sugeriu listar prioridades e perguntou se deveria consultar o quadro. | 1,869 s |
| Criar relatorio amanha | Preparou confirmacao para 01/10/2026. | 1,108 s |
| Na verdade, depois de amanha | Atualizou o mesmo rascunho para 02/10/2026. | 1,609 s |
| Pode criar | Criou a tarefa real `#1` uma unica vez. | 0,014 s |
| Quais tarefas agora? | Consultou e retornou `#1`, `A fazer`, 02/10/2026. | 1,282 s |
| O que voce quis dizer? | Apos a correcao final, explicou a ultima consulta preservando tarefa, status e data. | 1,174 s |
| Ler e-mails | Informou a limitacao sem afirmar acesso ou execucao. | 1,713 s |
| Cancela | Cancelou um segundo rascunho; nenhuma tarefa adicional foi criada. | 0,006 s |
| Ollama indisponivel | Conexao local recusada gerou erro especifico, sem fallback. | 0,007 s |
| Timeout e retry | O cliente expirou; retry com o mesmo `request_id` reconciliou a mesma acao em 0,007 s. O rascunho foi cancelado ao final. | 4,0 s de espera controlada |

A base pronta para teste manual contem exatamente uma tarefa sintetica criada
no fluxo acima. Os rascunhos dos casos de cancelamento e timeout ficaram
cancelados. Nao houve duplicacao.

## Validacao automatizada

- Contratos e provedor cobrem `responder_conversa`, fallback textual validado,
  historico delimitado, ferramenta restrita para explicacao, recuperacao
  limitada e rejeicao de status inventado.
- Servico cobre conversa persistida, historico no turno seguinte, bloqueio de
  alegacao de acao nao executada, quadro vazio e prazo inventado pelo modelo.
- JavaScript cobre feedback imediato, timeout, HTTP/JSON/resposta vazia,
  `finally`, retry idempotente, erros de microfone, nivel de audio, callbacks
  tardios e falha de TTS sem reenvio da acao.

Regressao final: 193 testes Python passaram, 2 foram ignorados e 17 testes
JavaScript passaram. A integracao real de voz com audio sintetico tambem
passou: Piper gerou audio, faster-whisper transcreveu, Ollama preparou e
corrigiu o rascunho, uma unica tarefa foi salva apos `Pode criar`, confirmacao
repetida nao duplicou e `Cancela` nao criou tarefa. Na primeira fala dessa
rodada, TTS levou 0,586 s, STT 1,660 s e o assistente 1,096 s. Esse teste nao
substitui fala humana e clique real no navegador.

## Teste manual pendente

Nao havia navegador controlavel nem microfone humano disponivel nesta sessao.
Permanecem pendentes a verificacao visual do clique, a permissao real do
navegador, a fala humana e a ausencia de erros no console. Roteiro:

1. Abra `http://127.0.0.1:8011/web/assistente` com recarga sem cache
   (`Cmd+Shift+R`).
2. Envie `Boa tarde` e confirme mensagem do usuario, indicador de processamento
   e resposta natural.
3. Pergunte `Quais tarefas eu tenho agora?` e confira a tarefa `#1`.
4. Clique `Iniciar conversa`; o texto deve mudar imediatamente para
   `Solicitando acesso ao microfone...`.
5. Permita o microfone, confira `Ouvindo` e o medidor de nivel; fale uma consulta
   e acompanhe transcricao, processamento e reproducao.
6. Encerre durante uma resposta e confirme que audio e microfone nao retomam.
7. Negue a permissao em uma segunda tentativa e confira a orientacao especifica.

## Limites mantidos

O assistente nao le e-mail, nao altera tarefas existentes, nao registra
atendimentos, nao exclui dados, nao opera financeiro e nao emite documentos ou
notas. Continua restrito ao computador local porque a aplicacao nao possui
autenticacao efetiva.
