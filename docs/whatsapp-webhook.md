# Entrada de mensagens do WhatsApp

O AD Balanças recebe mensagens somente pela integração oficial WhatsApp Business Platform Cloud API da Meta. A implementação usa o webhook oficial: no cadastro do endpoint, o `GET` valida `hub.mode=subscribe` e o token de verificação e devolve `hub.challenge`; nas notificações `POST`, valida `X-Hub-Signature-256` como HMAC-SHA256 do corpo bruto usando o app secret. O corpo não é reserializado antes da validação.

Referências oficiais consultadas:

- [Meta — WhatsApp Cloud API, referência de payloads de webhook](https://www.postman.com/meta/whatsapp-business-platform/folder/tduohwq/webhook-payload-reference)
- [Meta — exemplo de validação de assinatura de webhook](https://github.com/fbsamples/whatsapp-api-examples/blob/main/signature-validation-with-webhooks-payloads/app.py)

## Configuração

Adicione os valores no arquivo local de ambiente da aplicação, fora do Git. Não os coloque na configuração Yahoo (`.env.yahoo.local`) nem em arquivos versionados:

```dotenv
WHATSAPP_WEBHOOK_ENABLED=false
WHATSAPP_APP_SECRET=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_WEBHOOK_MAX_PAYLOAD_BYTES=1048576
WHATSAPP_WEBHOOK_MAX_MESSAGES=100
WHATSAPP_MESSAGE_PREVIEW_CHARS=400
```

`WHATSAPP_APP_SECRET` é o segredo do app Meta usado na assinatura; `WHATSAPP_VERIFY_TOKEN` é um token aleatório criado para o handshake. Os dois são independentes de tokens da Cloud API e das credenciais IMAP. O padrão permanece desligado, inclusive quando segredos estão presentes.

O endpoint é `GET` e `POST /webhooks/whatsapp`. A autenticação por sessão é isenta somente para esses dois métodos e esse caminho exato. Quando habilitada, o handshake compara o token em tempo constante; o POST compara o HMAC sobre os bytes recebidos em tempo constante. Payloads acima do limite, com mais mensagens que o limite configurado, assinatura inválida ou estrutura inválida são recusados. Não há endpoint de envio nem resposta automática.

## O que é armazenado

O payload completo não é persistido. Uma mensagem de texto é reduzida a uma prévia truncada ao limite configurado (400 caracteres por padrão), ID estável da mensagem Meta, identificador do remetente, horário, provedor/origem e estado de revisão. Mídias não são baixadas; a fila recebe apenas indicação de que existe uma mídia daquele tipo. Metadados de status sem mensagem não criam item.

Cada item entra em `E-mails e mensagens` como `other_review`, baixa confiança e destino `review`. O ID Meta usa a constraint já existente `(provider, mailbox_key, reference)` com provedor `whatsapp_cloud`, o que torna retries idempotentes sem nova tabela ou migração. A recepção não chama o classificador de e-mail, Gemini, sincronizador Yahoo, nem cria tarefas, clientes, rascunhos financeiros ou lançamentos. Uma pessoa pode revisar o conteúdo depois pelas rotas existentes da fila; qualquer ação operacional continua sujeita às confirmações atuais.

O texto limitado da mensagem é armazenado para permitir triagem humana. Ele não deve ser incluído em logs, métricas, telemetria ou relatórios técnicos. Não mantenha cópias do payload bruto.

## Limite de rede nesta instalação

A aplicação atual escuta somente em `127.0.0.1:8013`. A Meta não consegue entregar webhooks a um endereço loopback. Não abrir porta, criar túnel ou publicar a aplicação faz parte da configuração de segurança atual. Portanto, a implementação pode ser validada apenas com payloads sintéticos; mensagens reais não chegarão até que a empresa defina e aprove uma entrada pública HTTPS segura, com controles de borda e operação apropriados. Não habilite a opção em produção local esperando receber mensagens.

Não reinicie a aplicação para habilitar o recurso nesta entrega. Antes de ativação futura, valide os segredos localmente, defina a estratégia de endpoint HTTPS público e retenção, e revise autenticação, monitoramento e resposta a incidentes.
