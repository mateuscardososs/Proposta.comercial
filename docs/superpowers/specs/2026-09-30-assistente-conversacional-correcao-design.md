# Correcao da experiencia conversacional do assistente

## Problema confirmado

Na instancia isolada `127.0.0.1:8011`, o Ollama estava acessivel e todas as
requisicoes registradas terminaram como `completed`. Mesmo assim, saudacoes,
perguntas sobre identidade, capacidades e organizacao foram classificadas como
`consultar_tarefas`, pois o contrato obrigava exatamente uma das ferramentas
operacionais existentes. Com o quadro vazio, todas receberam a mesma resposta.

O frontend textual e o bootstrap de voz tambem estavam no mesmo script modulo e
dependiam de um import de voz no topo. Isso ampliava a falha: erro de carregamento
ou inicializacao da voz podia impedir o registro dos eventos do chat. O cliente nao
tinha timeout, parse defensivo de JSON nem retry com o mesmo `request_id`.

O clique de voz carregou pagina, asset e configuracao, mas nao produziu uma
transcricao. Sem navegador conectado, nao foi possivel observar console ou permissao.
A interface nao tinha medidor de nivel nem mensagens distintas para permissao,
microfone ausente ou dispositivo ocupado.

## Decisao arquitetural

Adicionar `responder_conversa` como uma ferramenta estruturada e validada. Ela
transporta texto natural curto gerado pelo modelo, mas nao executa acao nem consulta.
O Ollama continua sem SQL, shell, arquivos ou ferramentas arbitrarias.

O modelo usa:

- `responder_conversa` para saudacoes, identidade, capacidades, orientacao geral e
  explicacoes do historico;
- `consultar_tarefas` para qualquer pergunta que dependa do quadro;
- ferramentas atuais para preparar, corrigir, confirmar ou cancelar tarefas;
- `fora_do_escopo` para pedidos de operacoes nao implementadas.

Uma pergunta que combina consulta e explicacao ainda chama `consultar_tarefas`; o
backend formata os dados reais e inclui uma orientacao curta. Nesta fase nao havera
um loop aberto de multiplas ferramentas. Uma unica ferramenta validada por turno e
suficiente para consultar ou conversar sem ampliar a superficie de execucao.

## Veracidade e seguranca

`responder_conversa` nao pode alegar que consultou, criou ou alterou registros. O
prompt proibe afirmacoes sobre tarefas por esse caminho, e o backend nunca associa
acao ou `task_id` a essa resposta. Fatos de tarefa so entram em respostas produzidas
apos `board_service.query_tasks`.

Confirmacao, cancelamento, datas, resolucao de entidades, persistencia e
idempotencia permanecem deterministicas. Perguntas e saudacoes nunca autorizam
gravacao. O historico recente continua limitado pela configuracao existente.

## Interface textual

O chat tera bootstrap proprio, independente da voz. Ao enviar:

1. a mensagem aparece imediatamente;
2. o estado de processamento fica visivel;
3. o fetch usa timeout configurado no cliente;
4. HTTP invalido, JSON ausente, resposta vazia e indisponibilidade geram mensagem
   compreensivel;
5. `finally` sempre libera campo e botao;
6. uma falha oferece retry com o mesmo `request_id`, sem duplicar a mensagem nem a
   acao no backend.

Todo conteudo continua renderizado com `textContent`.

## Interface de voz

O bootstrap de voz sera um modulo separado que usa a API publica do controlador de
chat. Se ele falhar, o texto continua funcional. O clique muda imediatamente para
"Solicitando acesso ao microfone". A interface distingue permissao negada,
dispositivo ausente e dispositivo ocupado, permite encerrar enquanto a permissao
esta pendente e mostra nivel de entrada durante `listening`.

Captura permanece suspensa durante TTS. Encerrar incrementa a geracao, libera tracks
e invalida callbacks tardios. Falha de TTS depois de uma resposta salva conserva o
texto e oferece retry somente do audio.

## Validacao

Testes TDD cobrem contrato conversacional, fundamentacao de consultas, contexto,
timeout/retry, independencia entre chat e voz, estados de microfone e medidor. A
avaliacao final usa Ollama real e o banco isolado atual para os 14 casos solicitados.

Sem navegador conectado, clique, permissao e microfone humano permanecem como
validacao manual declarada. A instancia `8011` sera reiniciada sobre o mesmo banco
isolado, preservando a aplicacao antiga da porta `8000`.
