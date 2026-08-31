# Modo Word e upload externo de propostas — Design

## Objetivo

Adicionar dois caminhos assistidos para registrar no sistema propostas produzidas ou alteradas fora do formulário estruturado:

1. baixar o DOCX oficial de uma proposta, editá-lo no Word e reenviá-lo como uma nova revisão;
2. enviar uma proposta externa em DOCX ou PDF, revisar cliente e valor sugeridos, confirmar a data e só então criar o registro.

Os documentos serão a fonte oficial nesses dois caminhos. O sistema guardará somente os metadados confiáveis necessários para pesquisa, dashboard e histórico, sem tentar reconstruir itens ou cronogramas que possam ter sido alterados livremente no Word.

## Estado atual confirmado

- A tela de detalhes já disponibiliza `docx_path` e `pdf_path` por `/output/...` e oferece ações de duplicação e revisão.
- A geração estruturada usa `docxtpl` em `document_service.render_docx_from_template()` e converte o resultado com `pdf_service.convert_docx_to_pdf()` via LibreOffice do container.
- O template atual possui `{{VALOR_TOTAL}}`, mas não possui bookmark nem content control persistente. Depois da renderização, o placeholder desaparece; portanto, propostas já geradas não têm um marcador confiável para reextração.
- A importação legada atual aceita apenas PDF, extrai texto com `pdfplumber` e PyMuPDF, tenta reconstruir cliente, itens e cronograma e pode criar cliente automaticamente na confirmação.
- O novo upload externo tem contrato diferente: aceita DOCX/PDF, extrai somente sugestões, exige cliente já cadastrado e nunca persiste antes da confirmação humana. Por isso ele reutilizará a extração de texto PDF, mas não o fluxo de persistência de `POST /api/import-proposals`.
- `Base.metadata.create_all()` cria tabelas ausentes, mas não adiciona colunas em `proposals` já existente. A inclusão de `origem` requer compatibilidade idempotente explícita no startup, inclusive no PostgreSQL do Docker.

## Escopo aprovado

### Origem da proposta

- Adicionar `Proposal.origem`, obrigatório, com os valores permitidos `sistema`, `reupload_editado` e `upload_externo`.
- Usar `sistema` como default Python e default no banco.
- Preencher registros existentes com `sistema` sem apagar ou recriar dados.
- Manter criação, duplicação, revisão estruturada e importação PDF legada com origem `sistema` por default.
- Exibir a origem como badge na listagem e nos detalhes da proposta.
- Manter o dashboard inalterado: toda proposta do mês continua sendo contada e somada, independentemente da origem.

### Modo Word

- Na proposta que possua DOCX, oferecer “Baixar em Word para editar” e “Reenviar Word editado”.
- Na tela de nova proposta, depois de selecionar um cliente, consultar a proposta mais recente desse cliente e oferecer o download se essa proposta possuir DOCX.
- O download sempre corresponde ao arquivo da proposta explicitamente indicada. A tela de nova proposta usa a proposta mais recente pelo mesmo critério atual: `data_geracao DESC, id DESC`.
- Se a proposta mais recente não possuir DOCX, mostrar “A última proposta deste cliente não possui arquivo Word”, sem escolher silenciosamente uma proposta mais antiga.
- Aceitar no reenvio somente `.docx`; `.doc`, `.docm` e outros formatos não serão aceitos.
- Extrair o total por um marcador fixo `AD_VALOR_TOTAL` quando ele existir.
- Sempre mostrar uma prévia com o valor detectado em campo editável.
- Quando o marcador estiver ausente ou inválido, deixar o campo vazio e exigir preenchimento manual, com aviso claro.
- Ao confirmar, criar a próxima revisão do mesmo número, com `origem = "reupload_editado"`.
- Guardar o DOCX reenviado e o PDF convertido como arquivos oficiais da nova revisão.
- Preservar integralmente o registro e os arquivos da revisão de origem.

### Upload externo

- Criar `GET /web/proposals/upload-externo`, separado da importação PDF legada.
- Aceitar um arquivo por operação, nos formatos `.docx` ou `.pdf`.
- Extrair texto de PDF reutilizando `pdf_import_service.extract_text_from_pdf()`.
- Extrair texto de DOCX a partir do pacote OOXML, incluindo documento principal, cabeçalhos, rodapés e tabelas.
- Sugerir um cliente existente por correspondência normalizada e aproximada.
- Sugerir o valor total procurando valores em reais próximos a rótulos de total.
- Exibir cliente, responsável interno, valor total e data da proposta em campos editáveis antes da confirmação.
- Preencher a data inicialmente com a data atual; não tentar extrair datas do texto nesta primeira versão.
- Exigir a seleção de um cliente já cadastrado; o fluxo não criará clientes automaticamente.
- Ao confirmar, criar uma proposta número novo, revisão `00`, com `origem = "upload_externo"`.
- Para DOCX, guardar o documento enviado e o PDF convertido.
- Para PDF, guardar o PDF original e manter `docx_path` vazio.
- Não criar `ProposalItem` nem `ProposalScheduleItem` nesses dois fluxos documentais.

## Fora de escopo

- OCR para PDFs escaneados ou imagens.
- Leitura de `.doc`, `.docm`, arquivos do Google Docs, imagens ou ZIP enviados diretamente.
- Reconstrução automática de itens, cronograma, imposto, condição de pagamento ou demais campos estruturados.
- Edição do DOCX dentro do navegador.
- Sincronização posterior entre itens estruturados e conteúdo do documento.
- Criação automática de cliente com base no arquivo externo.
- Alteração do comportamento de `POST /api/import-proposals` e da tela “Importar PDFs (legado)”.
- Alteração do fluxo estruturado de criação, duplicação ou revisão.
- OCR, antivírus, armazenamento em nuvem, assinatura eletrônica ou aprovação comercial.
- Novo model de anexo, tabela de staging ou histórico de arquivos além das revisões de `Proposal`.
- Conversão PDF→DOCX.

## Decisões de design

### Revisão nova em vez de sobrescrita

O reenvio criará uma nova linha de `Proposal` com o mesmo `numero` e a próxima `revisao`, obtida pelo `numbering_service`. A revisão anterior não será atualizada nem terá seus arquivos substituídos.

Essa decisão resolve a tensão entre “tornar o reenvio oficial” e “preservar histórico”: a revisão recém-criada passa a ser a versão oficial mais recente, enquanto as versões anteriores permanecem consultáveis e baixáveis.

### Documento como fonte oficial

Uma proposta criada por reenvio ou upload externo não terá itens e cronograma estruturados. Copiar itens da proposta de origem seria enganoso, pois o usuário pode tê-los alterado no Word e o sistema não os reextrai.

No reenvio, serão copiados apenas `client_id` e `user_id` da proposta de origem, além do `numero`. Os demais campos não obrigatórios usarão os defaults do model, e `valor_total` será o valor confirmado. No upload externo, cliente, responsável, data e valor virão da confirmação. A tela de detalhes tratará essas origens como “documentais” e não apresentará campos estruturados vazios como se representassem o conteúdo oficial.

### Prévia sem staging persistente

As telas usarão um fluxo em duas chamadas:

1. o navegador envia o arquivo ao endpoint de prévia, que valida e extrai sugestões sem gravar arquivo nem banco;
2. o navegador mantém o mesmo `File` selecionado e o reenvia com os campos confirmados.

O servidor repetirá validação e leitura básica na confirmação e não confiará em dados ocultos da prévia. Esse desenho evita tabela de upload temporário, tokens de staging, expiração e limpeza de arquivos abandonados.

### Marcador do total no Word

O template receberá um content control OOXML com a tag fixa `AD_VALOR_TOTAL` envolvendo visualmente o valor renderizado por `{{VALOR_TOTAL}}`. O content control é preferido a texto livre porque conserva uma identidade própria no documento mesmo depois que o placeholder Jinja é substituído.

O extrator localizará o `w:sdt` cujo `w:tag` seja `AD_VALOR_TOTAL`, concatenará seus nós `w:t` e converterá o valor brasileiro para `Decimal`. O marcador não muda a aparência do documento.

Documentos gerados antes dessa alteração não terão a tag. Eles continuarão aceitos, mas seguirão diretamente para confirmação manual do valor. Não haverá tentativa de adivinhar livremente o total no fluxo de reenvio.

## Arquitetura

### Router

Um novo `app/routers/proposal_files.py` concentrará as rotas web e endpoints de prévia dos dois fluxos documentais. Ele será incluído em `app/main.py` antes de `pages.router`, pois `/web/proposals/upload-externo` precisa ser registrado antes da rota dinâmica `/web/proposals/{proposal_id}`.

Rotas previstas:

- `GET /web/proposals/{proposal_id}/baixar-word`: download por `FileResponse`, com nome de arquivo seguro e `Content-Disposition: attachment`;
- `GET /web/proposals/{proposal_id}/reenviar-word`: formulário de reenvio;
- `POST /api/proposal-files/{proposal_id}/word-preview`: validação e leitura do marcador, sem persistência;
- `POST /web/proposals/{proposal_id}/reenviar-word`: confirmação multipart e criação da nova revisão;
- `GET /web/proposals/upload-externo`: tela de upload externo;
- `POST /api/proposal-files/upload-externo/preview`: extração de sugestões, sem persistência;
- `POST /web/proposals/upload-externo`: confirmação multipart e criação da proposta.

As rotas dinâmicas validarão que a proposta existe. Download e reenvio exigirão `docx_path` preenchido e arquivo presente no diretório de saída.

### Services

Um novo `app/services/proposal_file_service.py` terá responsabilidades isoladas:

- validar tipo, tamanho e estrutura do upload;
- extrair texto de DOCX;
- localizar o marcador `AD_VALOR_TOTAL`;
- sugerir cliente e valor para upload externo;
- criar revisão documental ou proposta externa;
- promover arquivos validados para os caminhos oficiais;
- chamar o conversor LibreOffice existente.

O `pdf_import_service` continuará responsável pela extração de texto PDF já testada. O novo service reutilizará somente `extract_text_from_pdf()`, sem chamar `parse_pdf_text()` nem `to_proposal_payload()`.

Para distinguir um PDF escaneado de um arquivo PDF inválido sem inspecionar mensagens de erro, `pdf_import_service` ganhará uma exceção específica `PDFNoTextError`, derivada de `PDFImportError`. Ela será lançada somente quando os extratores conseguirem abrir o PDF, mas ambos retornarem texto vazio. Erros de abertura ou estrutura continuarão sendo falhas técnicas. O fluxo legado continuará compatível porque já captura a classe-base.

O `storage_service` continuará definindo diretórios e nomes finais. O `pdf_service.convert_docx_to_pdf()` continuará sendo o único mecanismo DOCX→PDF.

### Arquivos novos

- `app/routers/proposal_files.py`;
- `app/services/proposal_file_service.py`;
- `app/templates_web/proposal_word_reupload.html`;
- `app/templates_web/proposal_external_upload.html`;
- `tests/test_proposal_file_service.py`;
- `tests/test_proposal_file_routes.py`.

### Arquivos alterados

- `app/models.py`: campo `Proposal.origem`;
- `app/schemas.py`: exposição e validação de `origem`, além dos contratos de prévia;
- `app/db.py`: compatibilidade idempotente da coluna em bancos existentes;
- `app/main.py`: inclusão do novo router antes das rotas dinâmicas de páginas;
- `app/services/pdf_import_service.py`: erro tipado para PDF válido sem texto extraível;
- `app/templates_web/proposal_detail.html`: ações Word, badge de origem e apresentação documental;
- `app/templates_web/proposal_form.html`: ação contextual para a proposta mais recente do cliente;
- `app/templates_web/proposals.html`: botão para upload externo e badge de origem;
- `doc_templates/proposta_template.docx`: content control invisível `AD_VALOR_TOTAL` em torno do valor total.

A leitura OOXML usará `zipfile` e `xml.etree.ElementTree` da biblioteca padrão; nenhuma dependência nova será adicionada para DOCX.

Não serão alterados `app/services/proposal_service.create_proposal()`, o POST estruturado de `/web/proposals/new`, a importação legada nem o cálculo atual de propostas estruturadas.

## Modelo e compatibilidade de banco

`Proposal.origem` será declarado como:

- `String(30)`;
- `nullable=False`;
- `default="sistema"`;
- `server_default="sistema"`;
- index não necessário nesta primeira versão.

Os services aceitarão somente:

- `sistema` — formulário estruturado, duplicação, revisão estruturada e importação legada atual;
- `reupload_editado` — nova revisão produzida pelo reenvio Word;
- `upload_externo` — proposta criada na nova confirmação de arquivo externo.

Como não há Alembic, `ensure_schema_compatibility()` será ampliado de forma idempotente:

- no SQLite, inspecionar as colunas e executar `ALTER TABLE proposals ADD COLUMN origem VARCHAR(30) NOT NULL DEFAULT 'sistema'` somente quando ausente;
- no PostgreSQL, executar `ALTER TABLE proposals ADD COLUMN IF NOT EXISTS origem VARCHAR(30) NOT NULL DEFAULT 'sistema'`;
- manter o default no banco para proteger inserções antigas;
- nunca apagar, recriar ou truncar `proposals`.

O startup continuará executando `Base.metadata.create_all()` seguido da compatibilidade. Banco novo recebe a coluna pelo metadata; banco existente recebe a adição idempotente.

## Extração e sugestões

### Validação de arquivo

- Tamanho máximo: 20 MB por arquivo.
- Quantidade: um arquivo por operação.
- DOCX: exigir extensão `.docx`, assinatura ZIP válida e pacote OOXML contendo `[Content_Types].xml` e `word/document.xml`.
- PDF: exigir extensão `.pdf` e cabeçalho `%PDF-`.
- Rejeitar DOCX criptografado, entradas com caminho absoluto ou `..`, mais de 500 entradas ou soma descompactada superior a 100 MB.
- Nunca usar o nome enviado pelo navegador como caminho final.
- Não executar macros nem conteúdo incorporado.

Erros retornarão mensagens legíveis sem expor caminhos internos, stack traces ou conteúdo do documento.

O download resolverá o caminho armazenado contra `settings.output_dir`, recusará qualquer resultado fora desse diretório e nunca aceitará um caminho fornecido diretamente pelo usuário.

### Cliente

O texto e os nomes serão normalizados para minúsculas, sem acentos, pontuação duplicada ou espaços extras.

A sugestão seguirá esta ordem:

1. nome normalizado completo do cliente encontrado como trecho do documento;
2. comparação aproximada com linhas relevantes por `difflib.SequenceMatcher` da biblioteca padrão;
3. aceitar sugestão aproximada somente com score mínimo `0,82` e diferença mínima `0,08` para o segundo colocado.

Se não houver vencedor claro, o dropdown ficará sem seleção. Mesmo uma correspondência exata será somente sugestão: o usuário poderá selecionar outro cliente antes de confirmar.

### Valor total do upload externo

O extrator localizará padrões brasileiros `R$ 1.234,56` ou variantes equivalentes em linhas que contenham `valor total`, `total geral`, `total da proposta` ou `investimento total`, priorizando:

1. valor na mesma linha do rótulo;
2. valor na linha imediatamente seguinte;
3. menor distância textual até o rótulo.

Se houver candidatos empatados ou conflitantes sem um vencedor claro, nenhum valor será sugerido. O campo permanecerá editável e obrigatório na confirmação. Valores devem ser convertidos para `Decimal`, ser maiores ou iguais a zero e ter duas casas decimais. Zero é permitido porque o model atual permite propostas sem valor e o usuário pode confirmar explicitamente esse caso.

### PDF escaneado

Se `pdfplumber` e PyMuPDF retornarem texto vazio, a prévia responderá com sucesso assistido, não com falha técnica:

- aviso: “Este PDF parece escaneado. Não foi possível extrair cliente e valor automaticamente.”;
- cliente sem seleção;
- valor vazio;
- data preenchida com hoje;
- confirmação disponível após preenchimento manual.

Não haverá OCR nesta versão.

## Persistência e consistência dos arquivos

Na confirmação, o service repetirá a validação do arquivo e dos campos editáveis. O arquivo será processado primeiro em diretório temporário criado com nome aleatório.

### Reenvio Word

1. obter a próxima revisão com `numbering_service.get_next_revision_for_number()`;
2. criar e `flush()` a nova `Proposal` com mesmo número, próxima revisão, origem `reupload_editado`, cliente e usuário da origem, data atual e valor confirmado;
3. calcular os caminhos oficiais com `storage_service.build_document_paths()`;
4. copiar o DOCX validado para o caminho temporário de destino e converter para PDF com `pdf_service.convert_docx_to_pdf()`;
5. promover os dois arquivos para os nomes finais;
6. gravar `docx_path` e `pdf_path` relativos e fazer commit;
7. em qualquer falha antes do commit, executar rollback e remover somente os novos arquivos desta tentativa.

A conversão PDF é obrigatória para concluir o reenvio. Se o LibreOffice falhar, nenhuma revisão será criada e a revisão anterior continuará oficial.

A constraint única `(numero, revisao)` continuará sendo a proteção final contra duas confirmações concorrentes. Se ocorrer `IntegrityError`, a tentativa será revertida, seus arquivos novos serão removidos e a interface responderá com conflito legível, orientando o usuário a recarregar a proposta; o service não sobrescreverá a revisão criada pela outra requisição.

### Upload externo

- DOCX segue a mesma preparação e exige conversão bem-sucedida antes do commit.
- PDF é validado e promovido como arquivo oficial; `docx_path` permanece vazio.
- A proposta recebe novo número, revisão `00`, origem `upload_externo`, cliente, usuário ativo, data e valor confirmados. O responsável será pré-selecionado pelo mesmo critério da importação atual — primeiro usuário ativo — mas continuará editável.
- Nenhum item ou cronograma é criado.

Os nomes finais seguem o padrão atual por data, cliente, número e revisão. A promoção falhará se o destino final já existir; arquivos de revisões anteriores não serão sobrescritos.

## Interface

As telas reutilizarão `.page-header`, `.card`, `.card-head`, `.form-grid-*`, `.field`, `.btn`, `.badge`, `.warning`, `.actions` e o componente de seleção de arquivo já usado em `import_proposals.html`.

### Detalhe da proposta

- Badge de origem com rótulos “Sistema”, “Word reenviado” ou “Upload externo”.
- Quando houver DOCX: “Baixar em Word para editar” e “Reenviar Word editado”.
- Quando houver PDF: manter “Baixar PDF”.
- Para origem documental, mostrar um resumo com cliente, responsável, data, valor confirmado e arquivos oficiais.
- Não mostrar seções de itens/cronograma vazias como conteúdo extraído.
- Para origem `sistema`, preservar integralmente a interface atual.

### Tela de nova proposta

Ao alterar o cliente, a interface consultará a proposta mais recente pelo endpoint já existente de cliente. Se houver DOCX, exibirá uma área opcional:

- identificação `número/revisão` e data da proposta encontrada;
- botão “Baixar última proposta em Word”;
- link “Reenviar depois de editar”.

Essa área não muda campos, modo ou envio do formulário estruturado.

### Reenvio Word

- identificação da proposta de origem;
- link para baixar novamente o DOCX;
- dropzone de um arquivo `.docx`;
- botão “Analisar arquivo”;
- campo “Valor total confirmado”, preenchido quando o marcador funcionar;
- aviso destacado e campo vazio quando o marcador faltar;
- botão “Criar nova revisão” habilitado somente com arquivo válido e valor válido.

### Upload externo

- acesso pela listagem de propostas, ao lado de “Nova proposta”;
- escolha de um `.docx` ou `.pdf`;
- botão “Analisar arquivo”;
- confirmação com cliente, responsável, valor total e data;
- indicação da confiança do cliente sugerido sem tratar sugestão como confirmação;
- avisos para ausência/ambiguidade de dados e PDF escaneado;
- botão “Confirmar e registrar proposta” habilitado somente quando os campos obrigatórios estiverem válidos.

Se a prévia falhar por rede ou validação, nenhum registro será criado e a tela manterá o arquivo selecionado para correção ou nova tentativa.

## Fluxos

### Baixar e reenviar Word

1. O usuário abre uma proposta ou seleciona um cliente na nova proposta.
2. O sistema identifica a proposta fonte e oferece seu DOCX quando disponível.
3. O usuário baixa e edita o documento localmente.
4. Na tela de reenvio, escolhe o DOCX e solicita análise.
5. O servidor valida o pacote e procura `AD_VALOR_TOTAL`.
6. A tela mostra o valor detectado ou exige valor manual.
7. O usuário confirma.
8. O servidor revalida, converte o DOCX, cria a próxima revisão e redireciona para seus detalhes.

### Upload externo

1. O usuário abre “Upload externo” e seleciona DOCX ou PDF.
2. O navegador solicita a prévia sem persistência.
3. O servidor extrai texto, sugere cliente e valor e devolve avisos.
4. O usuário revisa cliente, responsável, valor e data.
5. O navegador reenvia o arquivo e os campos confirmados.
6. O servidor revalida tudo e salva arquivos e proposta atomicamente.
7. O usuário é redirecionado para a proposta criada.

### Falha de conversão ou persistência

- Nenhum registro parcial deve permanecer.
- A tela exibe mensagem acionável e permite tentar novamente.
- Arquivos temporários e finais criados somente pela tentativa com falha são removidos.
- Revisões anteriores e arquivos já existentes nunca são removidos.

## Testes e verificação

### Model e compatibilidade

- default `sistema` em proposta estruturada;
- aceitação das três origens e rejeição de valores inválidos no service;
- adição idempotente de `origem` em banco SQLite existente;
- adição idempotente de `origem` no PostgreSQL do Docker com dados preservados;
- dashboard contando e somando propostas das três origens.

### Extração Word

- marcador `AD_VALOR_TOTAL` presente e valor brasileiro válido;
- texto do marcador dividido em múltiplos nós `w:t`;
- marcador ausente, vazio, duplicado ou com valor inválido;
- DOCX antigo sem marcador seguindo para confirmação manual;
- rejeição de ZIP inválido, arquivo excessivo, `.docm`, travessia de caminho e pacote OOXML incompleto;
- extração de texto em parágrafos, tabelas, cabeçalhos e rodapés.

### Upload externo

- PDF textual reutilizando o extrator atual;
- PDF escaneado produzindo confirmação manual, sem OCR;
- sugestão por nome exato normalizado;
- sugestão aproximada somente acima do limiar e sem ambiguidade;
- ausência de cliente sugerido quando dois candidatos forem próximos;
- valor na mesma linha e na linha seguinte ao rótulo;
- ausência de sugestão em valores conflitantes;
- cliente, valor e data editáveis prevalecendo na confirmação;
- nenhuma escrita em banco ou output durante a prévia;
- nenhuma criação automática de cliente.

### Revisões e arquivos

- reenvio cria mesmo número e próxima revisão;
- origem anterior e arquivos anteriores permanecem intactos;
- nova revisão recebe origem `reupload_editado`, total confirmado e nenhum item/cronograma;
- upload externo recebe número novo, revisão `00`, origem `upload_externo` e nenhum item/cronograma;
- DOCX gera PDF pelo `pdf_service` existente;
- PDF externo preserva o original e deixa `docx_path` vazio;
- falha do LibreOffice ou do commit executa rollback e limpeza dos arquivos novos;
- confirmação duplicada não sobrescreve revisão existente e retorna erro legível se houver conflito de numeração.

### Rotas e interface

- rotas estáticas não são capturadas por `/web/proposals/{proposal_id}`;
- download retorna somente o DOCX da proposta solicitada como anexo;
- proposta inexistente ou sem DOCX retorna 404/409 legível;
- upload com tipo ou tamanho inválido retorna 400/422 sem persistência;
- preview nunca cria `Proposal`, `Client` ou arquivo oficial;
- campos obrigatórios bloqueiam confirmação incompleta;
- badges de origem aparecem na listagem e nos detalhes;
- propostas estruturadas preservam detalhes, duplicação e revisão atuais;
- telas funcionam em desktop e mobile com o design system existente.

### Verificação final

- Executar a suíte completa localmente e no container Docker.
- Testar a compatibilidade contra um banco PostgreSQL já populado antes da coluna `origem`.
- Gerar uma proposta estruturada nova e confirmar que o template mantém `AD_VALOR_TOTAL` depois do `docxtpl` e da abertura/salvamento no Word ou LibreOffice.
- Reenviar um DOCX com marcador e outro documento antigo sem marcador.
- Enviar PDF textual, PDF escaneado e DOCX externo.
- Confirmar que cada prévia deixa banco e diretório `output` inalterados.
- Confirmar que criação, duplicação, revisão estruturada, importação PDF legada, dashboard e conversão atual continuam sem regressão.
- Inspecionar as telas novas em desktop e mobile, incluindo mensagens de erro e estados sem sugestão.
