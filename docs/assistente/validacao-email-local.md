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

Regressão final após as correções: 278 testes Python passaram, 3 foram ignorados por dependerem de
condição opcional; 17 testes JavaScript passaram. A validação real controlada executou 2 testes com
Ollama e mensagens sintéticas, ambos aprovados.

## Não validado

- nenhuma conta Yahoo real foi acessada;
- autenticação Yahoo, conteúdo real, nomes localizados de pastas e sincronização de Enviados não
  foram validados;
- a não alteração de flags foi verificada no provedor sintético e no protocolo emitido pelo adaptador,
  não observada contra o servidor Yahoo;
- desempenho e comportamento no Windows/Ryzen continuam pendentes;
- a experiência de voz com os novos resumos de e-mail ainda depende de teste humano no navegador.
