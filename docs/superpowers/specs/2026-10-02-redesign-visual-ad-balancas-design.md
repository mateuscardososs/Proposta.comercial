# Redesign visual do sistema AD Balanças

**Data:** 2026-10-02  
**Estado:** design aprovado para planejamento  
**Direção:** Operação calibrada, revisão 2

## Objetivo

Reformular visualmente as páginas reais do sistema interno da AD Balanças e Engenharia para criar uma experiência profissional, clara e eficiente no uso diário. O redesign deve preservar a aplicação FastAPI, os templates Jinja2, o JavaScript, o CSS, as rotas, os dados, as permissões e as regras de negócio existentes.

O trabalho não é uma demonstração isolada. A direção aprovada deve ser aplicada às páginas funcionais da aplicação.

## Referência e identidade

As referências fornecidas orientam a hierarquia, a densidade, o espaçamento e a organização:

- sidebar clara e legível;
- grande superfície central de trabalho;
- cabeçalho consistente;
- cartões brancos discretos;
- listas e tabelas fáceis de percorrer;
- cor reservada a ação, estado e prioridade;
- respostas estruturadas no Assistente.

O sistema não copiará marcas, textos, dados ou imagens comerciais das referências.

### Exploração do domínio

- **Conceitos:** precisão, calibração, serviço técnico, rastreabilidade e prazo.
- **Mundo de cor:** azul de instrumento, grafite, branco técnico, verde-azulado, âmbar e vermelho de alerta.
- **Assinatura:** pequena régua de medição usada como marcador discreto em áreas prioritárias.
- **Padrões rejeitados:** dashboard genérico, excesso de cartões, capa decorativa, gradientes, sombras pesadas e múltiplas cores de destaque.

## Arquitetura visual compartilhada

O redesign evoluirá os templates atuais sem trocar framework e sem introduzir uma aplicação paralela.

- `app/templates_web/base.html` concentrará tokens, estrutura global e componentes reutilizáveis.
- A sidebar será clara e fixa no desktop, recolhível por botão, com preferência persistida em `localStorage`.
- Em telas pequenas, a sidebar será um drawer com foco contido, fechamento por `Esc` e overlay.
- A navegação será agrupada em Operação, Comunicação, Comercial, Financeiro e Administração.
- Assistente permanecerá como item de primeiro nível, agrupado visualmente com E-mails e mensagens.
- O cabeçalho interno terá breadcrumbs, título, descrição breve e somente ações implementadas.
- O conteúdo ficará sobre uma superfície cinza-clara, com cartões brancos, bordas suaves e sombras mínimas.
- Azul institucional será usado para identidade e ações; verde para sucesso; âmbar para atenção; vermelho somente para atraso, erro e destruição.
- Ícones serão SVGs simples, consistentes e acessíveis, sem emojis nem biblioteca pesada.
- A régua de medição aparecerá apenas como assinatura discreta, sem decoração repetitiva.

### Componentes reutilizáveis

- botões primário, secundário, neutro, sucesso e destrutivo;
- campos, selects, textareas, upload e busca;
- grupos de filtros e barra de ferramentas;
- breadcrumbs e cabeçalho de página;
- KPIs compactos;
- cartões de resumo e listas operacionais;
- tabelas responsivas e listas estruturadas para celular;
- badges e etiquetas semânticas;
- alertas, mensagens de status e feedback de erro;
- estados vazios, carregamento e sucesso;
- menu acessível para mudança de estado;
- drawer móvel e sidebar recolhível.

O CSS compartilhado permanecerá inicialmente no template base para reduzir risco e preservar o padrão atual. Estilos específicos do Assistente e scripts existentes serão ajustados pontualmente, sem reescrever seus fluxos.

## Páginas

### Hoje

- saudação, data e resumo operacional do dia;
- quatro indicadores compactos: tarefas atrasadas, tarefas de hoje, serviços com pendência e e-mails para revisar;
- fila Precisa de atenção;
- agenda do dia;
- serviços em andamento;
- e-mails para revisar;
- contas próximas do vencimento;
- indicadores mensais em área secundária.

A ordem continuará derivada de `today_service`. Datas e horários só aparecerão quando existirem nos dados.

### Tarefas

O Kanban de cinco colunas e as ações de criar, editar, mover, concluir e excluir serão preservados.

- busca local;
- filtros por status, responsável, cliente e prazo;
- contagem total e por coluna;
- cartões compactos com título, prazo, responsável, cliente, proposta e origem de e-mail quando disponível;
- texto Cliente a identificar quando não houver vínculo;
- etiquetas derivadas para atraso, vencimento no dia e ausência de prazo;
- menu acessível para movimentação por teclado, além do arrastar e soltar.

`Task` não possui prioridade persistida nem nome livre de cliente. O redesign não criará esses dados: urgência será derivada do vencimento, e tarefas sem cliente usarão o texto Cliente a identificar.

### Serviços

A lista apresentará cliente, resumo, execução técnica, situação administrativa, próxima etapa e último evento quando disponível.

O detalhe será organizado em:

- resumo do chamado;
- próxima pendência;
- execução técnica;
- etapas administrativas;
- linha do tempo de eventos;
- correções vigentes;
- histórico das transições;
- lembretes vinculados.

O histórico append-only, as correções e os fluxos de confirmação serão preservados. Inspeção não será tratada visualmente como execução concluída.

### E-mails e mensagens

- indicadores de novas mensagens, prioridade e revisão;
- filtros locais por período, categoria, prioridade e estado de revisão;
- lista compacta com remetente, assunto, data, categoria e prioridade;
- detalhes expansíveis com resumo e evidência da classificação;
- ação sugerida e tarefa vinculada somente quando realmente disponíveis;
- categorias incertas destacadas como Revisar;
- estado real de sincronização, incluindo falha, pausa e último ciclo.

A operação Yahoo continuará somente leitura. O redesign não marcará mensagens como lidas, não enviará, moverá ou excluirá e-mails.

### Assistente

- histórico centralizado com largura confortável;
- mensagens do usuário e do assistente distintas sem excesso de balões;
- listas, resultados de e-mail, tarefas e confirmações em cartões compactos;
- composer fixo na parte inferior;
- controles de voz claramente identificados;
- estados para ouvindo, transcrevendo, revisando, processando e falando;
- transcrição revisável antes do envio;
- estilos próprios para rascunho, esclarecimento, confirmação, cancelamento e erro;
- ações exibidas somente quando disponíveis.

Os contratos, confirmações, cancelamentos e políticas de voz existentes não serão alterados pelo redesign.

### Propostas

- lista com busca e filtros derivados dos dados existentes;
- tabela responsiva com número, revisão, cliente, responsável, data, origem e valor;
- detalhe dividido em resumo comercial, cliente, documentos, itens, cronograma e financeiro;
- formulário longo organizado por etapas, preservando cálculos, atalhos e resumos em tempo real.

Criação, clonagem, duplicação, revisão, geração de DOCX/PDF e sugestões baseadas em propostas anteriores ficam fora de mudanças comportamentais.

### Importações e documentos

- área de upload destacada;
- formatos aceitos e instruções claras;
- estados de seleção, análise, preview, confirmação, progresso, sucesso e erro;
- preservação dos fluxos separados de PDF legado, upload externo e reenvio de Word.

### Clientes

- lista com busca e dados principais;
- detalhe com cadastro e propostas associadas;
- serviços associados somente quando houver vínculo confirmado;
- nenhum cadastro ou vínculo automático a partir de texto livre.

### Financeiro

Contas a receber e contas a pagar usarão tabelas operacionais responsivas com descrição, cliente ou fornecedor, valor, vencimento e situação.

- filtros e totais usarão dados reais;
- atraso e vencimento próximo serão comunicados por texto e cor;
- criação e edição atuais serão preservadas;
- mudança de situação usará o endpoint atual, por controle explícito e acessível;
- nenhuma tela fará baixa automática, emitirá nota ou alterará lançamento fora do fluxo autorizado.

### Usuários

Usuários permanecerá acessível no grupo Administração, preservando lista, pesquisa e cadastro atuais.

## Fluxo de dados

Routers e services existentes continuarão sendo a fonte de verdade. Templates receberão dados persistidos ou valores derivados de forma determinística.

- filtros simples atuarão sobre conteúdo já carregado quando isso não expuser dados adicionais;
- nenhum campo inexistente será simulado;
- mudanças de estado continuarão usando os endpoints existentes;
- ações otimistas restaurarão o estado anterior quando o backend rejeitar a mudança;
- nenhuma confirmação visual será mostrada antes da confirmação do backend.

Não haverá alteração de modelos, integração financeira, Yahoo, serviços, permissões ou startup para facilitar o design.

## Erros e estados

- falhas de movimentação restauram o estado anterior e mostram alerta acessível;
- formulários preservam valores preenchidos quando o fluxo existente permitir;
- upload diferencia seleção, análise, confirmação, sucesso e erro;
- caixa vazia, falha de sincronização e ausência de dados são estados diferentes;
- erros técnicos evitam conteúdo pessoal desnecessário;
- ações indisponíveis não aparecem como botões fictícios;
- estados vazios oferecem apenas próximos passos funcionais.

## Acessibilidade e responsividade

- foco visível e contraste equivalente a WCAG AA;
- skip link, labels, `aria-current` e regiões de status;
- ícones com nome acessível;
- status comunicados por texto e cor;
- navegação por teclado na sidebar, drawer, Kanban e financeiro;
- áreas de toque adequadas em celular;
- tabelas convertidas em listas estruturadas quando a leitura móvel exigir;
- ausência de rolagem horizontal na página;
- suporte a `prefers-reduced-motion`.

Larguras de referência: 1440, 1024, 768 e 390 pixels.

## Segurança e privacidade

- a aplicação continuará limitada a `127.0.0.1`;
- nenhuma autenticação fictícia será adicionada;
- notificações, logs e mensagens técnicas não exibirão conteúdo pessoal desnecessário;
- dados sintéticos serão usados em testes e capturas visuais;
- WhatsApp permanece fora do escopo.

## Verificação

1. Rodar toda a suíte Python e os testes JavaScript existentes antes e depois.
2. Adicionar testes somente para navegação, filtros, sidebar, drawer e alternativas acessíveis introduzidas.
3. Validar renderização das rotas com dados sintéticos.
4. Inspecionar visualmente todas as páginas em desktop e celular.
5. Testar sidebar expandida e recolhida, drawer, filtros, links, formulários, uploads, botões e estados vazios.
6. Testar movimentação por arrastar e por controle acessível.
7. Confirmar que criação, clonagem, revisão e geração DOCX/PDF permanecem funcionais e sem mudança comportamental.
8. Confirmar ausência de cortes, sobreposição, rolagem horizontal e textos ilegíveis.

## Limites de implementação

- não trocar FastAPI, Jinja2, JavaScript ou CSS;
- não remover recursos;
- não alterar modelos ou regras de negócio por conveniência visual;
- não adicionar dependências pesadas;
- não incluir dados reais em testes visuais;
- não fazer commit, push, merge ou deploy;
- preservar todas as mudanças existentes na branch;
- não introduzir Alembic.

## Resultado esperado

O sistema deve parecer um único produto interno da AD Balanças: sóbrio, preciso, legível e orientado ao trabalho. A interface deve tornar pendências, próximos passos e estados operacionais evidentes sem transformar todas as informações em cartões ou depender de cor para comunicar significado.
