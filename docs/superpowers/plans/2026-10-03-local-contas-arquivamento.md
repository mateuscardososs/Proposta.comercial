# Entrada Local e Arquivamento Financeiro — Plano de Implementação

**Goal:** Atualizar a instância local 8013 no PostgreSQL padrão com estados financeiros organizados e arquivamento auditável, preservando o limite Yahoo do piloto.

**Architecture:** Manter `Lancamento.status` como `pendente`/`pago`, acrescentar `arquivado_em` como projeção do arquivamento e gravar toda criação/transição relevante em histórico append-only com chave idempotente. As listas financeiras separam contas abertas, atrasadas, pagas/recebidas e arquivadas; um worker diário e a leitura dos murais compartilham a mesma operação idempotente.

**Tech Stack:** FastAPI, Jinja2, SQLAlchemy 2.0, PostgreSQL 16, SQLite isolado para testes unitários, pytest, Docker e Yahoo IMAP somente leitura.

## Global Constraints

- Usar somente `propostas_db` para a instância 8013; não copiar registros sintéticos das portas 8000/8011.
- Fazer backup verificável antes de qualquer escrita no PostgreSQL padrão.
- Validar compatibilidade e arquivamento em PostgreSQL temporário antes da alteração no banco padrão.
- Publicar a aplicação exclusivamente em `127.0.0.1:8013`; não habilitar autenticação por suposição.
- Manter Yahoo IMAP em leitura somente, intervalo de 900 segundos e criação automática restrita a pedidos operacionais de alta confiança.
- Preservar `activation_at=2026-10-02 20:43:34` quando possível; a busca incremental nunca pode iniciar antes desse marco.
- Não apagar contas, eventos, e-mails ou histórico; não alterar status/datas sem ação explícita e trilha.
- Manter 8000/8011/8012 ativos até a 8013 atualizada e validada; depois encerrar somente os processos identificados dessas portas.
- Não fazer commit, push ou deploy.

---

### Task 1: Estados financeiros, auditoria e arquivamento idempotente

**Files:**
- Modify: `app/models.py`, `app/db.py`, `app/schemas.py`
- Modify: `app/services/lancamento_service.py`
- Modify: `app/main.py` ou novo `app/services/finance_archive_worker.py`
- Test: `tests/test_lancamento_service.py`, `tests/test_service_history_immutability.py`, `tests/test_assistant_schema_compatibility.py`

- [x] Adicionar primeiro testes para atraso (somente pendente vencido), pagamento confirmado com/sem data, manutenção de data em retry idêntico, arquivamento após 30 dias, exclusão de contas sem data confirmada e ausência de evento duplicado.
- [x] Executar os testes novos e confirmar falha pelos campos/serviço ausentes (RED inicial: 4 falhas; após implementação: suite relevante aprovada).
- [x] Adicionar `Lancamento.arquivado_em` e tabela `LancamentoHistorico` com FK `RESTRICT`, `event_key` único por conta, ação, estado/data anterior e novo, observação e timestamp.
- [x] Adicionar evento de criação e eventos para alterações explícitas de status/data; retry idêntico conserva data e não cria evento.
- [x] Criar `archive_expired_lancamentos`: somente pagamentos/recebimentos confirmados com data há pelo menos 30 dias; arquivamento e evento na mesma transação.
- [x] Tornar o histórico append-only por `before_flush` e gatilhos SQLite/PostgreSQL; sem `delete-orphan` nem `ON DELETE CASCADE`.
- [x] Acrescentar migração aditiva e idempotente de `lancamentos.arquivado_em` e índice; sweep na inicialização, diariamente e ao abrir os murais.
- [x] Rodar testes de service, rotas e imutabilidade no SQLite isolado.

### Task 2: Grupos e filtros nas duas áreas financeiras

**Files:**
- Modify: `app/routers/financeiro.py`, `app/templates_web/lancamentos_board.html`
- Test: `tests/test_financeiro_routes.py`

- [x] Adicionar testes para grupos exclusivos nos dois murais.
- [x] Implementar `?grupo=abertas|atrasadas|pagas|arquivadas`, default `abertas`, contagens e filtros compartilhados.
- [x] Ocultar ações nas arquivadas e mostrar data de arquivamento e pagamento.
- [x] Reexecutar testes financeiros e regressão do quadro.

### Task 3: Validar migração e fluxos em PostgreSQL isolado

**Files:**
- Verify: `app/db.py`, `app/models.py`, `app/services/lancamento_service.py`
- Test: PostgreSQL temporário sem dados operacionais

- [x] Fazer backup novo do banco padrão e validar arquivo/checksum/TOC antes da primeira escrita.
- [x] Criar PostgreSQL temporário, restaurar apenas o esquema do backup, e validar migração compatível sem dados operacionais.
- [x] Exercitar contas sintéticas no PostgreSQL temporário: arquivamento único, trigger de imutabilidade e FK `RESTRICT`.
- [x] Confirmar restrições e preservação do histórico no PostgreSQL temporário.
- [x] Remover apenas o contêiner temporário criado neste plano depois dos testes.

### Task 4: Aplicar a 8013, preservar ativação e sincronizar Yahoo

**Files:**
- No código adicional além das Tasks 1–2; operação local na configuração ignorada `.env.yahoo.local`
- Verify: `app/assistant/email/sync.py`, `app/assistant/email/imap.py`, `scripts/run_assistant_8011_yahoo.sh`

- [x] Revalidar 8013 e criar backup novo verificável antes da escrita no banco padrão.
- [x] Aplicar esquema aditivo e arquivamento inicial no banco padrão; comparar contagens operacionais.
- [x] Copiar somente o marco `imap_yahoo / adbalancas-piloto-20261002`, sem importar mensagens/tarefas piloto.
- [x] Montar `.env.yahoo.local` somente leitura e confirmar configuração sem revelar credenciais.
- [x] Ativar IMAP somente leitura a cada 900s e criação somente de tarefas operacionais elegíveis de alta confiança.
- [x] Acompanhar uma sincronização e reportar somente totais por categoria.

### Task 5: Trocar as instâncias após validação

**Files:**
- Verify only: `docker`/processos nas portas 8000–8013

- [x] Confirmar health, rotas financeiras principais e listener 8013 em loopback antes de parar processos antigos.
- [x] Identificar PID, processo Python e diretório do projeto em 8000, 8011 e 8012; encerrar somente os PIDs identificados após health da 8013.
- [x] Confirmar 8000/8011/8012 sem listener; 8013 saudável e Yahoo configurado para 900 segundos.
- [x] Rodar suíte completa/relevante, compileall, Ruff no worker novo e `git diff --check`; sem commit.

## Execution Evidence — 2026-10-03

- Backup imediatamente anterior à escrita: `../local-backups/adbalancas-default-pre-release-20261003.dump`, modo `0600`, `pg_restore --list` válido (263 entradas); SHA-256 `55a97c799ff128ff54bd4266b5327e406e3fe910f80f57785653eb685752d201`.
- PostgreSQL temporário: restaurado somente o schema do backup, sem dados operacionais; migração/compatibilidade executadas duas vezes; arquivamento, trigger append-only e FK `RESTRICT` testados com um registro sintético; contêiner temporário removido.
- Banco `propostas_db`: clientes 4, usuários 1, tarefas 24, propostas 9 e lançamentos 23 antes/depois. Sete lançamentos com pagamento confirmado há pelo menos 30 dias foram arquivados e têm sete eventos de auditoria; nenhum arquivado viola a regra.
- Yahoo: preservado `activation_at=2026-10-02 20:43:34.394255`; nenhum e-mail ou tarefa do banco piloto foi importado. Primeira sincronização real concluiu com 3 mensagens, nenhuma anterior ao marco e nenhum link de tarefa criado. Categorias: `informational=2`, `other_review=1`.
- Listener externo da aplicação: `127.0.0.1:8013`; `/healthz`, quadro, contas a pagar/receber, filtros e mensagens responderam HTTP 200. Portas antigas 8000, 8011 e 8012 encerradas após a verificação da 8013; PostgreSQL permaneceu ativo.
- Arquivos gerados/documentos do contêiner anterior 8013 foram preservados em `../local-data/adbalancas-8013/` e montados na nova instância. O contêiner anterior permanece parado para rollback local.
- A aplicação foi publicada apenas em `127.0.0.1:8013`. O contêiner PostgreSQL preexistente continua com sua publicação Docker `0.0.0.0:5432`; não foi reiniciado nem alterado nesta entrega, e esse vínculo de rede merece uma mudança de segurança separada.
- Voz permanece desativada na 8013, como estava na instância anterior; não foi alterada nesta entrega. A aplicação continua sem autenticação efetiva.
- Testes: SQLite `501 passed, 10 skipped`; PostgreSQL temporário aprovado; testes financeiros focados `32 passed`; compileall, Ruff no novo worker e `git diff --check` aprovados.
