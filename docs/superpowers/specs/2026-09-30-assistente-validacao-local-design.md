# Assistente local real — desenho da validação

## Objetivo

Executar o assistente com Ollama nativo e um único modelo local, validar o fluxo completo em português sobre dados sintéticos isolados e corrigir apenas as lacunas necessárias para confirmação, cancelamento, correção de rascunho e recuperação de requisições interrompidas.

## Runtime escolhido

- Ollama nativo no macOS, limitado a `127.0.0.1:11434`, com recursos de nuvem desativados.
- Modelo `qwen3:4b-instruct-2507-q4_K_M`, 4B, quantização Q4_K_M, download publicado de 2,5 GB e licença Apache 2.0.
- Contexto de 4096 tokens, um modelo carregado e uma inferência por vez.
- Python 3.12 em `.venv`, alinhado ao README e ao Dockerfile.
- FastAPI nativo acessa `http://127.0.0.1:11434`; no Docker, o backend usa `http://host.docker.internal:11434`. O navegador nunca acessa Ollama.

## Contrato conversacional

O provedor continua retornando somente comandos Pydantic discriminados. Além de `consultar_tarefas`, `criar_tarefa` e `fora_do_escopo`, serão aceitos:

- `confirmar_acao`: confirma o último rascunho pendente da conversa;
- `cancelar_acao`: cancela o último rascunho pendente;
- `corrigir_tarefa`: altera campos explícitos do último rascunho, com flags específicas para remover prazo, cliente ou responsável.

Campos opcionais de `Task` permanecem opcionais. O backend, não o modelo, resolve clientes e responsáveis, normaliza datas em `America/Recife`, aplica correções e persiste tarefas. Uma correção atualiza a ação pendente, gira o hash de confirmação e torna o token anterior inválido. Toda criação mantém uma confirmação breve.

Pedidos de exclusão, financeiro, atendimento/serviço executado, documentos, mensagens ou emissão fiscal retornam `fora_do_escopo`; nenhuma ferramenta nova será criada para atendê-los.

## Recuperação persistente

Uma tabela independente `assistant_requests` registra `request_id`, conversa, mensagem do usuário, estado, lease, tentativas e resposta associada. A criação da requisição e da mensagem ocorre na mesma transação.

- `processing` com lease válido: o retry recebe “ainda em processamento” e não chama o modelo novamente;
- `processing` expirado: uma atualização condicional toma o lease e reexecuta apenas a interpretação segura;
- `completed`: o retry devolve a resposta persistida;
- gravações continuam protegidas pela ação idempotente e pela transação que cria tarefa e marca ação como executada.

A duração do lease será configurável por `ASSISTANT_REQUEST_LEASE_SECONDS`, com padrão superior ao timeout de leitura do Ollama.

## Validação isolada

Um runner local criará diretório temporário, banco SQLite próprio e cadastros fictícios, incluindo `Alfa Serviços`, `Alfa Indústria`, `Beta` e responsáveis fictícios. Ele chamará os endpoints FastAPI reais, que chamarão o Ollama real. Consultas e tarefas serão conferidas diretamente no banco temporário. Tempos serão medidos com relógio monotônico, distinguindo carregamento inicial e chamadas subsequentes.

Os vinte casos fornecidos serão registrados com resultado observado, comando interpretado ou limitação segura. Falhas de qualidade do modelo poderão resultar em ajustes do prompt/contrato, nunca em SQL, shell, código gerado ou ferramenta adicional fora do escopo.

## Segurança e limites

- Sem API paga, fallback externo, exposição de rede, microfone ou síntese.
- Sem acesso ao banco operacional, `output/`, documentos ou volumes Docker existentes.
- Conteúdo do usuário e registros são dados não confiáveis; o prompt deixa explícito que não são instruções para ampliar ferramentas.
- O desempenho no Ryzen não será inferido a partir do Mac.
- Enquanto não houver autenticação, a aplicação continuará restrita a loopback.

## Critérios de aceitação

1. Ollama e o modelo respondem localmente com saída estruturada válida.
2. O fluxo real consulta tarefas sintéticas, prepara criação, corrige, confirma e cancela por texto.
3. Ambiguidade e cadastro inexistente geram pergunta sem ID inventado.
4. Datas relativas são persistidas e exibidas corretamente.
5. Confirmação repetida não duplica tarefa e token antigo falha após correção.
6. Uma requisição expirada é retomada; uma requisição concluída é reconciliada sem nova inferência.
7. Pedidos fora do escopo não alteram tarefas ou financeiro.
8. Evidências e latências reais ficam em `docs/assistente/validacao-local.md`.
