# Contas a Receber e Contas a Pagar — Design

## Objetivo

Adicionar dois murais financeiros manuais ao sistema AD Balanças:

- `/web/contas-a-receber`, para lançamentos do tipo `receber`;
- `/web/contas-a-pagar`, para lançamentos do tipo `pagar`.

Os lançamentos serão independentes do ciclo de propostas. Um vínculo opcional com uma proposta servirá somente como referência navegável, sem criação, atualização ou recálculo automático.

## Escopo aprovado

- Criar o model `Lancamento` com `id`, `tipo`, `descricao`, `client_id`, `proposal_id`, `fornecedor`, `valor`, `data_emissao`, `data_vencimento`, `status`, `data_pagamento`, `created_at` e `updated_at`.
- Aceitar somente os tipos `receber` e `pagar` e os status `pendente` e `pago`.
- Informar manualmente valor, data de emissão e data de vencimento nos formulários.
- Manter `client_id` e `proposal_id` opcionais como referências para contas a receber.
- Manter `fornecedor` como texto livre opcional para contas a pagar.
- Marcar um lançamento vencido com destaque vermelho quando `data_vencimento < hoje` e `status != "pago"`.
- Permitir movimentação entre as colunas pendente e pago sem recarregar a página.
- Ao mover para pago, preencher `data_pagamento` com a data atual. Ao voltar para pendente, limpar `data_pagamento`.
- Adicionar links “Contas a Receber” e “Contas a Pagar” à navegação.
- Criar as tabelas pelo `Base.metadata.create_all` já executado no startup, sem Alembic.

## Fora de escopo

- Campo `Client.dias_pagamento_padrao`.
- Pré-preenchimento de condições de pagamento em propostas.
- Checkbox financeiro no formulário de propostas.
- Criação automática de lançamentos a partir de propostas.
- Atualização de lançamentos quando uma proposta é revisada.
- Recálculo automático de valor ou vencimento.
- Cadastro separado de fornecedores.
- Conciliação bancária, parcelas, recorrência, categorias, centros de custo ou fluxo de caixa.
- Reordenação persistida de cards dentro de uma coluna.

## Arquitetura

A implementação financeira ficará isolada em um router e um service próprios. As páginas de receber e pagar usarão os mesmos templates parametrizados por `tipo`, evitando duplicação sem acoplar as regras financeiras ao router de tarefas.

O módulo de tarefas continuará com suas quatro colunas e regras atuais. Apenas a camada visual e o comportamento genérico de drag-and-drop serão compartilhados onde isso puder ser feito sem mudar as URLs ou o funcionamento do quadro existente.

### Arquivos novos

- `app/routers/financeiro.py`: rotas web de listagem, criação e edição, além de `POST /api/lancamentos/{id}/move`.
- `app/services/lancamento_service.py`: consultas, validação, persistência e mudança de status.
- `app/templates_web/lancamentos_board.html`: mural parametrizado para receber e pagar.
- `app/templates_web/lancamento_form.html`: formulário parametrizado por tipo e modo de criação/edição.
- `app/templates_web/_kanban_drag.html`: comportamento genérico de drag-and-drop configurado por atributos HTML.
- `tests/test_lancamentos.py`: testes das regras do service e das rotas principais.

### Arquivos alterados

- `app/models.py`: model `Lancamento` e seus relacionamentos unidirecionais opcionais.
- `app/schemas.py`: schemas de criação, atualização, leitura e movimentação.
- `app/main.py`: inclusão do router financeiro.
- `app/templates_web/base.html`: links da navbar e estilos compartilhados do mural e do estado vencido.
- `app/templates_web/board.html`: adoção do comportamento compartilhado de drag-and-drop, preservando o quadro atual.

Não serão alterados `app/routers/pages.py`, `app/services/proposal_service.py`, `app/templates_web/proposal_form.html` nem os models/schemas de clientes e propostas.

## Modelo e relacionamentos

`Lancamento` usará SQLAlchemy 2.0 com `Mapped` e `mapped_column`:

- `tipo`: `String`, obrigatório;
- `descricao`: `String`, obrigatório;
- `client_id`: FK opcional para `clients.id`, com `ondelete="SET NULL"`;
- `proposal_id`: FK opcional para `proposals.id`, com `ondelete="SET NULL"`;
- `fornecedor`: `String`, opcional;
- `valor`: `Numeric(14, 2)`, obrigatório e maior que zero;
- `data_emissao`: `Date`, obrigatório, com default `date.today`;
- `data_vencimento`: `Date`, obrigatório e sempre informado pelo usuário;
- `status`: `String`, obrigatório, default `pendente`;
- `data_pagamento`: `Date`, opcional;
- timestamps fornecidos por `TimestampMixin`.

Os relacionamentos com `Client` e `Proposal` serão unidirecionais a partir de `Lancamento`, sem novas coleções nos models existentes e sem `delete-orphan`. As duas FKs serão anuláveis e usarão explicitamente `ForeignKey(..., ondelete="SET NULL")`. Assim, excluir um cliente ou proposta preserva o lançamento e remove apenas o vínculo de referência, sem bloquear a exclusão nem apagar o registro financeiro.

## Regras de validação

O service será a fonte das regras, tanto para formulários HTML quanto para a API de movimentação:

- Rejeitar `tipo` ou `status` fora dos valores permitidos.
- Exigir descrição não vazia e valor maior que zero.
- Em `receber`, aceitar cliente e proposta opcionais e ignorar fornecedor vazio.
- Em `pagar`, aceitar fornecedor opcional e manter cliente/proposta vazios por padrão.
- Validar que IDs opcionais informados existem.
- Impedir que a URL de edição de receber altere um lançamento do tipo pagar, e vice-versa.
- Em edição manual com status pago, preservar a data de pagamento existente ou usar a data informada; ao definir pendente, limpar a data de pagamento.
- Na movimentação, usar a data atual do servidor ao entrar em pago e limpar a data ao retornar para pendente.

Erros de formulário devem reapresentar o formulário com mensagem legível e os valores digitados, em vez de expor a exceção bruta. A API JSON deve responder com status 404 para ID inexistente e 422/400 para transição ou payload inválido.

## Interface

Cada mural terá duas colunas:

- Receber: “A Receber” e “Pago”;
- Pagar: “A Pagar” e “Pago”.

Cards de contas a receber mostrarão descrição, cliente quando houver, valor, vencimento e link para a proposta quando houver. Cards de contas a pagar mostrarão descrição, fornecedor quando houver, valor e vencimento.

Os formulários reutilizarão `.card`, `.form-grid-*`, `.field`, `.btn`, `.badge` e os tokens de cor de `base.html`. Campos específicos serão exibidos conforme o tipo. O destaque de vencido usará `var(--danger)` e não criará uma terceira coluna.

Como `Lancamento` não terá campo `ordem`, os cards serão carregados por status, vencimento ascendente e ID descendente. O drag-and-drop persistirá apenas a mudança de status; movimentos dentro da mesma coluna não terão ordenação persistente.

Se a chamada AJAX falhar, o card retornará visualmente ao estado anterior e será exibida uma mensagem de erro acessível. Os contadores das colunas só serão considerados confirmados depois de uma resposta bem-sucedida.

## Fluxos

### Criação e edição

1. O tipo é definido pela URL da página e não por um campo editável do formulário.
2. O router converte os dados do formulário para o schema correspondente.
3. O service valida referências e regras de domínio.
4. Após persistir, o usuário retorna ao mural do mesmo tipo.

### Movimentação

1. O navegador envia `POST /api/lancamentos/{id}/move` com o novo status.
2. O service valida o status e localiza o lançamento.
3. A transição atualiza `status` e `data_pagamento` atomicamente.
4. A resposta JSON atualiza o card e os contadores no navegador.

## Testes e verificação

Os testes devem cobrir:

- criação manual de contas a receber e pagar;
- validação de tipo, status, descrição, valor e referências opcionais;
- isolamento entre URLs de receber e pagar;
- ordenação por vencimento;
- marcação de vencidos apenas para pendentes;
- movimento para pago preenchendo `data_pagamento`;
- retorno para pendente limpando `data_pagamento`;
- inexistência de efeitos no fluxo de criação e revisão de propostas;
- respostas de erro da API e recuperação visual prevista no JavaScript.

A verificação final deve executar a suíte automatizada disponível, validar a criação da tabela em banco limpo, testar os dois murais no navegador em desktop e mobile e confirmar que criação, revisão, clonagem e geração DOCX/PDF de propostas continuam funcionando.
