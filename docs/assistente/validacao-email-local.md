# Validação local da leitura de e-mail

Data: 01/10/2026. Ambiente: Mac Apple Silicon M5, Ollama 0.35.0,
`qwen3:4b-instruct-2507-q4_K_M`, banco e documentos isolados em
`/tmp/ad-balancas-conversational.xFP65K`, provedor `synthetic`.

## Causa e correção da alegação sem evidência

`responder_conversa` validava consultas do quadro, mas e-mail não existia no catálogo de capacidades
e verbos como “conferi” não exigiam prova. A validação agora associa alegações a domínio e resultado
de ferramenta da solicitação. Resultado histórico precisa ser identificado como anterior. A mesma
regra bloqueia alegações sem ferramenta sobre financeiro, documentos, serviços, envio e emissão
fiscal.

## Casos automatizados com caixa simulada

- hoje e semana: passou;
- lidas e não lidas sem alterar flags: passou;
- publicidade sem ação sugerida: passou;
- prazo explícito separado de prazo inferido: passou;
- duas empresas Alfa retornadas sem inventar uma identidade: passou;
- conversa respondida e possível resposta pendente: passou;
- Enviados indisponível produz resultado parcial e inconclusivo: passou;
- autenticação e timeout produzem falha, nunca caixa vazia: passou;
- conteúdo malicioso permanece dado e não autoriza ferramenta: passou;
- resultado parcial e desatualizado: passou nos contratos do provedor sintético;
- referência de continuidade e ambiguidade: passou;
- tarefa a partir do segundo e-mail: passou com rascunho, confirmação, vínculo e replay sem duplicar;
- adaptador IMAP: seleção `readonly=True`, `BODY.PEEK`, descoberta por `\\Inbox`/`\\Sent`, sem `STORE`;
- `SELECT`/`SEARCH` malsucedidos viram falha ou resultado parcial, nunca caixa vazia;
- filtros próprios da entrada não são reutilizados ao correlacionar a pasta Enviados;
- MIME simples, multipart e multipart aninhado: seleção da parte textual, decodificação de
  `base64`/`quoted-printable` e descarte de seção não textual/anexo;
- credencial: tipo secreto na configuração e ausência no resultado de teste;
- retenção: detalhes estruturados expiram sem apagar o texto da conversa.
- contexto enviado ao modelo: no máximo três mensagens compactadas e envelope abaixo do limite;
- continuidade histórica: exige referência explícita ao resultado anterior e não contamina uma
  mudança de assunto.

## Ollama real com mensagens sintéticas

Executado pelo backend real, sem respostas simuladas do modelo:

- “Quais e-mails chegaram hoje e qual precisa de atenção primeiro?”: duas inferências, ferramenta
  `consultar_emails`, duas mensagens da caixa sintética, intervalo mostrado e Alfa Indústria
  priorizada por autorização, pedido de resposta e prazo explícito;
- “Tem algum e-mail da empresa Alfa nesta semana?”: duas inferências, dois remetentes parecidos
  preservados, sem escolher um cliente arbitrariamente;
- “Por que o primeiro é importante e quem enviou?”: usa o resultado anterior e, após uma rodada de
  reparo, identifica explicitamente a evidência como histórica;
- pedido de envio e baixa de cobrança: nenhuma ferramenta executada; o modelo declarou ambas as
  capacidades indisponíveis;
- criação a partir do segundo e-mail: rascunho determinístico, confirmação real criou a tarefa
  isolada nº 6 e a confirmação repetida devolveu a mesma tarefa; existe um único vínculo com
  `syn-in-003`.

Tempos totais observados pelo HTTP local: consulta combinada 20,18 s; consulta Alfa 12,14 s;
continuidade aceita 5,71 s; limitação de envio/financeiro 5,04 s; rascunho a partir da referência
0,02 s. São medições do Mac, não estimativas para o Ryzen.

Durante a validação o processo Ollama encerrou uma vez. O backend respondeu indisponibilidade sem
inventar resultado. O serviço foi reiniciado em `127.0.0.1:11434` com `OLLAMA_NO_CLOUD=true`.

Regressão final após a correção de roteamento: 291 testes Python passaram, 4 foram ignorados por
dependerem de condição opcional; 17 testes JavaScript passaram. A validação controlada executou 2
testes com Ollama e mensagens sintéticas, ambos aprovados.

## Não validado

- desempenho e comportamento no Windows/Ryzen continuam pendentes;
- a experiência de voz com os novos resumos de e-mail ainda depende de teste humano no navegador.

## Validação com a conta Yahoo real

Executada em 01/10/2026 pela instância isolada `127.0.0.1:8011`, com banco isolado e
`EMAIL_PROVIDER=imap_yahoo`. Nenhuma credencial, remetente, assunto, corpo, UID ou referência de
mensagem foi registrada neste relatório.

- conexão TLS e autenticação com senha de aplicativo: aprovadas;
- Entrada: descoberta e acessível em modo somente leitura;
- Enviados: descoberta, acessível em modo somente leitura e disponível para correlação;
- consulta de hoje: aprovada, com 7 mensagens na amostra real, sendo 4 lidas e 3 não lidas naquele
  instante;
- consulta da semana: aprovada, com 16 mensagens na primeira amostra, 8 lidas e 8 não lidas;
- consulta exclusiva de não lidos: aprovada;
- respostas possivelmente pendentes: consulta executada com cobertura de Enviados e resultado vazio,
  sem limitação parcial;
- fluxo HTTP completo do assistente: aprovado para hoje, semana, não lidos e pedido explícito de
  possíveis respostas pendentes;
- modo simulado: desativado na instância 8011; a capacidade publicada está disponível e somente
  leitura;
- credenciais: a senha de aplicativo não aparece em arquivos rastreados, histórico do assistente ou
  linha de comando do processo. O endereço da conta já constava em sete PDFs de propostas rastreados
  anteriormente e não foi introduzido pela integração;
- alteração de flags: uma prova controlada buscou uma mensagem não lida e confirmou zero transições
  de não lida para lida. Durante a validação completa chegou uma nova mensagem não lida, elevando os
  totais semanais de 16 para 17 e de 8 para 9 não lidas; isso explica a diferença entre snapshots sem
  indicar mutação pelo assistente.

### Correção do roteamento de linguagem natural

O backend agora resolve localmente intenções de alta confiança antes da primeira inferência. Foram
validadas com caixa sintética as paráfrases sobre algo a resolver no e-mail, alguém esperando retorno,
o que chegou hoje, conteúdo ainda não visto e urgência na caixa de entrada. Pedidos sem escopo, como
“O que chegou?” e “Tem algo urgente?”, não consultam a caixa e permanecem disponíveis para uma
pergunta de esclarecimento; menção explícita ao quadro também não é desviada para e-mail.

Na conta Yahoo real, “Ficou alguém esperando meu retorno?” executou `consultar_emails`, consultou o
intervalo semanal, teve cobertura de Enviados e retornou resultado vazio naquele instante. A auditoria
registrou a ferramenta e o estado `empty`; nenhuma mensagem passou de não lida para lida e não houve
chegada ou remoção durante essa consulta limitada. A redação continua sendo produzida pelo modelo
somente depois do resultado estruturado da ferramenta.

Em 02/10/2026, após o último ajuste e reinício da 8011, “Quais mensagens chegaram hoje?” também executou
`consultar_emails`, retornou estado `success` com duas mensagens dentro do limite visual e preservou
as flags; nenhum conteúdo dessas mensagens foi incluído neste relatório técnico.

### Correção da falsa caixa vazia em consultas de prioridade — 02/10/2026

A Entrada real foi novamente descoberta por `\Inbox`, selecionada com `readonly=True` e consultada
na mesma conta configurada. O `UID SEARCH` retornou quatro candidatos para o critério de calendário
IMAP de hoje e 21 para a semana. Depois da conversão exata para `America/Recife`, dois pertenciam a
hoje e 21 ao intervalo semanal.

A causa da resposta incorreta estava depois do `SEARCH`: consultas como “tem algo que eu precise
resolver?” ativavam `attention_only`; o adaptador limitava a leitura às três mensagens mais recentes
antes de aplicar a classificação e transformava “nenhuma das três passou pelo filtro” em estado
`empty`. A resposta conversacional apresentava esse resultado como se não houvesse mensagens no
período.

Foram aplicadas quatro correções:

- a data recebida passa a usar `INTERNALDATE`, que corresponde à chegada na caixa, e não o cabeçalho
  `Date` controlado pelo remetente;
- os limites locais são convertidos para dias UTC antes de `SINCE`/`BEFORE`, com filtro exato posterior
  em `America/Recife`;
- o total de candidatos é calculado antes do limite visual de três e o filtro de prioridade examina os
  candidatos do intervalo dentro do limite configurado do provedor;
- resultado filtrado vazio informa que havia mensagens no período, sem declarar a caixa vazia; uma
  alegação contrária produz erro de fundamentação.

Validação real, sem registrar remetentes, assuntos, corpos, UIDs ou referências:

- hoje: estado `success`, 2 candidatas e 2 detalhes retornados;
- semana: estado `success`, 21 candidatas e 3 detalhes retornados pelo limite visual;
- prioridade da semana: estado `success`, 21 candidatas e 2 resultados classificados, em 57,47 s;
- flags comparadas antes e depois: 21; flags alteradas: 0;
- pasta Enviados permaneceu descoberta; esta validação não enviou, moveu ou excluiu mensagens.

Depois do reinício da 8011, o fluxo HTTP completo também foi repetido: “hoje” retornou 2 detalhes em
16,80 s; “esta semana” retornou 3 detalhes pelo limite visual em 19,88 s; e a formulação indireta
“algo no meu e-mail que eu precise resolver?” retornou 2 resultados após classificar as 21 candidatas,
em 60,41 s. Nenhuma das três respostas afirmou incorretamente que o período estava vazio.

A consulta de prioridade ficou correta, mas a leitura e classificação das 21 candidatas levou 57,47 s.
Essa latência permanece como limitação conhecida; reduzi-la exige cache incremental ou leitura IMAP em
lote sem enfraquecer a cobertura.

Regressão após a correção: 68 testes de e-mail passaram e 2 testes opcionais foram ignorados; na suíte
completa, 297 testes passaram e 4 foram ignorados.
