# Validação local — registro e acompanhamento de serviços

Data: 2026-10-02. Instância restrita ao loopback em `127.0.0.1:8011`.

## Ambiente e isolamento

- Desenvolvimento executado no Mac com Apple Silicon M5.
- Ollama local em `http://127.0.0.1:11434`, modelo `qwen3:4b-instruct-2507-q4_K_M` (Q4_K_M, já instalado). Nenhum modelo foi baixado nesta etapa.
- Banco de teste da instância: `/tmp/ad-balancas-services-8011/app.sqlite3`; documentos e saída também ficam sob `/tmp/ad-balancas-services-8011/`.
- A carga contém três clientes explicitamente sintéticos, um responsável fictício, chamados e tarefas com prefixo `[SINTÉTICO]`.
- O banco anterior de teste em `/tmp/ad-balancas-conversational.xFP65K` foi preservado. O banco operacional não foi usado.
- `.env.yahoo.local` continua fora do Git e não foi lido pelo relatório. Nenhuma consulta à conta Yahoo foi feita para validar serviços; sua integração permanece somente leitura.
- A aplicação antiga da porta 8000 não foi modificada.
- Uma consulta natural real executada pela API da instância retornou o chamado sintético da Alfa Serviços, indicou relatório pendente e reconheceu o evento de inspeção registrado. A solicitação usou uma consulta e uma resposta natural do modelo, sem reparo; não consultou tarefas nem caixa de e-mail.

## Comportamentos cobertos

1. Inspeção cria evento `inspection` e não conclui a execução.
2. Execução iniciada e conclusão explícita são projetadas separadamente do encerramento administrativo.
3. Cliente ambíguo gera pergunta de esclarecimento; não é escolhido um ID por aproximação.
4. Campos administrativos passam por rascunho e confirmação; transições mantêm etapa, estado anterior/novo, observação e ação.
5. Correção de evento confirmado acrescenta evento de correção, preserva o original e recompõe a projeção técnica.
6. Correção do rascunho anterior à confirmação cancela o token antigo e emite uma nova confirmação.
7. Cancelar um rascunho não cria chamado, evento nem tarefa.
8. Lembretes usam o serviço existente do quadro, ficam ligados ao chamado e a confirmação repetida não duplica tarefas.
9. Alegações de estado técnico/administrativo contraditórias à consulta real ou sobre ID não apresentado são rejeitadas.
10. A interface recebe links para abrir chamado e cada tarefa associada.

## Evidência executada

- Suite Python completa: **409 passed, 5 skipped**. Os skips incluem testes opt-in de provedores reais. Os avisos restantes são deprecações do SQLAlchemy/Starlette/FastAPI já existentes.
- JavaScript de chat e voz: **18 passed**, incluindo renderização dos links para chamado e lembretes.
- Integração real do Ollama: executada com `RUN_OLLAMA_LIVE=1` e o modelo local listado acima. O modelo classificou o relato sintético como inspeção; a ação só persistiu após confirmação e o estado final permaneceu `not_started`. Resultado: **1 passed**, duração observada do caso completo **2,56 s** com o modelo aquecido; uma execução inicial mediu **9,17 s**. São observações isoladas, não mediana nem garantia de desempenho.
- Testes SQLite verificam `PRAGMA foreign_keys=ON`, guardas de imutabilidade, `RESTRICT`, correção append-only, replay/idempotência e rollback. As conexões SQLAlchemy usadas pela aplicação e pelo seed recebem a configuração; conexões SQLite abertas diretamente com `sqlite3` fora do SQLAlchemy não são abrangidas pelo listener.
- O PostgreSQL foi declarado na implementação das guardas, mas **não foi executado** contra container/servidor PostgreSQL nesta validação. Validação PostgreSQL e inspeção de plano de migração nesse backend permanecem pendentes.

O tempo de carregamento do modelo não foi separado do tempo do primeiro caso e não foi medido por etapa nesta entrega. Também não houve validação de STT/TTS, microfone no navegador, Windows/Ryzen ou conta de e-mail real.

Durante a consulta HTTP real, a primeira validação detectou que a camada de escopo interpretava a resposta pós-consulta como função indisponível, pois a ferramenta de leitura é removida da allowlist após seu uso. A regra agora aceita a resposta natural quando existe evidência de consulta bem-sucedida no mesmo pedido, mantendo apenas `responder_conversa` permitido na rodada seguinte. O resultado compacto inclui eventos efetivos e estados das cinco etapas; a repetição do teste real passou sem alegar que a inspeção não ocorreu nem que consultou tarefas.

## Iniciar e testar manualmente

Com Ollama já ativo em loopback, a partir da raiz do projeto:

```bash
DATABASE_URL=sqlite:////tmp/ad-balancas-services-8011/app.sqlite3 \
SERVICE_VALIDATION_ALLOW_SYNTHETIC_SEED=1 PYTHONPATH=. \
.venv/bin/python scripts/seed_assistant_service_validation.py
./scripts/run_assistant_8011_yahoo.sh
```

Abra [http://127.0.0.1:8011/web/assistente](http://127.0.0.1:8011/web/assistente). Se a porta já estiver ocupada, confira o PID e encerre somente a instância 8011 conhecida; não toque na 8000. O launcher verifica credenciais localmente, mantém o Yahoo em modo de leitura e não imprime os valores.

Roteiro sugerido:

1. “Fui à Alfa” — deve perguntar qual das empresas Alfa.
2. “Alfa Serviços Sintética; fiz só uma inspeção, sem conserto” — revisar e confirmar; a execução deve continuar não iniciada.
3. “Terminei o reparo na Beta Comércio Sintética” — revisar e confirmar; a conclusão técnica não encerra as etapas administrativas.
4. Consultar o chamado; depois informar que falta o relatório e, em outra ação confirmada, que aguarda o cliente.
5. Solicitar correção do evento de execução para inspeção — confirmar; o histórico anterior permanece e a projeção deixa de mostrar execução concluída.
6. Pedir lembretes de relatório e proposta para um chamado exibido — confirmar; abrir os links e repetir a confirmação para verificar idempotência.
7. Cancelar um rascunho e conferir que nada foi persistido.

Para voz, repetir exatamente os mesmos enunciados usando o microfone; STT apenas encaminha a transcrição ao mesmo endpoint textual, sem caminho paralelo de gravação. A qualidade por microfone e sintetizador depende de teste humano.
