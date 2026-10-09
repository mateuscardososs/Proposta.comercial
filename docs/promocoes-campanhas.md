# Promoções por e-mail

## Fluxo

1. O usuário descreve a campanha em texto livre. Datas exatas, aproximadas e período omitido são aceitos; não há campo obrigatório de data.
2. O backend combina a descrição com `PROMOTION_MARKETING_BASE_PROMPT` e gera assunto/corpo pelo `GEMINI_MODEL`; gera a arte pelo modelo independente `GEMINI_IMAGE_MODEL`.
3. A imagem não é usada para reproduzir texto comercial. A prévia editável do assunto e corpo é a fonte revisável da mensagem. A imagem pode ser regenerada (com referência visual opcional) ou substituída por PNG/JPEG.
4. A página lista apenas contatos com e-mail válido e autorização vigente, mostra a quantidade selecionada e congela os endereços selecionados no rascunho.
5. Uma alteração cria nova revisão e invalida a confirmação anterior. O envio só começa com SMTP configurado e confirmação explícita da versão exibida.

A descrição da campanha e as referências visuais opcionais são enviadas à API Gemini. A lista de contatos e os endereços não são enviados ao Gemini. A referência visual enviada para geração não é retida pela aplicação; a imagem gerada e as revisões de texto ficam em `OUTPUT_DIR/promotions` e no banco, respectivamente. Não há limpeza automática/retention configurável nesta primeira versão; definir retenção e acesso administrativo é pendência antes de uso em escala.

## Elegibilidade e consentimento

`ClientCampaignContact` guarda um ou mais contatos associados ao cadastro de cliente. Um contato não recebe campanhas por padrão. Para tornar-se elegível, requer e-mail válido, ativo, autorização explícita, origem e data do consentimento. Os contatos legados não são convertidos e nenhum e-mail é inferido de Yahoo, proposta ou outro cadastro.

Autorizações e revogações são eventos append-only em `campaign_contact_consent_events`, com endereço capturado no evento; a preferência atual no contato é uma projeção para seleção rápida. Trocar e-mail de um contato autorizado exige uma nova confirmação explícita com origem e data. Uma revogação posterior remove o contato da lista e é revalidada imediatamente antes do envio. Se o endereço mudar após a seleção, o destinatário é suprimido para revisão. Endereços duplicados entre clientes selecionados bloqueiam a criação do rascunho em vez de escolher um cliente silenciosamente.

## Conteúdo e segurança

- O prompt de marketing proíbe inventar datas, preços, percentuais, descontos, garantias, certificações e condições. A validação determinística rejeita números/datas ou termos comerciais que não estejam sustentados pelo texto fornecido.
- A linguagem pode mencionar “condições especiais”, convidar a entrar em contato e agendar uma conversa; o usuário revisa o texto antes de qualquer envio.
- A arte é orientativa e não deve ser considerada fonte dos termos comerciais. Texto legível/valor/data na imagem não é uma forma autorizada de apresentar condições.
- Gemini recebe somente a descrição e, se o usuário escolher, uma referência PNG/JPEG limitada por `PROMOTION_MAX_REFERENCE_IMAGE_BYTES`. Referências SVG, caminhos locais arbitrários e anexos de e-mail não são aceitos.
- A chave é lida de `GEMINI_API_KEY`; não fica na URL, banco, histórico de conversa ou logs. Erros registrados na campanha são códigos curtos, não respostas completas do provedor.
- O IMAP Yahoo permanece separado e somente leitura. Nenhuma rotina de campanha lê, marca, move, exclui ou envia mensagens usando a conta IMAP.
- O sistema não cria propostas, relatórios ou lançamentos financeiros.

## Envio e idempotência

O transporte usa SMTP separado da entrada IMAP. `PROMOTION_SMTP_*` é opcional e vazio por padrão. O botão de envio fica desabilitado e o endpoint recusa o envio enquanto host, usuário, senha, remetente válido e TLS/SSL não estiverem configurados. A senha não deve ser colocada em `.env.example`; configure-a somente no arquivo de ambiente local ignorado pelo Git ou no mecanismo seguro do executor.

Um e-mail individual é enviado a cada destinatário, sem CC/BCC compartilhado. O banco registra campanha, revisão confirmada e cada resultado por destinatário. A chave única do rascunho evita campanha duplicada por retry; a chave única de campanha/e-mail evita duplicar destinatários. Antes da chamada SMTP, o estado `sending` é persistido. Se houver interrupção após isso, o resultado vira `unknown` na próxima verificação e não é reenviado automaticamente: SMTP não fornece garantia de entrega exatamente uma vez. O responsável precisa reconciliar o estado fora do sistema antes de qualquer nova campanha. Envios já aceitos não podem ser desfeitos.

Não há envio em testes automatizados. Os testes usam gerador/transportes simulados e banco isolado. Uma chamada de geração real Gemini e qualquer envio real são ações distintas; o segundo continua dependendo de configuração SMTP e confirmação humana.

## Configuração

```dotenv
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_IMAGE_MODEL=gemini-nano-banana-2.1
GEMINI_CONNECT_TIMEOUT=3
GEMINI_READ_TIMEOUT=60

# Saída independente de EMAIL_PROVIDER/EMAIL_IMAP_*
PROMOTION_SMTP_HOST=
PROMOTION_SMTP_PORT=587
PROMOTION_SMTP_USERNAME=
PROMOTION_SMTP_PASSWORD=
PROMOTION_SMTP_FROM_EMAIL=
PROMOTION_SMTP_FROM_NAME=AD Balanças
PROMOTION_SMTP_STARTTLS=true
PROMOTION_SMTP_USE_SSL=false
PROMOTION_SMTP_TIMEOUT_SECONDS=15
PROMOTION_MAX_REFERENCE_IMAGE_BYTES=8388608
```

O modelo de imagem inicial é configurável e fica separado do modelo de conversa. A documentação atual da API Gemini apresenta `gemini-nano-banana-2.1` como modelo de geração/edição de alta eficiência e documenta saída de imagem pela Interactions API, além de referências visuais. Modelos e disponibilidade podem mudar; conferir a [documentação oficial de geração de imagens](https://ai.google.dev/gemini-api/docs/image-generation) antes de atualizar.

## Banco e operação

A migração PostgreSQL aditiva é `scripts/migrations/20261007_promotions_postgresql.sql`; o rollback é `scripts/migrations/20261007_promotions_rollback_postgresql.sql` e recusa execução se houver qualquer contato, consentimento, campanha ou destinatário persistido. Testar a migração e rollback em PostgreSQL isolado antes de atualizar o banco operacional. Fazer e verificar backup antes da aplicação. O startup também cria as tabelas novas por `Base.metadata.create_all` e aplica triggers append-only para eventos de consentimento/campanha.

A aba fica em `/web/promocoes`, dentro do menu Comunicação. O cadastro de contatos autorizados fica na ficha do cliente, seção “Contatos para campanhas”. A aplicação continua local (`127.0.0.1`); como ainda não há autenticação efetiva, não publicar nem expor o SMTP/API na rede.
