# Dashboard executivo — Design

## Objetivo

Transformar a página inicial existente em um dashboard executivo que resuma financeiro, tarefas e propostas usando somente dados já persistidos em `Lancamento`, `Task` e `Proposal`.

O dashboard será a página canônica de início em `GET /`. Esse é o caminho mais natural no projeto atual porque `app/routers/pages.py` já registra `web_index` em `/`, o item “Início” da navegação já aponta para `/` e `index.html` já representa a página inicial. Não será criada uma rota concorrente em `/web/dashboard`.

## Escopo aprovado

### Financeiro

- Exibir o valor total pendente em Contas a Receber: soma de `Lancamento.valor` quando `tipo = "receber"` e `status = "pendente"`.
- Exibir quanto do total a receber está vencido: mesmo filtro, acrescido de `data_vencimento < hoje`.
- Exibir o valor total pendente em Contas a Pagar: soma de `Lancamento.valor` quando `tipo = "pagar"` e `status = "pendente"`.
- Exibir quanto do total a pagar está vencido: mesmo filtro, acrescido de `data_vencimento < hoje`.
- Ignorar lançamentos com `status = "pago"` em todos os quatro indicadores.

### Tarefas

- Exibir a quantidade de tarefas atrasadas quando `status != "concluido"`, `prazo IS NOT NULL` e `prazo < hoje`.
- Exibir a quantidade de tarefas em A Fazer, com `status = "a_fazer"`.
- Exibir a quantidade de tarefas em Em Andamento, com `status = "em_andamento"`.
- As demais colunas atuais do Kanban continuam funcionando, mas não ganham KPIs nesta primeira versão do dashboard.

### Propostas

- Exibir a quantidade de propostas cuja `data_geracao` pertença ao mês corrente.
- Exibir a soma de `Proposal.valor_total` para o mesmo período.
- Definir o mês corrente pelo intervalo semiaberto `[primeiro_dia_do_mes, primeiro_dia_do_mes_seguinte)`, evitando dependência de funções específicas do PostgreSQL e cobrindo corretamente dezembro/janeiro.

### Página inicial

- Substituir os indicadores atuais de clientes, usuários e total histórico de propostas em `index.html` pelos indicadores aprovados acima.
- Remover da página inicial a tabela “Últimas propostas”, evitando carregar registros e relacionamentos que não fazem parte do dashboard aprovado.
- Manter o item “Início” da navbar apontando para `/` e ativo nessa rota.
- Renderizar o dashboard em largura total por meio do suporte `full_width` já existente em `base.html`.

## Fora de escopo

- Novos models, tabelas, migrations ou alterações de schema.
- Agenda de manutenção, propostas por upload externo ou cards “em breve”.
- Gráficos, séries históricas, comparação com meses anteriores ou metas.
- Fluxo de caixa projetado, saldo, lucro, inadimplência percentual ou conciliação bancária.
- Listas detalhadas de lançamentos, tarefas ou propostas dentro do dashboard.
- Contagem das colunas `servico_feito_falta_nota_pedido`, `aguardando_cliente` e `concluido` como KPIs.
- Alterações nos fluxos de criação, revisão, clonagem ou geração DOCX/PDF de propostas.
- Alterações nos murais financeiros ou no drag-and-drop do Kanban.
- Cache persistente ou atualização automática por polling/WebSocket.
- Nova rota `/web/dashboard`; `/` permanece a URL canônica.

## Arquitetura

As agregações ficarão em um service dedicado, `app/services/dashboard_service.py`. Isso mantém o router de páginas responsável apenas por receber a requisição e renderizar o template, sem misturar regras de consolidação com os services operacionais de tarefas e financeiro.

O service executará três consultas de leitura:

1. uma consulta agregada sobre `lancamentos` para os quatro valores financeiros;
2. uma consulta agregada sobre `tasks` para os três contadores de tarefas;
3. uma consulta agregada sobre `proposals` para quantidade e valor do mês.

Nenhuma consulta carregará instâncias completas, relacionamentos ou coleções. Serão usados `func.sum`, `func.count`, `case` e `func.coalesce` do SQLAlchemy, com filtros executados no banco.

### Arquivos novos

- `app/services/dashboard_service.py`: cálculo do período mensal e consultas agregadas.
- `tests/test_dashboard_service.py`: regras de agregação, limites de data e quantidade de consultas.
- `tests/test_dashboard_routes.py`: renderização da página inicial e contrato visual.

### Arquivos alterados

- `app/routers/pages.py`: substituir as queries atuais de `index()` por uma chamada ao dashboard service.
- `app/templates_web/index.html`: substituir o painel comercial atual pelas três seções do dashboard.
- `app/templates_web/base.html`: somente o modificador visual mínimo do KPI vencido, caso o estilo ainda não exista.

Não serão alterados `app/models.py`, `app/schemas.py`, `app/services/board_service.py`, `app/services/lancamento_service.py` nem os routers dos módulos existentes.

## Modelo e queries

### Contrato do service

O service exporá uma função única:

```python
def get_dashboard_summary(
    db: Session,
    reference_date: date | None = None,
) -> DashboardSummary:
    ...
```

`reference_date` usará `date.today()` quando omitida e poderá ser informada nos testes para tornar os limites de hoje e do mês determinísticos.

`DashboardSummary` será uma estrutura Python tipada, não um model SQLAlchemy, com os campos:

- `receber_pendente: Decimal`;
- `receber_vencido: Decimal`;
- `pagar_pendente: Decimal`;
- `pagar_vencido: Decimal`;
- `tarefas_atrasadas: int`;
- `tarefas_a_fazer: int`;
- `tarefas_em_andamento: int`;
- `propostas_mes_quantidade: int`;
- `propostas_mes_valor: Decimal`;
- `mes_inicio: date`;
- `mes_fim_exclusivo: date`.

A estrutura poderá ser uma `@dataclass(frozen=True)` definida no próprio service. Ela não cria tabela, schema de API ou estado persistente.

### Consulta financeira

A consulta filtrará `Lancamento.status == "pendente"` e calculará, com agregação condicional, as somas por tipo e por vencimento. Valores sem registros usarão `coalesce(..., 0)` e serão convertidos para `Decimal("0.00")` no contrato final.

Um lançamento com vencimento igual a hoje não está vencido. Somente `data_vencimento < reference_date` recebe essa classificação.

### Consulta de tarefas

Uma única consulta usará contagens condicionais para:

- `Task.status == "a_fazer"`;
- `Task.status == "em_andamento"`;
- `Task.status != "concluido" AND Task.prazo IS NOT NULL AND Task.prazo < reference_date`.

A contagem de atrasadas inclui qualquer coluna não concluída, inclusive `servico_feito_falta_nota_pedido` e `aguardando_cliente`, desde que o prazo esteja preenchido e tenha passado.

### Consulta de propostas

Uma única consulta aplicará:

```text
Proposal.data_geracao >= mes_inicio
Proposal.data_geracao < mes_fim_exclusivo
```

e retornará `COUNT(Proposal.id)` e `COALESCE(SUM(Proposal.valor_total), 0)`.

## Interface

A página reutilizará `page-header`, `.card`, `.card-head`, `.kpi-grid`, `.kpi-card`, `.kpi-label`, `.kpi-value`, `.kpi-note`, `.badge` e `.btn` já disponíveis em `base.html`.

### Cabeçalho

- Título: “Visão geral da empresa”.
- Subtítulo: “Financeiro, tarefas e propostas em um único lugar.”
- Badge com o mês/ano de referência das propostas.

### Seção Financeiro

Uma `.card` com quatro KPIs:

1. A receber pendente;
2. A receber vencido;
3. A pagar pendente;
4. A pagar vencido.

Valores monetários usarão `format_brl`, já fornecido por `render_template`.

Os dois KPIs vencidos usarão um modificador visual do componente existente, por exemplo `.kpi-card.is-danger`, com borda e valor em `var(--danger)` e fundo vermelho suave consistente com `.kanban-card.is-overdue`. O destaque será aplicado apenas quando o valor vencido for maior que zero; quando for zero, o KPI permanece neutro.

### Seção Tarefas

Uma `.card` com três KPIs:

1. Tarefas atrasadas;
2. A Fazer;
3. Em Andamento.

“Tarefas atrasadas” usará o mesmo modificador de perigo apenas quando a contagem for maior que zero.

### Seção Propostas do mês

Uma `.card` com dois KPIs:

1. Propostas geradas no mês;
2. Valor total das propostas do mês.

O valor total usará `format_brl`. A seção mostrará claramente o mês/ano correspondente ao intervalo calculado.

### Navegação e responsividade

- O dashboard não criará um novo item de navbar; o item existente “Início” continua sendo a entrada.
- A página usará `full_width=True`, sem os painéis laterais de atalhos e produtividade.
- Os breakpoints existentes de `.kpi-grid` serão reutilizados: múltiplas colunas em desktop e uma coluna em telas pequenas.
- Não será criado CSS estrutural paralelo ao design system existente.

## Fluxos

### Carregamento da página

1. O navegador solicita `GET /`.
2. `pages.index()` recebe a sessão e chama `dashboard_service.get_dashboard_summary(db)`.
3. O service determina `hoje`, `mes_inicio` e `mes_fim_exclusivo`.
4. O service executa as três consultas agregadas e monta `DashboardSummary`.
5. O router renderiza `index.html` com `summary` e `full_width=True`.
6. O template formata moedas e aplica o destaque de perigo somente aos indicadores vencidos/atrasados positivos.

### Banco vazio

Se não houver lançamentos, tarefas ou propostas, todos os totais e contadores serão zero. A página continuará respondendo HTTP 200 e exibirá `R$ 0,00` nos indicadores monetários, sem estados vazios adicionais ou cards fictícios.

### Falha de consulta

Não haverá ocultação silenciosa nem valores fabricados quando o banco falhar. A exceção seguirá o tratamento padrão da aplicação e resultará em erro de servidor, preservando a causa nos logs do processo.

## Testes e verificação

### Testes do service

Os testes devem cobrir:

- separação entre receber e pagar;
- exclusão de lançamentos pagos dos totais;
- vencimento estrito (`< hoje`), confirmando que vencimento igual a hoje não está atrasado;
- tarefas atrasadas somente quando não concluídas, com prazo preenchido e anterior a hoje;
- contagem independente de `a_fazer` e `em_andamento`;
- inclusão das demais colunas não concluídas na contagem de atrasadas;
- exclusão de tarefas concluídas da contagem de atraso;
- propostas no primeiro e no último dia válido do mês;
- exclusão de propostas anteriores ao início e iguais ao primeiro dia do mês seguinte;
- transição de dezembro para janeiro no cálculo do intervalo;
- retorno de inteiros e `Decimal("0.00")` em banco vazio;
- execução de no máximo três consultas SQL de leitura pelo service.

### Testes da rota e do template

Os testes devem confirmar:

- `GET /` responde HTTP 200;
- a rota usa o dashboard novo, sem os KPIs antigos de clientes/usuários e sem a tabela de últimas propostas;
- as três seções e os nove indicadores aprovados são renderizados;
- valores monetários são formatados em reais;
- indicadores vencidos/atrasados positivos recebem a classe de perigo;
- indicadores zerados permanecem neutros;
- a página usa o layout em largura total e o item “Início” continua ativo;
- não existem seções ou textos de funcionalidades “em breve”.

### Verificação final

- Executar a suíte completa localmente e no container Docker com as dependências fixadas do projeto.
- Confirmar `git diff --check` e compilação dos módulos Python.
- Validar que `/`, `/web/board`, `/web/contas-a-receber`, `/web/contas-a-pagar` e `/web/proposals` respondem sem regressão.
- Inspecionar o dashboard em desktop e mobile, verificando hierarquia, responsividade e contraste do destaque `var(--danger)`.
- Confirmar no log de queries ou por instrumentação de teste que o carregamento do dashboard usa no máximo três consultas agregadas e não carrega coleções completas.
