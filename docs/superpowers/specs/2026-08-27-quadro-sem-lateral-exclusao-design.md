# Quadro sem lateral e exclusao de atividades

## Objetivo

Simplificar as paginas do Quadro removendo o conteudo lateral voltado a propostas e permitir a exclusao definitiva de uma atividade com confirmacao explicita.

## Paginas do Quadro em largura total

As rotas abaixo nao devem exibir os paineis "Atalhos" e "Padrao de produtividade":

- `/web/board`
- `/web/board/new`
- `/web/board/{id}/edit`

O router passa uma flag de contexto para que `base.html` omita o `aside` e aplique uma variante de uma coluna ao layout. As demais paginas continuam usando a lateral existente sem alteracao.

## Exclusao de atividade

- A exclusao fica disponivel apenas na tela de edicao.
- O botao usa o estilo visual de perigo existente e o texto "Excluir atividade".
- O botao pertence a um formulario separado, evitando formularios HTML aninhados.
- Antes do envio, `window.confirm` mostra: "Tem certeza que deseja excluir esta atividade? Esta acao nao pode ser desfeita."
- Confirmando, o formulario envia `POST /web/board/{id}/delete`.
- Cancelando, nenhuma requisicao e enviada e a atividade permanece inalterada.
- Depois da exclusao, a rota responde com redirect HTTP 303 para `/web/board`.
- Uma atividade inexistente retorna HTTP 404.

## Persistencia e ordenacao

O service localiza a atividade, guarda `status` e `ordem`, exclui o registro e reduz em um a ordem das atividades posteriores da mesma coluna. Exclusao e reorganizacao sao confirmadas na mesma transacao.

Nao ha alteracao de schema ou migration.

## Arquivos previstos

- `app/templates_web/base.html`: variante opcional do layout sem lateral.
- `app/routers/board.py`: passar a flag de largura total e adicionar a rota de exclusao.
- `app/services/board_service.py`: implementar a exclusao e compactacao da coluna.
- `app/templates_web/board_form.html`: adicionar o formulario e a confirmacao de exclusao somente na edicao.
- `tests/test_board_delete.py`: cobrir layout, exclusao, 404 e compactacao.

## Validacao

- Confirmar ausencia dos dois paineis laterais nas tres paginas do Quadro.
- Confirmar que outras paginas continuam exibindo a lateral.
- Confirmar que o botao de exclusao aparece apenas na edicao e possui confirmacao.
- Confirmar exclusao, redirect, resposta 404 e reorganizacao de `ordem`.
- Executar a suite completa localmente e no Docker.

## Fora do escopo

- Arquivamento ou lixeira recuperavel.
- Exclusao direta pelo card do Kanban.
- Alteracao dos atalhos globais da barra de navegacao.
- Mudancas em propostas, clientes ou modulos financeiros.
