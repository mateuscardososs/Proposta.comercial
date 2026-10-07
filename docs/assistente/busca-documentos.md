# Busca documental no Assistente

## O que existia

O fluxo de importação de proposta externa aceita PDF e DOCX. O `proposal_file_service` valida os arquivos,
extrai texto para sugerir dados da proposta e persiste os documentos em `OUTPUT_DIR`; os caminhos relativos
ficam associados aos registros `Proposal.docx_path` e `Proposal.pdf_path`. O importador legado de PDF extrai
campos e cria uma proposta, mas não conserva o PDF de entrada como documento pesquisável. A conversa do
Assistente não tinha uma capacidade de busca desses arquivos.

## Busca adicionada

Perguntas sobre conteúdo de propostas, PDFs, DOCX e documentos vinculados a propostas são roteadas pelo
backend antes do provedor de linguagem. A busca consulta os registros de propostas que apontam para um
arquivo, resolve o caminho sob `OUTPUT_DIR`, rejeita caminhos externos, arquivos ausentes e arquivos acima
do limite do importador e chama os extratores já usados pelo fluxo de importação.

- PDFs são pesquisados por página e a resposta cita o nome do arquivo e a página.
- DOCX são pesquisados por seção de título quando o estilo existe; na ausência de título, a resposta cita
  o número do parágrafo.
- A resposta traz trechos encontrados, sem pedir ao Gemini/Ollama para interpretar o documento. Assim,
  conteúdo incorporado no arquivo não pode se tornar instrução, ferramenta ou autorização para o Assistente.
- Quando não há trecho correspondente, a resposta diz que não encontrou evidência suficiente. Arquivos
  inacessíveis ou sem texto extraível tornam explícita a limitação; a busca não afirma ausência total.
- Texto e transcrição de voz usam o mesmo caminho. O trecho curto e a referência também seguem para o TTS.
- A leitura é somente leitura: não cria proposta, tarefa, serviço, lançamento ou evento de agenda.

## Limites

A primeira versão faz recuperação lexical e extrativa, não uma interpretação semântica ampla. A busca cobre
somente arquivos vinculados por caminhos persistidos em propostas, não pastas arbitrárias. Um PDF escaneado
sem camada de texto pode não ser pesquisável. O importador legado `/api/import-proposals` não mantém o PDF
original; para pesquisar esse conteúdo, ele precisa estar associado a uma proposta pelo fluxo documental
atual. Não há índice persistente: os arquivos são extraídos durante a consulta.

## Validação

`tests/test_assistant_document_search.py` usa PDF e DOCX sintéticos no diretório temporário de testes. Cobre
evidência com página/seção, informação ausente, conteúdo instrucional malicioso tratado como dado, isolamento
de caminho fora de `OUTPUT_DIR` e o mesmo comportamento quando a entrada vem do fluxo de voz. Nenhuma
consulta ou conteúdo de e-mail é usado.
