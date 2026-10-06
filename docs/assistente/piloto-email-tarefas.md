# Piloto local: triagem de e-mail e tarefas sem cliente cadastrado

**Data:** 02/10/2026  
**Escopo:** instância local `127.0.0.1:8012`, banco e arquivos próprios em `/tmp`. As instâncias 8000 e 8011 não fazem parte do piloto.

## Comportamento

- Tarefas manuais continuam exigindo confirmação antes da gravação. Cliente não cadastrado fica em `Task.client_name`, com `client_id=NULL` e `client_link_status=pending_review`; correspondência múltipla usa `needs_confirmation`; ausência de empresa usa `unlinked`.
- Uma correspondência única com o cadastro preenche `client_id`. A conversa de correção atualiza a mesma `AssistantAction`, invalida o token anterior e não perde o rascunho. Responder que quer cadastrar uma empresa não cria um cadastro incompleto: preserva o nome na tarefa e informa que o cadastro não foi alterado.
- O comportamento atual substitui a criação automática do piloto: a sincronização apenas cria rascunhos revisáveis e nunca grava `Task` ou `Lancamento`. Pedido de orçamento de cliente pode gerar rascunho de tarefa; um cliente ausente/ambíguo fica como texto livre para revisão. A tarefa `A fazer` só nasce após confirmação explícita, com vínculo idempotente ao e-mail.
- Conta a pagar ou nota recebida pode gerar proposta estruturada de lançamento. O fluxo exige confirmar explicitamente a obrigação a pagar e informar valor, fornecedor, data de emissão e vencimento antes de criar um lançamento pendente. Não marca pagamento, não baixa recebimento e não emite nota. Cotação recebida de fornecedor permanece distinta do pedido de orçamento do cliente.
- Releituras/retries atualizam a mesma projeção e reutilizam o rascunho por origem e tipo de ação; nenhum corpo completo é persistido. Campos extraídos ficam em JSON estruturado, com evidências por tipo de marcador, ausências e incertezas.
- Entrada e Enviados continuam IMAP somente leitura (`select(..., readonly=True)` e leitura de partes por `BODY.PEEK`). O sincronizador não marca como lida, envia, move ou exclui mensagens. O corpo integral não é persistido.

## Janela de ativação

`email_sync_states.activation_at` registra o instante local da ativação por provedor/caixa. O primeiro ciclo consulta de `activation_at` até agora, sem lookback histórico. Ciclos seguintes aplicam a sobreposição incremental, mas limitam seu início a `activation_at`. A ativação é persistida antes da primeira consulta; retries e reinícios da instância preservam o limite. Intervalo, lote e caixa permanecem configuráveis.

## Configuração local

O arquivo `.env.yahoo.local` do repositório está ignorado pelo Git e deve conter apenas configuração local. Não imprima seu conteúdo, não use `set -x` e não passe a senha em argumentos de processo. A configuração carregada pelo piloto pode ser sobrescrita pelas variáveis abaixo, sem tocar em `.env` ou na configuração da 8000/8011.

Com o diretório `/tmp/adbalancas-email-pilot-20261002` já preparado, iniciar com:

```sh
cd /Users/mateuscardoso/dev/pai/Proposta.comercial
APP_ENV_FILE="$PWD/.env.yahoo.local" \
DATABASE_URL="sqlite:////tmp/adbalancas-email-pilot-20261002/pilot.sqlite3" \
OUTPUT_DIR="/tmp/adbalancas-email-pilot-20261002/output" \
TEMPLATE_DOC_PATH="/tmp/adbalancas-email-pilot-20261002/templates/proposta_template.docx" \
APP_HOST="127.0.0.1" APP_PORT="8012" APP_RELOAD="false" \
EMAIL_PROVIDER="imap_yahoo" EMAIL_SYNC_ENABLED="true" \
EMAIL_AUTO_TASK_CREATION_ENABLED="true" EMAIL_SYNC_INTERVAL_SECONDS="900" \
EMAIL_SYNC_BATCH_SIZE="30" EMAIL_SYNC_MAILBOX_KEY="adbalancas-piloto-20261002" \
OLLAMA_MODEL="qwen3:4b-instruct-2507-q4_K_M" VOICE_ENABLED="false" \
PYTHONPATH=. .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8012
```

A primeira consulta ocorre após a persistência da fronteira de ativação; as seguintes, a cada 900 segundos. Para pausar sem parar a aplicação, use a ação local de pausa em `/web/mensagens`. O banco não é operacional; remova o diretório de piloto apenas depois de confirmar que não precisa mais dos dados de teste.

## Teste local

1. Abrir `http://127.0.0.1:8012/web/mensagens` e verificar o provedor, intervalo, estado e contagem. A tela não deve mostrar credenciais nem conteúdo integral.
2. Abrir `http://127.0.0.1:8012/web/board`; tarefas de e-mail sem empresa mostram `Cliente a identificar`, com pendência de revisão e link para a mensagem.
3. No Assistente, solicitar tarefa para uma empresa inexistente e confirmar que há prévia, empresa textual e nenhuma gravação antes da confirmação. Confirmar e verificar `client_id` vazio.
4. Testar nome com correspondência única, nome ambíguo e correções `Cadastre a empresa Roca` / `Roca`; a ação pendente deve manter o mesmo ID.
5. Reiniciar somente a porta 8012 e confirmar que `activation_at` não recua e que releitura não duplica tarefas.

## Limitações do piloto

- Sem autenticação efetiva no app: manter loopback e nunca publicar a porta.
- A classificação é determinística e conservadora; itens não reconhecidos seguem para revisão. O modelo não lê a caixa inteira nem autoriza ações.
- Tarefas automáticas entram em `A fazer` como triagem, não significam proposta, serviço, emissão fiscal, pagamento ou compromisso aceito.
- Dados do cache permanecem no banco isolado até exclusão local. O sincronizador não importa mensagens anteriores à ativação; há dados mínimos de remetente, assunto, resumo limitado, data, estado/classificação e referência opaca para auditoria.
- A sincronização é de uma instância/processo; não executar múltiplos workers com a mesma caixa de piloto.

## Evidência executada nesta preparação

- `PYTHONPATH=. .venv/bin/pytest -q`: **481 passaram, 10 ignorados**, incluindo fluxo de rascunho/cliente, categorias, idempotência, migração aditiva e limite de ativação, em SQLite de teste.
- Ruff passou nos módulos de e-mail e testes novos; compilação dos módulos alterados e `git diff --check` passaram.
- A instância isolada iniciou com Yahoo real pelo arquivo local ignorado. O IMAP autenticou e consultou Entrada com sucesso; o ciclo retornou **0 mensagens novas desde a ativação**, sem importar a caixa histórica. Após reiniciar apenas 8012, o segundo ciclo também concluiu com sucesso e manteve `activation_at` original. Isso não afirma que a caixa inteira esteja vazia nem verifica a cobertura de Enviados.
- Saúde, Mensagens, Tarefas e Assistente retornaram HTTP 200. Um pedido sintético de tarefa com cliente não cadastrado, seguido de “Cadastre a empresa Roca” e “Roca”, retornou prévias com a mesma ação; banco permaneceu com **0 tarefas gravadas** porque a confirmação não foi aceita. O cadastro de cliente também permaneceu inalterado.
- O pedido sintético canônico de criação foi tratado pelo roteador determinístico e, portanto, **não valida a interpretação do Ollama**. Uma tentativa feita antes de reiniciar o código atualizado retornou erro de formato do modelo. Conversa geral dependente do Ollama ainda requer validação separada; nenhum conteúdo de e-mail foi usado nessa tentativa.
- O listener da instância é `127.0.0.1:8012`. As portas 8000 e 8011 não foram reiniciadas. Nenhum e-mail foi alterado e nenhuma tarefa de mensagem real foi gravada.
