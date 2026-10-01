# Desenho da leitura de e-mail

## Escopo desta entrega

A leitura de e-mail entra como uma capacidade opcional do mesmo assistente de texto e voz. A
instância de validação usa exclusivamente uma caixa sintética. O adaptador Yahoo IMAP existe, mas
fica desativado até receber configuração local e passar por teste explícito com a conta da empresa.

Não fazem parte desta entrega: envio, exclusão, movimentação, alteração de flags, abertura de links,
download de anexos, execução de anexos ou criação automática de tarefas.

## Causa da alegação sem evidência

A proteção anterior verificava consultas de tarefas e alguns verbos de alteração. E-mail não era uma
capacidade representada, `conferi` não era uma alegação reconhecida e `responder_conversa` podia
produzir texto sem uma prova de ferramenta. A correção é estrutural:

1. um catálogo central informa se cada capacidade está implementada, configurada e disponível;
2. toda ferramenta produz um resultado com estado e identificador de evidência;
3. alegações de consulta ou execução são validadas por domínio contra evidências da solicitação;
4. resultados anteriores só podem ser descritos explicitamente como históricos;
5. financeiro, documentos, serviços, envio e emissão fiscal continuam indisponíveis e não são
   convertidos em consultas ou tarefas.

## Componentes

- `capabilities.py`: catálogo central e estados das capacidades.
- `email/contracts.py`: filtros e resultados estruturados independentes de provedor.
- `email/provider.py`: protocolo de leitura e erros tipados.
- `email/synthetic.py`: caixa imutável para testes e demonstração.
- `email/imap.py`: adaptador genérico IMAP com configuração Yahoo, conexão SSL, `SELECT` somente
  leitura e buscas/fetches sem alteração da flag `\\Seen`.
- `email/service.py`: período no fuso da aplicação, cache, classificação determinística,
  encadeamento entrada/enviados e resultados auditáveis.
- `AssistantService`: orquestra a ferramenta, devolve somente um conjunto limitado ao modelo e
  preserva referências apresentadas para continuidade.

## Estados de resultado

Cada consulta retorna um entre: `not_implemented`, `not_configured`, `failed`, `empty`, `success`,
`partial` ou `stale`. `empty` significa consulta concluída sem mensagens; `failed` nunca é tratado
como caixa vazia. `partial` e `stale` carregam uma limitação visível.

## Prioridade e resposta pendente

A classificação determinística considera prazo explícito, pedido de resposta, orçamento,
autorização, serviço com prazo e cobrança. Publicidade e mensagens meramente informativas reduzem a
pontuação. A palavra “urgente” isolada não basta. O modelo recebe os indícios e pode redigir o resumo,
mas não pode inventar fatos ou prazos.

“Possível resposta pendente” é inferência: compara a mensagem de entrada mais recente com mensagens
enviadas do mesmo encadeamento. Se Enviados não estiver disponível, o resultado informa que a
avaliação não é confiável. A flag `\\Seen` significa apenas lido/não lido no servidor; não prova que
alguém compreendeu a mensagem.

## Segurança e privacidade

- credenciais existem apenas em variáveis locais e não são persistidas nem incluídas em erros;
- conteúdo de e-mail é dado não confiável e nunca pode autorizar ferramenta ou alterar instruções;
- telemetria guarda tempos, contagens, estados e referências opacas, sem corpo, assunto ou remetente;
- o histórico visual persiste o texto apresentado e os detalhes estruturados necessários à
  continuidade;
- o cache persiste metadados, resumo e trecho limitado pelo período configurável de retenção;
- o adaptador não abre links, não salva anexos e busca somente a parte textual escolhida pelo
  `BODYSTRUCTURE`;
- a seleção de pastas usa atributos IMAP (`\\Inbox`, `\\Sent`) antes de recorrer a nomes conhecidos.

## Yahoo

Segundo a documentação oficial consultada em 01/10/2026, o Yahoo informa
`imap.mail.yahoo.com:993` com SSL e senha de aplicativo para clientes IMAP. O Outlook é apenas o
cliente atual; isso não transforma a conta em Microsoft. Referências:

- [Configuração IMAP do Yahoo](https://ca.help.yahoo.com/kb/SLN4075.html)
- [Gerar e gerenciar senha para aplicativo](https://help.yahoo.com/kb/SLN15241.html)

O adaptador é somente leitura. A existência e sincronização da pasta Enviados só podem ser confirmadas
por uma consulta real posterior.

## Configuração

O padrão é `EMAIL_PROVIDER=disabled`. A demonstração usa `EMAIL_PROVIDER=synthetic`. Para Yahoo:

```text
EMAIL_PROVIDER=imap_yahoo
EMAIL_IMAP_HOST=imap.mail.yahoo.com
EMAIL_IMAP_PORT=993
EMAIL_IMAP_USERNAME=conta-completa@example.com
EMAIL_IMAP_APP_PASSWORD=senha-de-app-gerada-no-Yahoo
EMAIL_IMAP_TIMEOUT_SECONDS=10
EMAIL_MAX_MESSAGES=30
EMAIL_CACHE_RETENTION_DAYS=14
EMAIL_BODY_PREVIEW_CHARS=4000
```

Esses valores sensíveis devem ficar em `.env` local ou no gerenciador de segredos do ambiente, nunca
no Git. O processo não imprime usuário nem senha.

