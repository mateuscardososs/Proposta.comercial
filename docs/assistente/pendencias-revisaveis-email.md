# Pendências revisáveis originadas de e-mail

## Escopo e fluxo

O leitor Yahoo permanece IMAP somente leitura. A sincronização/classificação existente continua responsável pela caixa, grupos operacionais/informativos/revisão e evidência da categoria. Esta etapa acrescenta uma prévia estruturada na mesma tela **E-mails e mensagens**; não lê o Yahoo por uma rota paralela, não envia ou altera mensagens e não persiste o corpo completo.

Para categorias operacionais de alta confiança — solicitação de orçamento de cliente, pedido de compra, serviço e possível resposta pendente — o cache pode receber um `EmailActionDraft` do tipo tarefa. A categoria de cotação enviada por fornecedor é distinta e não gera tarefa. Contas a pagar e notas recebidas podem abrir uma proposta de lançamento em modo de conferência; uma nota recebida não prova que existe obrigação a pagar. A tela pode mostrar a proposta, mas a gravação financeira requer campos completos e a confirmação explícita de que se trata de conta a pagar.

```text
IMAP somente leitura → classificação existente → extração determinística de campos
                    → InboxEmail + prévia revisável (sem Task/Lancamento)
                    → usuário confirma → serviço existente + vínculo de origem
```

O Gemini não extrai valores diretamente para o banco e não autoriza ações. Categorias, campos e argumentos são validados no backend. A origem é preservada por `InboxEmail` e, para tarefas, por `EmailTaskLink`; `EmailActionDraft` tem unicidade por mensagem/tipo de ação. Repetir sincronização ou confirmar novamente reutiliza a ação já ligada. A confirmação financeira cria lançamento `pagar` pendente e histórico por `lancamento_service`; não paga, baixa ou emite documentos.

## Extração e incerteza

Os campos persistidos em `InboxEmail.extracted_fields` são JSON estruturado: nome explícito de cliente/fornecedor e papel, valor monetário explicitamente identificado, número de nota, data de emissão, vencimento/prazo, ação sugerida, campos ausentes, incertezas e marcadores genéricos de evidência. Datas sem contexto apropriado, múltiplos candidatos e valores conflitantes não são escolhidos automaticamente. A interface separa **prazo informado** de **vencimento** e mostra campos ausentes/incertos.

A extração de releituras históricas ocorre somente dos metadados e do resumo já guardados; a interface informa que o corpo não está retido e que a evidência pode ser incompleta. Revisar uma categoria usa novamente o resumo persistido, não acessa IMAP. Um cadastro de cliente só é vinculado por correspondência determinística suficientemente clara; fornecedor continua texto livre para conferência.

## Persistência e compatibilidade

- Migração aditiva: `inbox_emails.extracted_fields` é acrescentado como JSON anulável em bancos antigos.
- `email_action_drafts` é criado por `Base.metadata.create_all` e mantém vínculo restritivo à mensagem de origem; referências a tarefa/lançamento ficam anuláveis para que exclusão de um registro operacional antigo não apague o histórico da proposta.
- Índice único `(inbox_email_id, action_type)` impede duas prévias da mesma ação para a mesma mensagem. O serviço financeiro exige confirmação explícita e valores/datas válidos antes de chamar `lancamento_service`.
- No início da aplicação, `backfill_existing_email_drafts` percorre apenas linhas já armazenadas, sem chamada de rede. O backfill não cria tarefa nem lançamento. Repeti-lo é idempotente.

## Testes e validação

Os testes sintéticos devem verificar pedido de orçamento versus cotação de fornecedor, extração e ausência de invenções, cliente existente/ambíguo, campos financeiros ausentes, preview sem gravação, confirmação/cancelamento, retries e sincronização repetida, backfill e compatibilidade de schema. Testes não usam a conta real nem o banco operacional. Integração em PostgreSQL deve validar a coluna JSON aditiva e a tabela/constraints antes do startup na instância principal. Uma consulta real de Yahoo não é necessária nem autorizada para validar esta funcionalidade.

## Limites

- Não há autenticação efetiva: mantenha o aplicativo preso a `127.0.0.1`.
- Uma nota fiscal recebida pode ou não corresponder a uma conta; alguém precisa conferir a obrigação e completar dados ausentes.
- Uma prévia não equivale a compromisso aceito, orçamento enviado, serviço registrado, documento emitido, pagamento realizado ou recebimento baixado.
- A classificação permanece na fila existente e pode exigir revisão. “Não lido” não eleva prioridade.
- Não há criação automática de lançamentos ou tarefas nesta etapa; confirmações são explícitas em cada prévia.
