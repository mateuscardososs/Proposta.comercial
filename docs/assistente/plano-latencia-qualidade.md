# Plano de latencia e qualidade

1. Cobrir por testes a coleta de telemetria do Ollama, inclusive fila, tokens, carga,
   inferencias rejeitadas e motivo de reparo.
2. Propagar a telemetria pelo servico e persisti-la junto da resposta, sem expor dados
   internos ao modelo nem credenciais.
3. Medir fila e processamento de STT e TTS nas respostas HTTP.
4. Executar uma linha de base repetida em banco temporario, com o modelo local atual.
5. Enxugar prompt e contexto, retirar contratos desnecessarios depois de consultas e
   impedir repeticao da mesma consulta na mensagem.
6. Criar casos novos e criterios verificaveis de qualidade, incluindo referencias
   tecnicas externas quando houver fonte primaria adequada.
7. Repetir o benchmark, comparar mediana, pior caso, acerto, inferencias e reparos.
8. Rodar regressao automatizada, teste real controlado e reiniciar somente a instancia
   isolada da porta 8011.

## Criterios de aceite

- Cada inferencia real tem contagens e tempos observaveis, sem prompt ou raciocinio salvo.
- Consultas nao executam duas vezes os mesmos argumentos na mesma mensagem.
- Confirmacoes simples permanecem sem inferencia e idempotentes.
- Uma resposta de consulta usa apenas dados consultados.
- STT e TTS informam fila e processamento separadamente.
- O relatorio apresenta repeticoes, mediana, pior tempo, acerto e numero de inferencias.
- A instancia 8011 usa apenas banco e documentos isolados e continua disponivel ao final.
