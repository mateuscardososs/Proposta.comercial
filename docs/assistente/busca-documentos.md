# Busca documental no Assistente

## O que existia

O fluxo de importação de proposta externa aceita PDF e DOCX. O `proposal_file_service` valida os arquivos,
extrai texto para sugerir dados da proposta e persiste os documentos em `OUTPUT_DIR`; os caminhos relativos
ficam associados aos registros `Proposal.docx_path` e `Proposal.pdf_path`. Chamados concluídos também podem
ter documentos DOCX/PDF em `ServiceTechnicalReport.docx_path` e `ServiceTechnicalReport.pdf_path`. O
importador legado de PDF extrai campos e cria uma proposta, mas não conserva o PDF de entrada. Arquivos
antigos não armazenados nem referenciados por um registro não são reconstruídos nem pesquisados.

## Busca adicionada

Perguntas sobre conteúdo documental são roteadas pelo backend antes do provedor de linguagem. A busca
consulta somente caminhos registrados em propostas e relatórios técnicos, resolve o caminho sob
`OUTPUT_DIR`, rejeita caminhos externos, arquivos ausentes e arquivos acima do limite do importador e
reaproveita os extratores já usados pelo fluxo de importação.

O texto extraído fica em um índice persistente, com um registro por arquivo e entradas por página de PDF ou
seção/parágrafo de DOCX. A chave de origem (`proposal`/`service_report`, id do registro e `pdf`/`docx`) é
única. O hash SHA-256 identifica conteúdo, e caminho, tamanho e mtime evitam reprocessamento em consultas
repetidas. Alterações detectadas substituem as entradas antigas; arquivos ausentes ficam marcados como
indisponíveis, com o texto anterior removido; registros-fonte que deixaram de existir são reconciliados. O
comando de reindexação também oferece `--force` para reprocessamento explícito. O índice guarda cópias de
texto extraído no PostgreSQL enquanto o arquivo continuar registrado; apagar/desvincular o arquivo ou o
registro remove sua projeção na próxima reconciliação. O backup do banco inclui esse texto.

- PDFs digitais são pesquisados por página e a resposta cita o nome do arquivo e a página.
- Para páginas sem camada de texto, usa-se Apple Vision/VisionKit local via PDFKit, com idioma `pt-BR` e
  sem transmitir o PDF ou o OCR ao Gemini, Ollama ou qualquer serviço externo. A instalação do macOS já
  disponibiliza a estrutura Vision; a execução usa `swift` e `scripts/ocr_pdf_vision.swift`. Se Swift/Vision
  não estiver disponível, falhar ou não reconhecer texto, o documento/página não é considerado pesquisável;
  a resposta informa a consulta parcial em vez de alegar ausência de evidência.
- No Windows, páginas sem camada de texto são rasterizadas localmente com pypdfium2/PDFium opcional e reconhecidas
  pelo executável Tesseract no idioma `por`. O processo recebe argumentos como lista (`shell=False`); as
  imagens temporárias ficam numa pasta temporária e são removidas também após falhas. Há limites de 500
  páginas, 200 DPI e 90 segundos totais por PDF. A aplicação não baixa nem instala componentes em execução.
  Sem Tesseract, o idioma `por` ou pypdfium2/PDFium, o arquivo fica não pesquisável/parcial e a consulta informa a
  causa detectada.
- DOCX são pesquisados por seção de título quando o estilo existe; na ausência de título, a resposta cita
  o número do parágrafo.
- A resposta traz trechos encontrados, sem pedir ao Gemini/Ollama para interpretar o documento. Assim,
  conteúdo incorporado no arquivo não pode se tornar instrução, ferramenta ou autorização para o Assistente.
- Quando não há trecho correspondente, a resposta diz que não encontrou evidência suficiente. Arquivos
  inacessíveis ou sem texto extraível tornam explícita a limitação; a busca não afirma ausência total.
- Texto e transcrição de voz usam o mesmo caminho. O trecho curto e a referência também seguem para o TTS.
- A leitura é somente leitura: não cria proposta, tarefa, serviço, lançamento ou evento de agenda.

## Limites

A recuperação é lexical e extrativa, não uma interpretação semântica ampla. OCR depende dos componentes
locais da plataforma: Apple Vision/Swift no macOS e Tesseract, `por` e pypdfium2/PDFium no Windows. Em sistemas sem
adaptador local, PDFs escaneados não são marcados como pesquisáveis. A busca cobre somente arquivos registrados no sistema, não
pastas arbitrárias nem anexos de e-mail. O importador legado `/api/import-proposals` não mantém o PDF
original; documentos ausentes não podem ser reconstruídos.

### Migração e reindexação

O esquema PostgreSQL é aditivo e está em `scripts/migrations/20261007_document_text_index_postgresql.sql`;
o rollback correspondente remove somente as duas tabelas do índice. Depois de backup e validação em um
PostgreSQL temporário, aplique a migração antes de iniciar uma versão que usa o índice. Para indexar apenas
arquivos atualmente referenciados, execute `python -m scripts.reindex_registered_documents`; para forçar
uma reextração idempotente, acrescente `--force`. O comando imprime apenas totais, nunca nomes ou conteúdo.
As consultas também reconciliam alterações detectadas nos caminhos registrados antes de responder.

### Ativar OCR no Windows

1. Instale o Tesseract OCR para Windows seguindo as [instruções oficiais](https://tesseract-ocr.github.io/tessdoc/Installation.html)
   e inclua os dados de idioma português (`por.traineddata`). Se o instalador não os incluir, use o repositório
   oficial de [dados treinados do Tesseract](https://github.com/tesseract-ocr/tessdata) e coloque `por.traineddata`
   na pasta `tessdata` da instalação. A aplicação apenas verifica esses dados; não os baixa.
2. No ambiente virtual do projeto, instale explicitamente o renderizador opcional:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements-ocr-windows.txt
   ```

3. Se os caminhos não estiverem no `PATH`/padrão, preencha no arquivo de ambiente local, ignorado pelo Git:

   ```dotenv
   TESSERACT_CMD="C:/Program Files/Tesseract-OCR/tesseract.exe"
   TESSERACT_DATA_DIR="C:/Program Files/Tesseract-OCR/tessdata"
   ```

   Os campos são opcionais se o executável e os dados forem encontrados pelo ambiente. Reinicie a aplicação
   após a configuração e deixe a reindexação normal processar os arquivos registrados. O conteúdo do PDF e
   os diagnósticos do processo não são gravados em logs.

O extra de renderização é pypdfium2, sob Apache-2.0/BSD-3-Clause, com PDFium sob licença BSD-style; consulte
os avisos da distribuição se futuramente empacotar ou distribuir o aplicativo. No macOS, `local_ocr_for_platform`
continua selecionando o adaptador Vision existente; Tesseract e pypdfium2 não são necessários nem chamados.
O repositório não possui workflow de CI Windows no momento.

## Validação

`tests/test_assistant_document_search.py` e `tests/test_document_index_service.py` usam somente arquivos
sintéticos em diretórios temporários. Cobrem PDF digital, PDF escaneado com OCR local em português, DOCX,
relatório técnico, página/seção, reindexação sem duplicação, substituição, arquivo removido, OCR ausente,
informação não encontrada, caminho fora de `OUTPUT_DIR`, conteúdo instrucional malicioso e fluxo de voz.
Os testes Windows simulam seleção de plataforma, saída do Tesseract, executável e idioma ausentes, falha de
conversão, limpeza da pasta temporária e citação de página. Não equivalem a execução numa máquina Windows
real. Nenhum documento real ou conteúdo de e-mail é usado.

### Validação na instância local 8013 — 2026-10-07

- A migração foi aplicada duas vezes e revertida em um PostgreSQL temporário isolado; ambas as aplicações
  foram idempotentes. A reversão removeu somente as tabelas temporárias do índice.
- Antes da alteração de `propostas_db`, foi criado um backup custom-format fora do repositório e validado
  pelo `pg_restore --list`. A migração aditiva foi então aplicada ao banco principal.
- O backfill consultou apenas caminhos registrados em `proposals` e `service_technical_reports`: nesta
  base não havia nenhum caminho de PDF/DOCX registrado (0 arquivos), então nenhum documento operacional
  foi copiado nem se tornou pesquisável. Arquivos sem referência registrada continuam fora do escopo.
- O OCR Apple Vision executou em teste automatizado com PDF escaneado sintético em português, com evidência
  recuperada na página correta. Nenhum documento real foi usado nos testes.
- O processo da aplicação foi reiniciado somente na porta 8013, em `127.0.0.1` (PID verificado no momento
  da validação). Health check, Hoje, Assistente, Serviços, Propostas, Mensagens e páginas financeiras
  responderam HTTP 200. O provedor configurado continuou Gemini.
- A interface não foi exercitada visualmente em navegador; as verificações de 8013 foram HTTP/health check.
  A busca na conversa e o conteúdo citado foram cobertos por testes automatizados sintéticos.
- Nenhuma sincronização manual de e-mails foi solicitada. A inicialização manteve o worker periódico
  configurado pela aplicação; ele segue o comportamento automático já existente.
