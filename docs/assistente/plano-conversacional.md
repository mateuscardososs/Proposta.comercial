# Plano de implementacao conversacional

1. Ampliar o contrato do provedor com resultados de consulta, estado pendente e conjunto de ferramentas permitido.
2. Escrever testes para resposta livre, consulta seguida de sintese, duas consultas, limite de loop, estado pendente e fundamentacao.
3. Implementar o ciclo limitado no servico, mantendo o caminho atual de criacao e confirmacao.
4. Simplificar o prompt do Ollama para conversa como comportamento principal e aceitar texto natural sem ferramenta.
5. Escrever testes de voz para pausa tolerante e texto falado sem Markdown, IDs ou diagnosticos; implementar os ajustes.
6. Executar regressao, validar conversas completas com o Ollama real e banco isolado, registrar latencias e reiniciar a porta 8011.

## Criterios de conclusao

- relatos e perguntas gerais recebem resposta natural contextual;
- fatos do quadro so aparecem depois de consulta real;
- consulta e orientacao podem ocorrer na mesma mensagem;
- ate duas consultas distintas podem compor uma resposta, sem loop;
- rascunho pendente chega ao modelo como estado estruturado;
- criacao continua exigindo confirmacao e permanece idempotente;
- voz nao le Markdown, IDs ou diagnosticos e tolera pausas naturais;
- modelo, banco e arquivos reais de operacao permanecem inalterados.
