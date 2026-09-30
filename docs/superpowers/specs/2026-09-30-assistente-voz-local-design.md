# Assistente por voz local — desenho aprovado

## Objetivo e escopo

Adicionar a primeira experiencia de conversa por voz ao assistente operacional existente. Uma sessao permite falar uma solicitacao, ver a transcricao, reutilizar o mesmo endpoint textual para consultar ou preparar tarefas, ouvir uma resposta curta e continuar falando para esclarecer, corrigir, confirmar ou cancelar.

Esta etapa nao adiciona novas operacoes de negocio. Criacao de tarefa continua passando por `AssistantService`, acao pendente, confirmacao e idempotencia existentes. Pagamentos, exclusao, documentos, atendimento, edicao de tarefas existentes, palavra de ativacao e interrupcao natural por voz permanecem fora do escopo.

## Decisoes

- Componentes de voz opcionais dentro do processo FastAPI.
- Interfaces independentes `AudioTranscriber` e `SpeechSynthesizer` permitem trocar implementacoes sem alterar rotas ou regras de negocio.
- faster-whisper 1.2.1 com modelo `small`, dispositivo `cpu` e `compute_type=int8` para transcricao multilíngue.
- Piper 1.8.0 com voz `pt_BR-faber-medium` para sintese WAV local.
- Dependencias pesadas ficam em `requirements-voice.txt`; sem elas, a pagina e o chat textual continuam funcionais e informam que voz esta indisponivel.
- Modelos ficam fora do Git em diretorio configuravel. O download inicial estimado e de 486,2 MB para Whisper e 63,2 MB para a voz Piper, abaixo do limite autorizado de 2 GB.
- Nenhuma API paga, reconhecimento remoto do navegador, envio de audio ou fallback para nuvem.

## Licencas

- `faster-whisper`: MIT.
- `Systran/faster-whisper-small`: MIT; conversao do Whisper small para CTranslate2.
- `piper-tts`: GPL-3.0-or-later.
- repositorio `rhasspy/piper-voices`: identificado como MIT.
- `pt_BR-faber-medium`: dataset de origem CC0 segundo o `MODEL_CARD`; a documentacao de implantacao deve manter a referencia ao modelo, ao dataset e ao repositorio.

O Piper foi aprovado apenas para uso interno da AD Balancas em computadores proprios. Uma futura venda, distribuicao a terceiros ou empacotamento comercial exige nova revisao de licencas antes da entrega.

## Arquitetura

```text
MediaDevices/getUserMedia
        |
        v
MediaRecorder + detector local de voz/silencio
        |
        v
POST /api/assistant/voice/transcriptions
        |
        +-- validacao de bytes, contêiner, faixa e duracao com PyAV
        +-- arquivo temporario removido em finally
        +-- AudioTranscriber -> FasterWhisperTranscriber
        |
        v
texto exibido e enviado a POST /api/assistant/messages
        |
        v
AssistantService existente -> regras/confirmacao/idempotencia
        |
        v
POST /api/assistant/voice/speech
        |
        +-- texto falado curto e validado
        +-- SpeechSynthesizer -> PiperSpeechSynthesizer
        |
        v
audio WAV reproduzido no navegador
```

Nao existe endpoint alternativo de criacao. A transcricao sempre entra no mesmo `/api/assistant/messages` usado pelo formulario textual, com `conversation_id` e `request_id` gerados no navegador.

## Componentes do backend

### Contratos

`app/assistant/voice/provider.py` define:

- `AudioTranscriber.transcribe(path: Path) -> TranscriptionResult`;
- `SpeechSynthesizer.synthesize(text: str) -> SynthesizedAudio`;
- erros tipados de indisponibilidade, conteudo invalido, silencio e saturacao;
- metadados seguros de duracao, idioma e tempo, sem audio bruto ou raciocinio de modelo.

### Validacao de audio

`app/assistant/voice/audio.py` recebe o upload em blocos, interrompe ao exceder o limite de bytes e usa `av.open` para inspecionar o conteiner real. Somente um arquivo com exatamente uma faixa de audio decodificavel e aceito. A duracao e calculada durante a decodificacao por amostras, nao apenas por metadados declarados; a leitura para e retorna erro assim que o limite e ultrapassado.

Limites iniciais configuraveis:

- 8 MiB por trecho;
- 30 segundos por fala;
- minimo de 250 ms de audio;
- 60 segundos para transcricao;
- 30 segundos para sintese;
- uma inferencia ativa e no maximo uma esperando por componente.

Todo temporario e criado fora dos diretorios operacionais e removido em `finally`, inclusive quando validacao, transcricao ou timeout falham. Audio bruto nao e persistido nem registrado em log.

### Transcricao

`FasterWhisperTranscriber` carrega `WhisperModel` de forma preguiçosa uma unica vez. A configuracao inicial usa CPU/INT8, idioma `pt`, `beam_size=1`, `condition_on_previous_text=False` e VAD. A inferencia e protegida por capacidade limitada; quando o componente esta ocupado e a unica espera ja foi consumida, a rota retorna erro compreensivel em vez de formar fila ilimitada.

Transcricoes vazias, abaixo do tamanho minimo, com baixa probabilidade de fala ou compostas apenas por pontuacao nao chegam ao assistente. Confirmacoes curtas (`sim`, `pode criar`, `confirmo`, `cancela`) exigem sinais mais estritos de fala e idioma portugues; o backend nunca converte silencio ou ruido em confirmacao.

### Sintese

`PiperSpeechSynthesizer` carrega a voz ONNX configurada uma unica vez e devolve WAV em memoria. O texto de fala e derivado deterministicamente da resposta visivel: sucesso, confirmacao e erros curtos podem ser lidos integralmente; listas longas sao reduzidas a uma contagem e a frase “Os detalhes estao na tela”.

Falha de sintese nunca desfaz nem repete a resposta textual ou a tarefa criada. O navegador conserva o texto falado e oferece “Repetir audio”, que chama apenas `/api/assistant/voice/speech`.

### Execucao assíncrona e capacidade

As rotas de voz sao `async`, mas validacao/decodificacao, transcricao e sintese executam por `run_in_threadpool`/`anyio.to_thread.run_sync`. Os componentes usam um limitador de capacidade com aquisicao temporizada e uma trava de inferencia, impedindo bloqueio do event loop e fila ilimitada. Timeouts de espera e processamento sao configuraveis e retornam 429/503/504 conforme saturacao, indisponibilidade ou tempo excedido.

## Endpoints

- `GET /api/assistant/voice/status`: informa disponibilidade de transcricao e sintese, modelos configurados e limites publicos, sem caminhos locais sensiveis.
- `POST /api/assistant/voice/transcriptions`: multipart com um arquivo; retorna texto, idioma, confianca, duracao do audio e milissegundos de transcricao.
- `POST /api/assistant/voice/speech`: JSON com texto visivel e tipo de resposta; retorna `audio/wav` e cabecalhos de tempo. Nao interpreta nem executa acoes.

As rotas permanecem sob o mesmo bind local e sem CORS adicional. A ausencia de autenticacao continua bloqueando publicacao externa.

## Maquina de estados no navegador

Estados: `idle`, `requesting_permission`, `listening`, `transcribing`, `processing`, `speaking`, `stopped` e `error`.

1. “Iniciar conversa” solicita o microfone uma vez e mantem o `MediaStream` durante a sessao.
2. Um analisador Web Audio detecta inicio e fim de fala. Apos cerca de 1,2 s de silencio, o `MediaRecorder` encerra e envia o trecho automaticamente.
3. “Encerrar fala” permite finalizar manualmente o trecho atual.
4. Durante transcricao, interpretacao e sintese, nao ha gravacao ativa.
5. Durante reproducao, o capturador permanece suspenso para evitar eco.
6. Ao terminar o audio, uma nova escuta inicia somente se a sessao ainda estiver ativa e o ciclo pertencer a geracao atual da sessao.
7. “Interromper audio” pausa e descarta a reproducao, retornando a escuta se a sessao continuar ativa.
8. “Encerrar conversa” incrementa a geracao, aborta `fetch` pendente, para gravador/analisador/audio, cancela temporizadores, fecha `AudioContext` e chama `stop()` em todas as faixas. Respostas tardias nao reproduzem audio nem reiniciam microfone.
9. O formulario textual permanece utilizavel fora de uma etapa de envio e compartilha o mesmo historico/conversa.

O navegador negocia `audio/webm;codecs=opus`, depois `audio/mp4`, `audio/webm` e o tipo padrao suportado. O backend nao confia nesse valor e valida o conteudo real.

## Interface visual

Intencao: permitir que o operador converse sem perder a previsibilidade da interface textual. A hierarquia continua centrada no historico; “Iniciar conversa” e a acao principal, enquanto controles de fala e audio sao secundarios. Paleta, tipografia, raios, sombras, cards e botoes reutilizam integralmente `base.html`.

Uma faixa compacta acima do historico mostra disponibilidade e estado da voz. Os controles tem alvos minimos de 44 px, foco visivel, textos claros e `aria-live`. Nao sera criado novo tema, componente visual externo ou frontend paralelo.

Microfone exige contexto seguro: funciona em `localhost`/`127.0.0.1`; fora disso, navegadores exigem HTTPS. Isso nao autoriza expor a aplicacao na rede.

## Testes

Testes de unidade e rotas cobrem contratos, validacao por conteudo, bytes, duracao durante decode, silencio, transcricao suspeita, indisponibilidade, saturacao, timeout, sintese e texto curto. Testes do JavaScript exercitam a maquina de estados por funcoes extraidas ou, se o projeto mantiver script inline, por um harness de navegador controlado sem testar detalhes irrelevantes.

Integracao real usa banco SQLite e diretorios temporarios, faster-whisper e Piper reais. Audio sintetico gerado pelo Piper valida o caminho WAV -> transcricao -> endpoint textual -> resposta -> WAV. Criacao, correcao e confirmacao usam a mesma conversa e devem produzir exatamente uma tarefa. Uma gravacao humana local sera usada apenas se houver acesso real ao microfone; caso contrario, a entrega inclui roteiro manual e nao afirma qualidade auditiva ou permissao real.

Tempos sao medidos separadamente para validacao/decodificacao, transcricao, Ollama, sintese e tempo total ate o WAV estar disponivel. Nenhum resultado do Mac sera extrapolado para o Ryzen.

## Operacao e Windows

Mac e Windows usam Python 3.12 e processamento CPU. `piper-tts` 1.8.0 publica wheels arm64 para macOS e amd64 para Windows; CTranslate2 publica wheels para ambos. Docker nao e o caminho inicial para voz: modelos e dispositivos de audio permanecem no host, e o FastAPI nativo e a instalacao validada primeiro.

Variaveis configuram ativacao, caminhos/cache, modelos, dispositivo, tipo de computacao, limites, timeouts, concorrencia, idioma e parametros de silencio. Nenhum modelo e embutido no Git ou na imagem Docker.
