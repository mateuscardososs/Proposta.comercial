# Defeitos e riscos anteriores identificados na refatoração

Estes itens não foram corrigidos nesta tarefa para cumprir a restrição de não
misturar refatoração e mudança de comportamento. Não são regressões das extrações.

## RF-01 — resumo pode descrever quadro vazio após falha da fonte

**Confirmado com banco SQLite em memória e fonte de tarefas sintética que lança
erro**, em 08/10/2026. Sem dados operacionais ou serviços externos.

`daily_brief_service.build_daily_brief` conserva `tasks_open=0` quando a fonte
falha e identifica a fonte como `failed`. A apresentação existente usa esse zero
e a ausência de itens para afirmar “Consultei o quadro: não há tarefas abertas”,
além de avisar que há fontes com problema. O aviso não torna a afirmação correta.

Resultado do diagnóstico: `synthetic_task_source_state=failed` e
`existing_reply_claims_empty_tasks=True`. A lógica já estava no método original;
foi movida literalmente para `app/assistant/day_presentation.py`.

Correção funcional recomendada: condicionar afirmações de consulta e vazio ao
estado `success`/`empty` da fonte de tarefas; para `failed`/`unavailable`, mostrar
indisponibilidade mantendo as outras fontes. Testar também resumo falado e cache
parcial. Não substituir ausência de resultado confiável por contagem zero.

## RF-02 — vocabulário amplo/incompleto nos detectores

Caracterização anterior à extração das intenções confirmou limites no código
existente: “corrija” não corresponde a `corrig*`; plural “urgentes” não ativa o
filtro singular; “segunda via” satisfaz a detecção de data por substring.

Uma eventual correção deve ser tratada como mudança de interpretação com
regressão das paráfrases e das ações pendentes, mantendo o roteamento fiscal e
financeiro protegido. Não houve alteração de regex nesta refatoração.

## RF-03 — política diferente para falha ambígua de commit documental

Identificado por inspeção do código, **sem reproduzir em banco operacional**:
propostas removem arquivos em exceção de commit; relatórios reconciliam se a
gravação foi aceita antes da limpeza. Não foi criado helper comum que apagasse
essa diferença. Avaliar a política de propostas em tarefa de correção própria,
com falhas simuladas antes/depois da persistência.

## RF-04 — startup executa operações operacionais

Inspeção de `app/main.py` e `app/assistant/email/worker.py`: inicialização aplica
compatibilidade/backfill e inicia workers; Yahoo realiza uma leitura antes de
aguardar o intervalo. Por isso a instância 8013 não foi iniciada neste trabalho.

Uma restauração precisa de procedimento que trate esses efeitos explicitamente,
sem desligar autenticação ou descartar estado. Nenhuma configuração ou migração
operacional foi alterada para contornar essa condição.
