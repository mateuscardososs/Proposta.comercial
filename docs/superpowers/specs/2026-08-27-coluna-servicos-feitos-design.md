# Coluna Servicos Feitos - Falta Nota/Pedido

## Objetivo

Adicionar ao Kanban de tarefas uma etapa propria para servicos que ja foram executados, mas ainda dependem da emissao de nota ou do registro de pedido.

## Fluxo do quadro

O quadro passa a ter cinco colunas, nesta ordem:

1. A Fazer (`a_fazer`)
2. Em Andamento (`em_andamento`)
3. Servicos Feitos - Falta Nota/Pedido (`servico_feito_falta_nota_pedido`)
4. Aguardando Cliente (`aguardando_cliente`)
5. Concluido (`concluido`)

Cards existentes permanecem com seus status atuais. A mudanca nao exige alteracao de tabela, pois `Task.status` ja e armazenado como texto.

## Interface e comportamento

- A nova coluna aparece imediatamente depois de Em Andamento.
- O formulario de criacao e edicao oferece o novo status na mesma posicao.
- O drag-and-drop reutiliza `POST /api/tasks/{id}/move`, incluindo `status` e `ordem`.
- O visual reutiliza integralmente o componente Kanban e os estilos existentes.
- O quadro informa cinco colunas por meio de `--kanban-columns: 5`; os breakpoints existentes continuam exibindo duas colunas em telas intermediarias e uma em celulares.

## Arquivos previstos

- `app/routers/board.py`: incluir o novo grupo no contexto do quadro.
- `app/templates_web/board.html`: incluir a coluna na ordem aprovada.
- `app/templates_web/board_form.html`: incluir a opcao no seletor de status.
- `tests/test_board_statuses.py`: cobrir renderizacao, formulario e movimentacao pela API.

## Validacao

- Confirmar que as cinco colunas aparecem na ordem definida.
- Confirmar que a nova opcao aparece nos formularios de criacao e edicao.
- Mover uma tarefa para o novo status pela API e confirmar a persistencia.
- Executar a suite completa no ambiente Docker.

## Fora do escopo

- Migration ou alteracao de schema do banco.
- Automacao financeira ou emissao de nota/pedido.
- Alteracoes em propostas, clientes ou lancamentos financeiros.
- Renomear ou migrar status existentes.
