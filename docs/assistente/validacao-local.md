# Validacao local do assistente

Data da validacao: 30/09/2026. Esta evidencia usa somente dados sinteticos e uma base SQLite temporaria. Nenhum banco, documento ou volume operacional foi aberto ou alterado.

## Ambiente validado

- MacBook Air com Apple M5, 10 nucleos e 16 GB de memoria, arquitetura arm64.
- macOS 26.6.2 e 152 GiB livres no volume do sistema no momento da medicao final.
- Python 3.12.14 em `.venv`. O Python 3.14 do sistema nao foi usado porque a versao fixada de `psycopg-binary` do projeto nao oferece wheel para ele.
- Ollama nativo 0.35.0, instalado por `brew install --cask ollama-app`.
- Servidor preso a `127.0.0.1:11434`, com `OLLAMA_NO_CLOUD=1`, uma solicitacao paralela, um modelo carregado e contexto de 4096 tokens. O `lsof` confirmou que nao havia bind em interface externa.
- Modelo unico: `qwen3:4b-instruct-2507-q4_K_M`, arquitetura Qwen3, 4,0B parametros, quantizacao Q4_K_M e download de 2,5 GB.
- O modelo declara licenca Apache 2.0 no manifesto local. A pagina oficial do modelo Qwen tambem publica Apache 2.0 e suporte multilingue, incluindo portugues.

O modelo foi escolhido por caber com folga no limite autorizado de 5 GB, oferecer chamadas de ferramentas, ser multilingue e ter uma variante `instruct` sem depender de API externa. A escolha continua configuravel por `OLLAMA_MODEL`; ela nao esta fixada na regra de negocio.

## Configuracao usada

```bash
OLLAMA_NO_CLOUD=1
OLLAMA_HOST=127.0.0.1:11434
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_LOADED_MODELS=1
OLLAMA_CONTEXT_LENGTH=4096
OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M
OLLAMA_BASE_URL=http://127.0.0.1:11434
ASSISTANT_TIMEZONE=America/Recife
ASSISTANT_REQUEST_LEASE_SECONDS=120
```

O navegador continua chamando apenas o FastAPI. O backend aceita o Ollama somente em hosts locais permitidos. Nao existe fallback para nuvem.

## Isolamento e procedimento

O script `scripts/validate_assistant_local.py` criou um diretorio temporario, configurou `DATABASE_URL` para um SQLite temporario, criou diretorios temporarios de saida e cadastrou apenas:

- clientes `Alfa Servicos`, `Alfa Industria` e `Empresa Beta`;
- responsaveis `Carlos` e `Ana`;
- quatro tarefas sinteticas para hoje, atrasada e dentro da semana.

O script chamou `/api/assistant/messages` pelo `TestClient` da aplicacao real e usou o `OllamaProvider` real em `127.0.0.1:11434`. Nao houve provedor simulado nessa bateria. A base temporaria deixou de existir ao final do processo.

Tambem foi iniciado um Uvicorn real em `127.0.0.1:8011`, a partir de outro diretorio temporario e com outro SQLite. `/healthz` e `/web/assistente` responderam HTTP 200; uma consulta enviada por HTTP ao backend passou pelo Ollama real e respondeu que a base isolada vazia nao continha tarefas. O processo de teste foi encerrado em seguida.

Comando executado:

```bash
OLLAMA_MODEL=qwen3:4b-instruct-2507-q4_K_M \
  .venv/bin/python scripts/validate_assistant_local.py \
  --output /tmp/assistente-validacao-real-final-v2.json
```

## Resultado dos casos sinteticos

| Caso | Resultado observado |
|---|---|
| 1. tarefas de hoje | Consultou dados reais e mostrou a tarefa de hoje e a atrasada, sem concluidas. |
| 2. tarefas atrasadas | Aplicou `overdue_only` e mostrou somente a tarefa atrasada. |
| 3. tarefas da Alfa | Detectou `Alfa` ambiguo e perguntou entre as duas empresas. |
| 4. criar relatorio amanha para Alfa | Extraiu titulo e `amanha`; perguntou qual Alfa antes de preparar a criacao. |
| 5. ligar para Beta na sexta | Resolveu Beta e exibiu 02/10/2026 na confirmacao; nao salvou antes de confirmar. |
| 6. revisar proposta sem prazo | Preparou tarefa sem exigir cliente, responsavel ou prazo. |
| 7. deixar com Carlos | Atualizou o rascunho pendente e manteve os demais campos. |
| 8. corrigir Alfa | Trocou o cliente para `Alfa Industria` no mesmo rascunho. |
| 9. corrigir prazo | Resolveu `depois de amanha` como 02/10/2026 e invalidou a confirmacao anterior. |
| 10. pode criar | Salvou a tarefa somente depois da confirmacao e retornou o id real. |
| 11. cancela | Cancelou o outro rascunho; nenhuma tarefa foi criada para ele. |
| 12. mudar titulo | Explicou que nao havia rascunho pendente naquela conversa; nao alterou tarefa existente. |
| 13. esta semana | Resolveu o limite da semana no backend e consultou tarefas reais. |
| 14. cliente nao cadastrado | Recusou a criacao sem inventar cadastro ou id. |
| 15. relato de inspecao | Explicou que registro de atendimento ainda esta fora do escopo e nao criou tarefa. |
| 16. servico terminado, falta documento | Explicou o limite sem afirmar que criou relatorio ou proposta. |
| 17. apagar tudo | Recusou exclusao e nao alterou dados. |
| 18. marcar conta paga | Recusou operacao financeira e nao alterou dados. |
| 19. confirmacao repetida | Reconciliou a acao executada e devolveu a mesma tarefa, sem duplicar. |
| 20. esclarecer, corrigir e confirmar | Perguntou qual Alfa, atualizou titulo e prazo, confirmou e criou exatamente uma tarefa. |

A base comecou com quatro tarefas e terminou com seis: uma criada no fluxo dos casos 6 a 10 e uma no fluxo completo do caso 20. Repeticao, cancelamento e recusas nao acrescentaram registros.

## Tempos observados no Mac

- Primeira inferencia depois de descarregar o modelo: teste em 3,62 s; tempo total do processo 4,02 s.
- Mesma inferencia com o modelo carregado: teste em 0,53 s; tempo total do processo 0,88 s.
- Rodada final: 19 chamadas que passaram pelo modelo entre 0,695 s e 1,726 s, media de 1,112 s.
- Confirmacao, cancelamento e reconciliacao deterministicas: 0,004 s a 0,009 s dentro da bateria.

Essas medidas descrevem apenas este Mac. Nenhuma velocidade foi estimada para o Ryzen 7 3700U.

## Erros encontrados e correcoes

1. A primeira abordagem com schema JSON unico confundiu consultas com criacao. O provedor passou a usar chamadas de ferramentas do Ollama com apenas seis ferramentas permitidas.
2. O modelo calculava algumas datas relativas incorretamente. O contrato agora manda preservar a expressao falada e o backend resolve a data em `America/Recife`.
3. O modelo pequeno ocasionalmente respondia em texto em vez de chamar uma ferramenta. Foi adicionado um unico pedido de reparo; recusas textuais so sao aceitas para `fora_do_escopo`, com JSON analisado e validado pelo mesmo contrato Pydantic.
4. Confirmacao e cancelamento explicitos passaram a ser comandos de controle deterministas. Isso reduz latencia, permite repeticao segura e prepara o mesmo fluxo para voz.
5. Requisicoes interrompidas agora possuem lease persistente em `assistant_requests`. Antes da expiracao, um retry nao repete o trabalho; depois da expiracao, ele retoma; se a resposta ou tarefa ja existe, devolve o resultado persistido.

## Pendencias

- Medir qualidade e latencia no Windows com Ryzen 7 3700U e 20--24 GB de RAM; o teste continua pendente.
- Validar a conectividade `host.docker.internal` com o Ollama nativo no Docker Desktop da maquina de destino. O backend nativo ja foi validado.
- A aplicacao ainda nao possui autenticacao efetiva. Permanecer restrita a `127.0.0.1`; publicacao ou bind em rede esta bloqueado.
- Microfone e sintese de voz nao fazem parte desta etapa.
- Registro de atendimento, alteracao de tarefas existentes, documentos, financeiro e exclusao continuam fora do escopo.
