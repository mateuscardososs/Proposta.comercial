# Conversa direta por voz na 8013

Atualização de 2026-10-03. Este documento descreve o fluxo atual e prevalece sobre
as evidências históricas de revisão de transcrição em
`validacao-instancia-8013-voz.md`.

## Comportamento

- Ao iniciar, o navegador captura áudio em memória e mostra `Ouvindo`.
- Após pelo menos 2,5 s de silêncio contínuo, a captura do turno termina e o áudio vai
  ao endpoint local de transcrição. A transcrição segue automaticamente para o mesmo
  endpoint de conversa usado pelo chat digitado; não há botão para enviar/concluir fala.
- A interface mostra apenas os estados de voz (`Ouvindo`, `Pensando` e `Falando`), as
  mensagens reconhecidas do usuário e as respostas do Assistente. A fala reconhecida
  aparece como mensagem normal somente depois do envio automático; não há etapa de
  revisão/aprovação nem botão adicional de envio.
- O mesmo identificador de requisição é mantido em retries: a mensagem reconhecida é
  acrescentada uma vez no envio inicial e não é duplicada ao repetir a solicitação. O
  texto fica no histórico do chat para continuidade e aparece ao reabrir a conversa.
  Áudio não é persistido. Logs técnicos não devem registrar áudio nem transcrição.
- A transcrição é encaminhada pelo fluxo normal, que mantém a confirmação humana para
  criar tarefas e registros. A voz não confirma ações automaticamente. Financeiro,
  fiscal e demais salvaguardas permanecem inalterados.
- O backend continua recusando silêncio, ruído e respostas curtas de controle com baixa
  confiança, como “Pode criar”; nesse caso mostra um erro e permite falar novamente,
  sem revelar o texto reconhecido.
- Respostas do Ollama usam Piper local. Ao terminar o áudio, o microfone volta a ouvir
  automaticamente após um intervalo de proteção de eco de 500 ms. Captura pede ao
  navegador cancelamento de eco, supressão de ruído e controle automático de ganho. O
  botão `Interromper resposta` interrompe o áudio e retoma a escuta após a proteção.
- Silêncio prolongado sem fala não encerra a sessão; somente `Encerrar conversa` fecha
  a captura. O limite técnico de uma fala individual continua sendo 30 s.
- Em falha recuperável de STT, assistente ou TTS, o erro é mostrado e a mesma sessão
  volta a ouvir automaticamente; falha de permissão impede o início até nova tentativa.
- Repetição de uma requisição usa o mesmo identificador idempotente e mantém origem
  `voice`; repetição somente do áudio não repete a solicitação ao assistente.

## Validação

Em 2026-10-03, somente o processo identificado na porta 8013 foi reiniciado para carregar
as correções; o launcher confirmou `127.0.0.1:8013`, `/healthz` respondeu 200 e a página
responde com `Cache-Control: no-store` e URLs versionadas. O startup também retomou o
worker Yahoo já configurado (IMAP somente leitura); não foi feita consulta manual à caixa
nem usado conteúdo de e-mail como teste. Configurações e marco incremental não foram
alterados. Portas 8000 e 8011 não foram reiniciadas.

Com Ollama real (`qwen3:4b-instruct-2507-q4_K_M`), faster-whisper small CPU/int8 e
Piper `pt_BR-faber-medium`, `scripts/validate_assistant_voice_local.py` foi executado
com áudio sintético e SQLite temporário descartável. Uma fala geral percorreu STT →
Ollama (`kind=text`) → Piper (WAV válido). Também passaram criação somente após
confirmação, correção de prazo, confirmação repetida sem duplicidade, cancelamento e
rejeição de silêncio/áudio inválido. Na
execução sintética mais recente, o Piper levou 0,071 s na primeira síntese medida; STT
levou 1,378/1,095/0,929 s nas falas de tarefa. A tarefa sintética ficou somente no
SQLite temporário.

O teste manual com microfone, detecção de silêncio física e reprodução no navegador
continua pendente: não havia ferramenta de navegador controlável disponível nesta
sessão. Testes por API ou em Node não comprovam permissão de microfone nem saída audível
no navegador.

Na validação da exibição de transcrição e consulta da agenda passaram 34 testes
JavaScript; a suíte Python completa passou com 512 testes aprovados e 10 ignorados por
serem opt-in. Cobrem mensagem de voz no chat após envio automático, histórico, retry sem
duplicidade, retomada da escuta e consulta sintética sem depender do modelo.

O teste manual solicitado com microfone, pausa natural e fala audível permanece pendente:
nenhuma sessão de navegador controlável estava disponível. HTTP/API e testes simulados
não comprovam permissão física do microfone nem reprodução audível.

## Inicialização

O comando local existente permanece:

```bash
cd /Users/mateuscardoso/dev/pai/Proposta.comercial
PYTHONPATH=. .venv/bin/python scripts/run_assistant_8013_local.py
```

Abra `http://127.0.0.1:8013/web/assistente`. O PostgreSQL, configuração Yahoo, marco
de ativação e portas 8000/8011 não fazem parte desta mudança.
