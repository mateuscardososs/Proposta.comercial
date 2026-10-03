# Instancia 8013 com voz local

## Causa encontrada

A instância Docker anterior tinha `VOICE_ENABLED=false`, usava apenas `requirements.txt`
(sem faster-whisper/Piper) e não montava os modelos de voz no container. O Ollama do
Mac estava disponível somente em `127.0.0.1:11434`; portanto, o endereço
`host.docker.internal` configurado para o container não representava o mesmo caminho
loopback que a instalação nativa. A interface já continha captura, revisão/editável da
transcrição, cancelamento, tratamento de permissões e reprodução; ficava indisponível
porque o endpoint de status reportava voz desligada.

## Configuração atual

- A 8013 é servida pelo ambiente virtual do projeto e escuta em `127.0.0.1:8013`.
- A antiga imagem/container da 8013 foi mantida parada como referência; não iniciar
  enquanto o servidor nativo estiver usando a porta 8013.
- O Ollama existente (`qwen3:4b-instruct-2507-q4_K_M`) escuta somente em
  `127.0.0.1:11434`. O modelo foi verificado pela API local e respondeu a uma inferência
  sintética. Não houve download ou fallback externo.
- faster-whisper 1.2.1, Piper 1.8.0 e os modelos `Systran/faster-whisper-small`
  (CPU/int8) e `pt_BR-faber-medium` já estavam instalados no ambiente/model directory.
  Não foi necessário instalar dependências ou baixar modelos. Havia 137 GiB livres no
  volume de trabalho na verificação.
- O PostgreSQL Docker mantém o mesmo volume `propostacomercial_postgres_data`, mas sua
  porta publicada agora é `127.0.0.1:5433`. A porta local 5432 já pertencia a outro
  PostgreSQL do Mac; esse serviço não foi parado nem alterado. A conexão da 8013 foi
  testada contra `propostas_db` na porta 5433.
- Os campos de usuário e senha do Yahoo continuam vindo de `.env.yahoo.local`, fora do
  Git. A configuração não secreta do container anterior (incluindo habilitação,
  intervalo e chave da caixa) foi copiada para
  `../local-data/adbalancas-8013/private/settings.json`, modo `0600`. A URL do banco
  está em `../local-data/adbalancas-8013/private/database-url`, também modo `0600`.
  Esses arquivos não contêm a senha Yahoo; nenhum valor de credencial é registrado.
- Antes de recriar somente o container PostgreSQL para restringir a publicação da porta,
  foi salvo e verificado o backup
  `../local-backups/adbalancas-pre-voice-8013-20261003.dump` (106.473 bytes, 276 entradas
  no catálogo `pg_restore --list`, SHA-256
  `be0300fd98ba17ce6fe8ac269390960b32bd9cf9fc848925512ce2670aa6982c`). O volume não foi
  removido nem inicializado novamente.
- Sincronização Yahoo: habilitada, intervalo de 900 s e criação idempotente de tarefa
  mantidos. A chave existente `adbalancas-piloto-20261002` e o marco
  `2026-10-02 20:43:34.394255` foram preservados. O ciclo automático de inicialização
  terminou sem erro: 3 mensagens já sincronizadas, 0 vínculos novos e 24 tarefas.
  Não foi feita consulta manual à caixa. A leitura IMAP continua somente leitura.

## Inicialização e encerramento

Os dois arquivos privados já foram preparados para esta máquina. No terminal:

```bash
cd /Users/mateuscardoso/dev/pai/Proposta.comercial
PYTHONPATH=. .venv/bin/python scripts/run_assistant_8013_local.py
```

Abra <http://127.0.0.1:8013/web/assistente>. O botão de voz só habilita quando
transcrição e síntese locais passam pela verificação do backend. Encerre o processo com
`Ctrl+C` no terminal em que ele está rodando. Não use `docker compose up app` nem inicie
o container antigo enquanto a versão nativa estiver ativa.

O iniciador verifica que o Ollama/modelo estão disponíveis, que os modelos locais de voz
existem, que a configuração de sincronização mantém os 900 s e que a conexão é ao
PostgreSQL local correto. A seleção do modelo continua configurável por `OLLAMA_MODEL`;
quando ausente, o iniciador seleciona um modelo já instalado e confirma sua presença
pela API local. Não baixa modelos.

## Evidências

### Executado na instância 8013

- `GET /healthz`: `200`, saudável.
- `GET /api/assistant/voice/status`: voz ativa, faster-whisper e Piper disponíveis.
- `GET /web/assistente`: `200`; markup contém área de revisão de transcrição e carrega
  `assistant_voice_bootstrap.js`.
- Áudio sintético pt-BR foi sintetizado pelo Piper, enviado ao endpoint real de STT,
  e a transcrição/confiança (`0.62`) foram revisadas pelo cliente de validação antes de enviar ao
  endpoint de conversa. A resposta real do assistente foi sintetizada pelo Piper; o WAV
  retornado foi válido. O fluxo foi feito por API, sem afirmar validação de microfone ou
  reprodução pelo navegador.
- Consulta de quadro pela API respondeu `200` sem alteração de tarefas. O estado de
  capacidade indica leitura de e-mail configurada; nenhum corpo de e-mail real foi usado
  como conteúdo de teste.
- Silêncio e arquivo de áudio inválido foram recusados com HTTP `422`, sem encaminhar
  texto ao assistente.
- Ollama foi consultado por loopback. A inferência sintética inicial levou 2,29 s; a
  primeira síntese observada na 8013 levou 0,08 s.

### Executado isoladamente, com SQLite temporário, Ollama e componentes de voz reais

`scripts/validate_assistant_voice_local.py` usou Piper e faster-whisper reais, junto ao
Ollama real, em um banco temporário descartável. Passaram: revisão/correção do prazo,
confirmação única de criação, confirmação repetida sem duplicação, cancelamento sem
gravação, síntese da resposta, áudio inválido e silêncio. O tempo de STT foi 1,743 s na
primeira fala e 0,907/0,849 s nas seguintes; esses tempos não incluem o uso físico do
microfone no navegador.

Os testes de integração opt-in do Ollama usaram apenas mensagens sintéticas e um banco
SQLite isolado: 9 passaram, incluindo consulta de tarefa, solicitação de orçamento,
conta a pagar, nota fiscal, hoje/semana e serviço. Os testes de conversa/e-mail
determinísticos com leitor sintético passaram separadamente.

Os testes JavaScript da sessão de voz passaram (13), inclusive permissão negada,
dispositivo ausente, silêncio, revisão antes do envio, falha de STT, repetição sem nova
solicitação e encerramento ignorando respostas tardias. Os testes Python relevantes de
voz passaram (35) e os de e-mail/conversa sintética passaram (101).

## Limite de validação manual

Não havia navegador controlável nem captura física de microfone disponível durante esta
execução. Por isso, ainda falta o teste manual no navegador para autorização real do
microfone, gravação de fala humana, edição/cancelamento da transcrição na interface,
reprodução audível e encerramento físico da captura. As validações de permissão e ciclo
de vida são automatizadas; isso não equivale a validar o microfone real. Até esse teste,
não declarar a experiência de voz validada ponta a ponta no navegador.
