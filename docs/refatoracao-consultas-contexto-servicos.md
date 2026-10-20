# Consultas e contexto de serviços — refatoração incremental

## Escopo

Esta rodada separa duas responsabilidades do adapter conversacional de serviços:
a consulta/projeção de chamados e a leitura das referências apresentadas em
mensagens anteriores. Preparação, correção, cancelamento, lembretes e confirmação
continuam no adapter existente. Não há funcionalidades novas nem mudanças de
regra de negócio.

Branch: `refactor/promotion-contacts`, partindo do estado externo `86e524f`.
O plano está em
[consultas e contexto](superpowers/plans/2026-10-11-refatoracao-consultas-contexto-servicos.md).

## Contratos protegidos

- Mesma sessão e callback de resolução de cliente, incluindo esclarecimento
  antes da consulta quando o cliente é ambíguo.
- Mesmos filtros, ordem, limites, payload, mensagens e evidências.
- Eventos efetivos, correções, últimos três eventos e descrições de até 240
  caracteres; inspeção e conclusão continuam distintas.
- Retornos vinculados a eventos e tarefas ainda incompletas.
- Histórico de mensagens isolado por conversa e papel, com janelas de 30
  mensagens para listas e 20 para verificar uma apresentação.
- Referências explícitas continuam dispensando leitura de histórico;
  consultas de contexto não escrevem dados nem criam ações.
- Mesmas confirmações, histórico imutável e idempotência dos escritores.

## Validação e incidente bloqueante

A consulta foi extraída para `app/assistant/service_queries.py`, mantendo a
classe de retorno por alias e o callback atual do adapter. Os outros 15 métodos
permanecem iguais por comparação AST. A revisão independente aprovou o código.
Os testes focados iniciais passaram com 125 casos antes/depois; a suíte reforçada
passou com 126 casos, mas sua execução de caracterização anterior **não foi
isolada corretamente** e não pode ser apresentada como validação segura.

O comando reforçado importou `service_records` antes de `pytest.main()` sem
definir `DATABASE_URL` explicitamente. Esse import inicializou o engine com o
SQLite padrão do repositório, pois o `.env` estava desativado. A alteração de
ambiente posterior em `tests/conftest.py` não substituiu o engine já criado.
Consequentemente, a fixture de reset recriou o schema no arquivo `propostas.db`.
O arquivo estava limpo no início, com 65.536 bytes na versão HEAD; após os testes
passou a 663.552 bytes e aparece modificado no Git. Seu conteúdo não foi aberto
para investigar, nem foi restaurado ou sobrescrito.

A revisão independente confirmou a falha de isolamento e retirou a aprovação
da execução segura. O PostgreSQL não foi usado por esse comando. A tarefa18,
a suíte completa e a validação integrada estão **suspensas**, aguardando decisão
sobre recuperação do arquivo. Não houve reinício ou integração externa.

Para novas execuções, `DATABASE_URL` e diretórios temporários devem ser definidos
antes de qualquer import da aplicação; o alvo real do engine precisa ser
verificado antes de qualquer fixture de reset. O launcher anterior, dependente
da ordem de imports do conftest, não é garantia suficiente.

## Limites operacionais

Nenhuma configuração privada ou integração real foi usada. Houve a alteração
indevida do SQLite local descrita acima; não se deve declarar preservação integral
dos dados desta rodada. Sem migrações no PostgreSQL, commits, publicação ou reinício.
Não há validação manual de
microfone, navegador, PostgreSQL ou provedores reais nesta rodada.

Na inspeção desta rodada, não havia listener na porta 8013. O código não foi
ativado: a inicialização existente pode aplicar compatibilidade/backfill e
iniciar consulta Yahoo, efeitos fora do escopo desta refatoração.
