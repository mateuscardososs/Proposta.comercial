# Modo Word e upload externo de propostas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registrar propostas editadas em Word e propostas externas em DOCX/PDF como revisões ou propostas documentais oficiais, sempre com prévia e confirmação humana.

**Architecture:** Um router `proposal_files.py` expõe downloads, prévias e confirmações; um service isolado valida arquivos, extrai sugestões e persiste documentos de forma atômica. `Proposal.origem` diferencia os fluxos, o template recebe o marcador OOXML `AD_VALOR_TOTAL`, e a conversão continua centralizada no `pdf_service` existente.

**Tech Stack:** Python 3.12, FastAPI 0.116.1, SQLAlchemy 2.0.44, PostgreSQL 16, SQLite nos testes, Jinja2 3.1.6, docxtpl 0.20.1, pdfplumber 0.11.7, fallback PyMuPDF já previsto no código quando disponível, LibreOffice headless, pytest 8.4.2 e HTTPX 0.28.1.

## Global Constraints

- Implementar exatamente a spec `docs/superpowers/specs/2026-08-31-modo-word-upload-externo-design.md`.
- Não alterar o comportamento da criação, duplicação, revisão estruturada ou importação PDF legada.
- Não criar cliente automaticamente nos fluxos novos.
- Não persistir banco ou arquivo oficial durante a prévia.
- Aceitar um arquivo por operação, com máximo de 20 MB.
- Aceitar somente `.docx` no reenvio e somente `.docx`/`.pdf` no upload externo.
- Rejeitar DOCX com macro, criptografia, path traversal, mais de 500 entradas ou mais de 100 MB descompactados.
- Não implementar OCR; PDF válido sem texto segue para confirmação manual.
- Propostas documentais não terão `ProposalItem` nem `ProposalScheduleItem`.
- Reenvio cria nova revisão e nunca sobrescreve revisão ou arquivo anterior.
- Conversão DOCX→PDF usa somente `pdf_service.convert_docx_to_pdf()`.
- Usar `Base.metadata.create_all()` e compatibilidade idempotente no startup; não introduzir Alembic.
- Reutilizar o design system de `base.html` e o dropzone de `import_proposals.html`.
- Não adicionar dependência para leitura DOCX; usar `zipfile` e `xml.etree.ElementTree`.
- Não criar commit, merge ou push sem autorização explícita do usuário. Os checkpoints abaixo verificam o diff, mas deixam tudo sem commit.

## Preflight de execução

- [ ] Registrar o estado inicial sem alterar o checkout:

```bash
git status --short
git branch --show-current
git log -3 --oneline
python3 -m pytest -q
```

Expected: branch `main`; somente a spec e este plano podem estar não rastreados; suíte atual verde antes da primeira alteração.

---

### Task 1: Campo `Proposal.origem` e compatibilidade de banco

**Files:**
- Modify: `app/models.py`
- Modify: `app/schemas.py`
- Modify: `app/db.py`
- Create: `tests/test_proposal_origin.py`

**Interfaces:**
- Consumes: `Base`, `engine`, `Proposal`, `ProposalRead` e `ProposalSummary` existentes.
- Produces: `Proposal.origem: str`, `ProposalOrigin = Literal["sistema", "reupload_editado", "upload_externo"]` e `ensure_schema_compatibility()` compatível com SQLite e PostgreSQL.

- [ ] **Step 1: Escrever os testes vermelhos do default e dos schemas**

Criar `tests/test_proposal_origin.py` com uma proposta mínima e as asserções:

```python
def test_proposal_origin_defaults_to_sistema(db):
    proposal = make_minimal_proposal(db)
    db.refresh(proposal)
    assert proposal.origem == "sistema"


def test_proposal_read_exposes_origin(db):
    proposal = make_minimal_proposal(db)
    payload = ProposalRead.model_validate(proposal)
    assert payload.origem == "sistema"


def test_proposal_schema_rejects_unknown_origin(db):
    proposal = make_minimal_proposal(db)
    proposal.origem = "desconhecida"
    with pytest.raises(ValidationError):
        ProposalRead.model_validate(proposal)
```

O helper deve criar `Client`, `User` e `Proposal` diretamente, sem gerar documentos.

- [ ] **Step 2: Executar e confirmar a falha pelo campo ausente**

```bash
python3 -m pytest tests/test_proposal_origin.py -q
```

Expected: FAIL porque `Proposal` e os schemas ainda não possuem `origem`.

- [ ] **Step 3: Adicionar o campo e o tipo literal**

Em `app/models.py`, adicionar junto a `data_geracao`:

```python
origem: Mapped[str] = mapped_column(
    String(30),
    default="sistema",
    server_default="sistema",
    nullable=False,
)
```

Em `app/schemas.py`:

```python
ProposalOrigin = Literal["sistema", "reupload_editado", "upload_externo"]
```

Adicionar `origem: ProposalOrigin` a `ProposalRead` e `ProposalSummary`. Não adicionar `origem` a `ProposalCreate`; o fluxo estruturado não deve aceitar origem fornecida pelo formulário ou API.

- [ ] **Step 4: Escrever o teste de upgrade SQLite idempotente**

Usar um arquivo SQLite temporário com uma tabela antiga `proposals` sem `origem`, executar uma helper nova duas vezes e afirmar:

```python
columns = {column["name"] for column in inspect(legacy_engine).get_columns("proposals")}
assert "origem" in columns
assert connection.execute(text("SELECT origem FROM proposals WHERE id = 1")).scalar_one() == "sistema"
```

A segunda execução não pode lançar erro nem alterar o registro.

- [ ] **Step 5: Generalizar a compatibilidade sem remover as colunas legadas atuais**

Extrair uma função testável e manter `ensure_schema_compatibility()` como wrapper do engine global:

```python
def ensure_schema_compatibility_for_engine(target_engine: Engine) -> None:
    inspector = inspect(target_engine)
    if "proposals" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("proposals")}
    with target_engine.begin() as conn:
        if "origem" not in columns:
            conn.execute(text(
                "ALTER TABLE proposals "
                "ADD COLUMN origem VARCHAR(30) NOT NULL DEFAULT 'sistema'"
            ))


def ensure_schema_compatibility() -> None:
    ensure_schema_compatibility_for_engine(engine)
```

Preservar na mesma função as adições SQLite já existentes de `condicao_pagamento_dias` e `imposto_percentual`. Para PostgreSQL, a inspeção anterior ao `ALTER` torna a operação idempotente sem depender de SQL específico; não retornar antecipadamente para bancos que não sejam SQLite.

- [ ] **Step 6: Rodar testes focados e regressão dos models**

Antes do comando, adicionar um teste que crie três propostas do mês — uma por origem — com valores `100.00`, `200.00` e `300.00`, e afirmar:

```python
summary = dashboard_service.get_dashboard_summary(db, reference_date=proposal_date)
assert summary.propostas_mes_quantidade == 3
assert summary.propostas_mes_valor == Decimal("600.00")
```

```bash
python3 -m pytest tests/test_proposal_origin.py tests/test_dashboard_service.py tests/test_dashboard_routes.py -q
```

Expected: PASS; o dashboard continua contando propostas sem filtrar origem.

- [ ] **Checkpoint 1: revisar sem commit**

```bash
git diff --check
git status --short
git diff -- app/models.py app/schemas.py app/db.py tests/test_proposal_origin.py
```

Não executar `git add` nem `git commit`.

---

### Task 2: Validação segura de upload e leitura OOXML

**Files:**
- Create: `app/services/proposal_file_service.py`
- Create: `tests/test_proposal_file_service.py`

**Interfaces:**
- Consumes: nome original e bytes já limitados pelo router.
- Produces:
  - `MAX_UPLOAD_BYTES = 20 * 1024 * 1024`;
  - `DOCX_MAX_ENTRIES = 500`;
  - `DOCX_MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024`;
  - `DOCX_TOTAL_TAG = "AD_VALOR_TOTAL"`;
  - `ProposalFileValidationError(ValueError)`;
  - `ValidatedUpload(filename: str, suffix: Literal[".docx", ".pdf"], payload: bytes)`;
  - `WordAnalysis(filename: str, valor_total: Decimal | None, marker_found: bool, warnings: tuple[str, ...])`;
  - `validate_upload(filename: str, payload: bytes, allowed_suffixes: frozenset[str]) -> ValidatedUpload`;
  - `extract_docx_text(payload: bytes) -> str`;
  - `analyze_word_reupload(filename: str, payload: bytes) -> WordAnalysis`.

- [ ] **Step 1: Criar helpers de DOCX sintético nos testes**

Em `tests/test_proposal_file_service.py`, criar `build_docx()` usando `io.BytesIO` e `zipfile.ZipFile`, com `[Content_Types].xml`, `word/document.xml`, cabeçalho e rodapé opcionais. O XML do marcador deve usar:

```xml
<w:sdt>
  <w:sdtPr><w:tag w:val="AD_VALOR_TOTAL"/></w:sdtPr>
  <w:sdtContent><w:r><w:t>R$ 1.234,56</w:t></w:r></w:sdtContent>
</w:sdt>
```

- [ ] **Step 2: Escrever a matriz vermelha de validação**

Parametrizar testes que rejeitem:

```python
cases = [
    ("arquivo.doc", b"conteudo", {".docx"}),
    ("arquivo.docm", valid_docx, {".docx"}),
    ("arquivo.docx", b"nao-e-zip", {".docx"}),
    ("arquivo.pdf", b"nao-e-pdf", {".pdf"}),
    ("arquivo.docx", oversized_payload, {".docx"}),
]
```

Adicionar casos DOCX para entrada `../escape.xml`, flag criptografada, `word/vbaProject.bin`, 501 entradas, soma descompactada acima de 100 MB e ausência de `word/document.xml`. Todos devem levantar `ProposalFileValidationError`.

- [ ] **Step 3: Confirmar a falha inicial**

```bash
python3 -m pytest tests/test_proposal_file_service.py -q
```

Expected: erro de importação porque `proposal_file_service.py` ainda não existe.

- [ ] **Step 4: Implementar validação de tamanho, extensão e assinatura**

Criar as dataclasses frozen e implementar:

```python
def validate_upload(
    filename: str,
    payload: bytes,
    allowed_suffixes: frozenset[str],
) -> ValidatedUpload:
    safe_filename = Path(filename or "").name
    suffix = Path(safe_filename).suffix.lower()
    if suffix not in allowed_suffixes:
        raise ProposalFileValidationError("Formato de arquivo não permitido.")
    if not payload:
        raise ProposalFileValidationError("O arquivo está vazio.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ProposalFileValidationError("O arquivo excede o limite de 20 MB.")
    if suffix == ".pdf" and not payload.startswith(b"%PDF-"):
        raise ProposalFileValidationError("O arquivo enviado não é um PDF válido.")
    if suffix == ".docx":
        _validate_docx_package(payload)
    return ValidatedUpload(safe_filename, suffix, payload)
```

`_validate_docx_package()` deve abrir o ZIP em memória, rejeitar `flag_bits & 0x1`, caminhos absolutos/`..`, macros, limites e entradas obrigatórias. Não extrair o ZIP para o filesystem.

- [ ] **Step 5: Escrever e implementar extração de texto OOXML**

O teste deve provar a ordem documento→headers→footers e concatenação de textos em tabela:

```python
text = extract_docx_text(docx_payload)
assert "Cliente Exemplo Ltda" in text
assert "Serviço em tabela" in text
assert "Cabeçalho comercial" in text
assert "Rodapé comercial" in text
```

Implementar leitura somente de `word/document.xml`, `word/header*.xml` e `word/footer*.xml`, ordenados por nome, usando namespace:

```python
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": WORD_NS}

def _xml_text(xml_bytes: bytes) -> str:
    root = ElementTree.fromstring(xml_bytes)
    return "\n".join(
        text.strip()
        for node in root.findall(".//w:t", NS)
        if (text := (node.text or "").strip())
    )
```

- [ ] **Step 6: Escrever e implementar análise do marcador**

Cobrir marcador válido dividido entre vários `w:t`, ausente, vazio, duplicado e inválido. Contrato esperado:

```python
analysis = analyze_word_reupload("editado.docx", marked_docx)
assert analysis.valor_total == Decimal("1234.56")
assert analysis.marker_found is True
assert analysis.warnings == ()

manual = analyze_word_reupload("antigo.docx", unmarked_docx)
assert manual.valor_total is None
assert manual.marker_found is False
assert "Informe o valor total manualmente." in manual.warnings[0]
```

Localizar exatamente um `w:sdt` com `w:sdtPr/w:tag[@w:val='AD_VALOR_TOTAL']`. Zero ou mais de um marcador retorna confirmação manual; nunca escolher silenciosamente o primeiro duplicado. Reutilizar `decimal_from_str` e quantizar para duas casas.

- [ ] **Step 7: Rodar os testes do service**

```bash
python3 -m pytest tests/test_proposal_file_service.py -q
```

Expected: todos os casos de validação, texto e marcador passam.

- [ ] **Checkpoint 2: revisar sem commit**

```bash
git diff --check
git status --short
git diff -- app/services/proposal_file_service.py tests/test_proposal_file_service.py
```

---

### Task 3: Prévia do upload externo, PDF escaneado e sugestões

**Files:**
- Modify: `app/services/pdf_import_service.py`
- Modify: `app/services/proposal_file_service.py`
- Modify: `tests/test_proposal_file_service.py`
- Create: `tests/test_pdf_no_text.py`

**Interfaces:**
- Consumes: `ValidatedUpload`, sessão SQLAlchemy e clientes existentes.
- Produces:
  - `PDFNoTextError(PDFImportError)`;
  - `ClientSuggestion(client_id: int, client_name: str, confidence: float)`;
  - `ExternalAnalysis(filename: str, file_type: Literal["docx", "pdf"], suggested_client: ClientSuggestion | None, suggested_valor_total: Decimal | None, warnings: tuple[str, ...])`;
  - `suggest_client(text: str, clients: Sequence[Client]) -> ClientSuggestion | None`;
  - `suggest_total(text: str) -> Decimal | None`;
  - `analyze_external_upload(db: Session, filename: str, payload: bytes) -> ExternalAnalysis`.

- [ ] **Step 1: Escrever o teste vermelho da distinção PDF sem texto**

Monkeypatchar os dois extratores internos:

```python
def test_valid_pdf_without_text_raises_typed_error(monkeypatch):
    monkeypatch.setattr(pdf_import_service, "_extract_text_pdfplumber", lambda _: "")
    monkeypatch.setattr(pdf_import_service, "_extract_text_pymupdf", lambda _: "")
    with pytest.raises(pdf_import_service.PDFNoTextError):
        pdf_import_service.extract_text_from_pdf(b"%PDF-valid")
```

Adicionar outro teste em que ambos levantam exceção e confirmar `PDFImportError`, mas não `PDFNoTextError`.

- [ ] **Step 2: Implementar o erro tipado preservando o legado**

Adicionar:

```python
class PDFNoTextError(PDFImportError):
    pass
```

Em `extract_text_from_pdf`, rastrear se algum extrator abriu o documento e retornou vazio. Se nenhum retornar texto e ao menos um retornar vazio, levantar `PDFNoTextError("PDF sem texto extraível.")`; se ambos falharem ao abrir/processar, manter `PDFImportError` com os erros técnicos. `parse_pdf_bytes_safe()` continua capturando a classe-base.

- [ ] **Step 3: Escrever testes vermelhos da sugestão de cliente**

Criar clientes `Companhia Siderúrgica Nacional`, `Metalúrgica Horizonte Ltda` e `Metalúrgica Horizonte Serviços Ltda`. Cobrir:

```python
assert suggest_client("CLIENTE: Companhia Siderurgica Nacional", clients).client_id == csn.id
assert suggest_client("Metalurgica Horizonte", ambiguous_clients) is None
assert suggest_client("apelido sem relação", clients) is None
```

Adicionar caso aproximado acima de `0.82` e com margem maior que `0.08`, afirmando `confidence` arredondado entre `0.82` e `1.0`.

- [ ] **Step 4: Implementar normalização e ranking conservador**

Normalizar com `unicodedata.normalize("NFKD")`, remover acentos/pontuação e compactar espaços. Primeiro procurar o nome completo normalizado como substring. Depois comparar cada nome com cada linha não vazia por `SequenceMatcher(None, client_name, line).ratio()`. Aceitar somente se:

```python
best_score >= 0.82 and (second_score is None or best_score - second_score >= 0.08)
```

Empate ou margem insuficiente retorna `None`.

- [ ] **Step 5: Escrever testes vermelhos do valor total**

Cobrir valores na mesma linha, linha seguinte e conflito:

```python
assert suggest_total("Valor total: R$ 1.234,56") == Decimal("1234.56")
assert suggest_total("TOTAL DA PROPOSTA\nR$ 9.876,00") == Decimal("9876.00")
assert suggest_total("Subtotal R$ 100,00\nValor total: R$ 250,00") == Decimal("250.00")
assert suggest_total("Valor total R$ 100,00 e R$ 200,00") is None
assert suggest_total("Preço R$ 100,00") is None
```

- [ ] **Step 6: Implementar ranking do valor e a análise externa**

Buscar `R$` apenas na mesma linha ou linha seguinte a `valor total`, `total geral`, `total da proposta` ou `investimento total`. Priorizar mesma linha e menor distância; se dois candidatos tiverem a mesma prioridade e valores diferentes, retornar `None`.

Implementar:

```python
def analyze_external_upload(
    db: Session,
    filename: str,
    payload: bytes,
) -> ExternalAnalysis:
    upload = validate_upload(filename, payload, frozenset({".docx", ".pdf"}))
    warnings: list[str] = []
    if upload.suffix == ".docx":
        text = extract_docx_text(upload.payload)
    else:
        try:
            text = pdf_import_service.extract_text_from_pdf(upload.payload)
        except pdf_import_service.PDFNoTextError:
            text = ""
            warnings.append(
                "Este PDF parece escaneado. Não foi possível extrair cliente "
                "e valor automaticamente."
            )
    clients = db.query(Client).order_by(Client.id.asc()).all()
    return ExternalAnalysis(
        filename=upload.filename,
        file_type=upload.suffix.removeprefix("."),
        suggested_client=suggest_client(text, clients),
        suggested_valor_total=suggest_total(text),
        warnings=tuple(warnings),
    )
```

- [ ] **Step 7: Rodar testes focados e regressão da importação legada**

```bash
python3 -m pytest tests/test_pdf_no_text.py tests/test_proposal_file_service.py -q
```

`tests/test_pdf_no_text.py` também deve chamar `parse_pdf_bytes_safe()` com PDF sem texto e afirmar que o contrato legado continua retornando `(None, mensagem)`, sem deixar a nova subclasse escapar. Expected: novos testes verdes e contrato legado preservado.

- [ ] **Checkpoint 3: revisar sem commit**

```bash
git diff --check
git status --short
git diff -- app/services/pdf_import_service.py app/services/proposal_file_service.py tests
```

---

### Task 4: Persistência atômica de revisões e propostas documentais

**Files:**
- Modify: `app/services/proposal_file_service.py`
- Modify: `tests/test_proposal_file_service.py`

**Interfaces:**
- Consumes: `Settings`, `Session`, fonte opcional, arquivo validado e campos confirmados.
- Produces:
  - `ProposalFileConflictError(ProposalFileValidationError)`;
  - `create_word_revision(db: Session, source_id: int, filename: str, payload: bytes, confirmed_total: Decimal, settings: Settings) -> Proposal`;
  - `create_external_proposal(db: Session, filename: str, payload: bytes, client_id: int, user_id: int, proposal_date: date, confirmed_total: Decimal, settings: Settings) -> Proposal`.

- [ ] **Step 1: Escrever testes vermelhos do reenvio**

Usar `tmp_path` como `settings.output_dir`, criar fonte `numero=42, revisao="00"`, com um item e um cronograma, e monkeypatchar `pdf_service.convert_docx_to_pdf` para gravar um PDF mínimo. Afirmar:

```python
created = create_word_revision(
    db, source.id, "editado.docx", marked_docx,
    Decimal("4500.00"), test_settings,
)
assert (created.numero, created.revisao) == (42, "01")
assert created.origem == "reupload_editado"
assert created.client_id == source.client_id
assert created.user_id == source.user_id
assert created.valor_total == Decimal("4500.00")
assert created.items == []
assert created.schedule_items == []
assert Path(test_settings.output_dir, created.docx_path).read_bytes() == marked_docx
assert Path(test_settings.output_dir, created.pdf_path).read_bytes().startswith(b"%PDF-")
assert source.docx_path == original_source_path
```

Adicionar teste para valor negativo, fonte inexistente, fonte sem DOCX e arquivo não DOCX.

- [ ] **Step 2: Escrever testes vermelhos do upload externo**

Para DOCX, afirmar novo número, revisão `00`, `upload_externo`, data/cliente/user/valor confirmados, arquivos DOCX/PDF e coleções vazias. Para PDF, afirmar conteúdo original preservado e `docx_path == ""`.

Adicionar validações de cliente inexistente, usuário inexistente/inativo e data/valor inválidos.

- [ ] **Step 3: Implementar validação das referências e criação da linha documental**

Adicionar helpers privados:

```python
def _confirmed_total(value: Decimal) -> Decimal:
    total = quantize_2(value)
    if total < 0:
        raise ProposalFileValidationError("O valor total não pode ser negativo.")
    return total


def _new_documental_proposal(
    *, numero: int, revisao: str, proposal_date: date,
    client_id: int, user_id: int, origem: str, valor_total: Decimal,
) -> Proposal:
    return Proposal(
        numero=numero,
        revisao=revisao,
        data_geracao=proposal_date,
        client_id=client_id,
        user_id=user_id,
        origem=origem,
        objeto_tipo="outro",
        objeto_texto="Proposta documental — consulte o arquivo oficial",
        valor_total=valor_total,
    )
```

No upload externo, exigir `Client.id` existente e `User.id` ativo. No reenvio, copiar as FKs da fonte mesmo que o responsável tenha sido desativado posteriormente, preservando autoria histórica.

- [ ] **Step 4: Implementar preparação e promoção exclusiva dos arquivos**

Criar um `TemporaryDirectory` dentro do diretório final do cliente. Para DOCX, gravar o upload temporário e chamar o conversor existente para um PDF temporário. Para PDF, preparar apenas o original.

Promover com escrita exclusiva, sem `os.replace`:

```python
def _copy_exclusive(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("xb") as dst:
        shutil.copyfileobj(src, dst)
        dst.flush()
        os.fsync(dst.fileno())
```

Manter uma lista de destinos promovidos; em exceção, remover somente esses destinos. Nunca calcular alvo a partir do nome original.

- [ ] **Step 5: Implementar as duas transações**

Para reenvio, validar que `source.docx_path` existe no banco e no output, obter revisão com `get_next_revision_for_number()`, `db.add()` e `db.flush()`, preparar/promover arquivos, atribuir paths relativos e `db.commit()`.

Para externo, obter número com `get_next_proposal_number()`, usar revisão `00` e seguir o mesmo pipeline. Capturar `IntegrityError` separadamente:

```python
except IntegrityError as exc:
    db.rollback()
    _remove_created_files(promoted_paths)
    raise ProposalFileConflictError(
        "Outra proposta ou revisão foi criada ao mesmo tempo. Recarregue e tente novamente."
    ) from exc
except Exception:
    db.rollback()
    _remove_created_files(promoted_paths)
    raise
```

Após commit, recarregar por `proposal_service.get_proposal_with_details()` para devolver relações prontas ao router.

- [ ] **Step 6: Testar rollback de conversão, promoção e commit**

Monkeypatchar separadamente:

- conversor levantando `RuntimeError`;
- `_copy_exclusive` falhando no segundo arquivo;
- `db.commit` levantando `IntegrityError`.

Em todos:

```python
assert db.query(Proposal).filter(Proposal.id != source.id).count() == 0
assert list(test_settings.output_dir.rglob("*.*")) == original_files_only
```

- [ ] **Step 7: Rodar os testes do service completo**

```bash
python3 -m pytest tests/test_proposal_file_service.py -q
```

Expected: validação, análise e persistência atômica verdes.

- [ ] **Checkpoint 4: revisar sem commit**

```bash
git diff --check
git status --short
git diff -- app/services/proposal_file_service.py tests/test_proposal_file_service.py
```

---

### Task 5: Schemas, router, download e endpoints multipart

**Files:**
- Modify: `app/schemas.py`
- Create: `app/routers/proposal_files.py`
- Modify: `app/main.py`
- Create: `tests/test_proposal_file_routes.py`

**Interfaces:**
- Consumes: funções públicas do `proposal_file_service` das Tasks 2–4.
- Produces: `WordReuploadPreviewResponse`, `ExternalUploadPreviewResponse` e todas as rotas HTTP documentadas na spec.

- [ ] **Step 1: Definir testes vermelhos dos contratos de prévia**

Testar `POST /api/proposal-files/{id}/word-preview` e `POST /api/proposal-files/upload-externo/preview` com multipart. Afirmar JSON:

```python
assert response.json() == {
    "filename": "editado.docx",
    "valor_total": "1234.56",
    "marker_found": True,
    "warnings": [],
}
```

Para externo, afirmar `file_type`, cliente sugerido, `client_confidence`, valor e avisos. Em ambos, comparar contagem de `Proposal` e snapshot de `output_dir` antes/depois para provar ausência de persistência.

- [ ] **Step 2: Adicionar schemas exatos**

Em `app/schemas.py`:

```python
class WordReuploadPreviewResponse(BaseModel):
    filename: str
    valor_total: Decimal | None
    marker_found: bool
    warnings: list[str] = Field(default_factory=list)


class ExternalUploadPreviewResponse(BaseModel):
    filename: str
    file_type: Literal["docx", "pdf"]
    suggested_client_id: int | None = None
    suggested_client_name: str | None = None
    client_confidence: float | None = None
    suggested_valor_total: Decimal | None = None
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 3: Criar o router e leitura limitada do upload**

Criar helper:

```python
async def _read_upload_limited(upload: UploadFile) -> bytes:
    payload = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ProposalFileValidationError("O arquivo excede o limite de 20 MB.")
    return payload
```

Mapear `ProposalFileValidationError` para 422, proposta/arquivo inexistente para 404, ausência de DOCX na fonte para 409, conflito para 409 e falha inesperada de conversão para formulário com mensagem legível/500 na API. Não devolver caminhos internos.

- [ ] **Step 4: Implementar previews e confirmar que não persistem**

Os endpoints chamam somente `analyze_word_reupload()` ou `analyze_external_upload()` e convertem dataclasses para os schemas. Não usar `db.commit`, `storage_service` nem `pdf_service` nessas rotas.

- [ ] **Step 5: Escrever e implementar o download seguro**

Teste proposta válida, inexistente, sem path, arquivo ausente e path `../../fora.docx`. Implementar:

```python
def _resolve_output_file(relative_path: str, output_root: Path) -> Path:
    root = output_root.resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(status_code=404, detail="Arquivo Word não encontrado.")
    if candidate.suffix.lower() != ".docx" or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Arquivo Word não encontrado.")
    return candidate
```

Retornar `FileResponse(candidate, filename=candidate.name, media_type=...)` como attachment.

- [ ] **Step 6: Escrever e implementar confirmações multipart**

Testar reenvio e externo com services reais e conversor monkeypatchado. O router deve parsear dinheiro com `decimal_from_str`, data ISO com `date.fromisoformat`, chamar a função de persistência uma vez e responder 303 para `/web/proposals/{created.id}`.

- [ ] **Step 7: Registrar o router antes de `pages.router`**

Em `app/main.py`:

```python
from app.routers import board, clients, financeiro, imports, pages, proposal_files, proposals, users

app.include_router(proposal_files.router)
app.include_router(pages.router)
```

Manter os demais routers na ordem relativa atual. A precedência da rota estática será validada na Task 6, depois que seu handler GET e template existirem.

- [ ] **Step 8: Rodar testes de rota e service**

```bash
python3 -m pytest tests/test_proposal_file_routes.py tests/test_proposal_file_service.py -q
```

- [ ] **Checkpoint 5: revisar sem commit**

```bash
git diff --check
git status --short
git diff -- app/routers/proposal_files.py app/main.py app/schemas.py tests/test_proposal_file_routes.py
```

---

### Task 6: Telas de confirmação e integração com propostas existentes

**Files:**
- Modify: `app/routers/proposal_files.py`
- Create: `app/templates_web/proposal_word_reupload.html`
- Create: `app/templates_web/proposal_external_upload.html`
- Modify: `app/templates_web/proposal_detail.html`
- Modify: `app/templates_web/proposal_form.html`
- Modify: `app/templates_web/proposals.html`
- Modify: `tests/test_proposal_file_routes.py`

**Interfaces:**
- Consumes: rotas, schemas e endpoints multipart da Task 5.
- Produces: páginas completas com preview via `fetch`, confirmação humana editável e badges de origem.

- [ ] **Step 1: Escrever testes vermelhos das páginas GET**

Testar:

```python
assert client.get(f"/web/proposals/{source.id}/reenviar-word").status_code == 200
assert "Reenviar Word editado" in response.text
assert "Analisar arquivo" in response.text

external = client.get("/web/proposals/upload-externo")
assert external.status_code == 200
assert "Upload externo de proposta" in external.text
assert "Confirmar e registrar proposta" in external.text
```

A página externa deve conter todos os clientes, somente usuários ativos e data de hoje. Fonte inexistente ou sem DOCX deve produzir 404/409 legível.

- [ ] **Step 2: Criar as duas páginas usando o design existente**

Cada template deve estender `base.html`, usar `.page-header`, `.card`, `.form-grid-*`, `.field`, `.actions`, `.btn`, `.badge` e `.warning`. Copiar o comportamento de dropzone de `import_proposals.html`, mas restringir a um arquivo.

No reenvio, o JS deve:

```javascript
const previewData = new FormData();
previewData.append("file", filesInput.files[0]);
const response = await fetch(`/api/proposal-files/${proposalId}/word-preview`, {
  method: "POST",
  body: previewData,
});
```

Preencher `valor_total` se retornado, mostrar todos os warnings e habilitar confirmação somente após preview bem-sucedido e valor brasileiro válido.

No externo, preencher dropdown/valor pelas sugestões, nunca ocultar os campos editáveis e manter cliente vazio quando não houver sugestão. O POST final deve reenviar o mesmo `filesInput.files[0]` em formulário multipart normal ou `fetch` seguido do redirect fornecido.

- [ ] **Step 3: Implementar os GETs e seus contextos**

O reenvio recebe `proposal`, `download_url` e `today`. O externo recebe `clients`, `users`, `default_user_id` e `today`. Reusar a função de contexto de template existente ou reproduzir exatamente `request`, `format_brl` e `format_date_br` no novo router.

- [ ] **Step 4: Escrever testes vermelhos da origem na listagem/detalhe**

Criar uma proposta de cada origem e afirmar:

```python
assert "Sistema" in listing.text
assert "Word reenviado" in listing.text
assert "Upload externo" in listing.text
assert "Proposta documental" in documental_detail.text
assert "Itens e servicos" not in documental_detail.text
assert "Itens e servicos" in structured_detail.text
```

- [ ] **Step 5: Adicionar badges e modo documental**

Em `proposals.html`, acrescentar coluna “Origem” e badges por valor. Adicionar “Upload externo” ao lado de “Nova proposta” e ajustar `colspan` do estado vazio.

Em `proposal_detail.html`, manter toda a interface atual dentro do ramo `proposal.origem == "sistema"`. Para origens documentais, renderizar cliente, responsável, data, `format_brl(proposal.valor_total)`, origem e arquivos oficiais, sem tabelas de itens/cronograma. Em qualquer origem com DOCX, usar as rotas seguras “Baixar em Word para editar” e “Reenviar Word editado”.

- [ ] **Step 6: Integrar a última proposta na tela estruturada sem alterar seu POST**

Adicionar um painel inicialmente oculto em `proposal_form.html`. No `change` do select de cliente, chamar:

```javascript
const response = await fetch(`/api/proposals/clients/${clientId}/last`);
const proposal = await response.json();
```

Se `proposal.docx_path` existir, mostrar número/revisão, data, link `/web/proposals/${proposal.id}/baixar-word` e `/web/proposals/${proposal.id}/reenviar-word`. Se existir proposta sem DOCX, mostrar a mensagem definida na spec. Se não existir proposta, ocultar o painel. Não adicionar campos ao form nem interceptar seu submit.

- [ ] **Step 7: Testar falha visual de preview e preenchimento manual**

Nos testes HTML, confirmar elementos/IDs e mensagens. Em teste unitário do JS por contrato de markup, afirmar que:

- botão de confirmação nasce desabilitado;
- `marker_found=false` não impede digitar valor manual;
- PDF escaneado mantém selects e valor disponíveis;
- erro HTTP não limpa o input de arquivo;
- HTML usa `textContent` ou `escapeHtml` para mensagens/nomes retornados.

- [ ] **Step 8: Rodar testes de interface e regressão das propostas**

```bash
python3 -m pytest tests/test_proposal_file_routes.py tests/test_dashboard_routes.py -q
python3 -m pytest -q
```

Expected: testes novos de proposta e a suíte existente completa passam.

- [ ] **Checkpoint 6: revisar sem commit**

```bash
git diff --check
git status --short
git diff -- app/templates_web app/routers/proposal_files.py tests/test_proposal_file_routes.py
```

---

### Task 7: Inserção reprodutível e sobrevivência do marcador no template

**Files:**
- Create: `scripts/ensure_docx_total_marker.py`
- Modify: `doc_templates/proposta_template.docx`
- Create: `tests/test_document_total_marker.py`

**Interfaces:**
- Consumes: template atual contendo exatamente um `{{VALOR_TOTAL}}`.
- Produces: template idempotentemente marcado com um `w:sdt/w:tag="AD_VALOR_TOTAL"` que sobrevive ao `docxtpl` e ao LibreOffice.

- [ ] **Step 1: Escrever o teste vermelho do template fonte**

Abrir o DOCX como ZIP e afirmar:

```python
assert count_total_tags(template_bytes) == 1
```

Expected inicial: FAIL, pois o template atual contém o placeholder, mas zero content controls com a tag.

- [ ] **Step 2: Criar script idempotente de marcação**

O script deve:

1. validar DOCX e localizar exatamente um `w:t` contendo `{{VALOR_TOTAL}}`;
2. construir mapa pai→filho do `word/document.xml`;
3. envolver o `w:r` correspondente em:

```xml
<w:sdt>
  <w:sdtPr>
    <w:alias w:val="Valor total AD"/>
    <w:tag w:val="AD_VALOR_TOTAL"/>
  </w:sdtPr>
  <w:sdtContent><!-- run original com {{VALOR_TOTAL}} --></w:sdtContent>
</w:sdt>
```

4. copiar todas as demais entradas ZIP sem alteração;
5. gravar em arquivo temporário, validar novamente e substituir o template;
6. se a tag já existir exatamente uma vez, sair 0 sem alterar bytes;
7. falhar se houver zero ou múltiplos placeholders/tags.

Interface CLI:

```python
def ensure_total_marker(path: Path) -> bool:
    """Retorna True quando alterou o template e False quando já estava marcado."""
```

- [ ] **Step 3: Executar o script no template e repetir para provar idempotência**

```bash
python3 scripts/ensure_docx_total_marker.py doc_templates/proposta_template.docx
shasum -a 256 doc_templates/proposta_template.docx
python3 scripts/ensure_docx_total_marker.py doc_templates/proposta_template.docx
shasum -a 256 doc_templates/proposta_template.docx
```

Expected: primeira execução informa alteração; segunda informa “marcador já presente”; hashes após a primeira e segunda execução são iguais.

- [ ] **Step 4: Testar sobrevivência ao `docxtpl`**

Criar uma proposta real mínima no banco de teste, montar contexto com `document_service.build_template_context()`, renderizar e analisar:

```python
document_service.render_docx_from_template(template_path, context, rendered_path)
analysis = proposal_file_service.analyze_word_reupload(
    rendered_path.name,
    rendered_path.read_bytes(),
)
assert analysis.marker_found is True
assert analysis.valor_total == proposal.valor_total
```

- [ ] **Step 5: Testar sobrevivência ao LibreOffice quando disponível**

O teste de integração deve pular somente quando `shutil.which(settings.libreoffice_cmd)` não localizar o binário. Quando disponível, abrir e salvar uma cópia DOCX em diretório distinto via `soffice --headless --convert-to docx`, então repetir `analyze_word_reupload` e afirmar marcador/valor.

No Docker, esse teste não pode ser pulado porque `/usr/bin/soffice` faz parte da imagem.

- [ ] **Step 6: Rodar testes do marcador**

```bash
python3 -m pytest tests/test_document_total_marker.py -q
```

- [ ] **Checkpoint 7: revisar template e script sem commit**

```bash
git diff --check
git status --short
unzip -p doc_templates/proposta_template.docx word/document.xml | rg -o 'AD_VALOR_TOTAL' | wc -l
python3 scripts/ensure_docx_total_marker.py doc_templates/proposta_template.docx
```

Expected: uma ocorrência; execução idempotente. Não executar commit.

---

### Task 8: Regressão completa, PostgreSQL, HTTP e verificação visual

**Files:**
- Modify only if a failure exposes a defect in files already listed above.

**Interfaces:**
- Consumes: sistema completo das Tasks 1–7.
- Produces: evidência de que os fluxos novos funcionam e os fluxos existentes permanecem intactos.

- [ ] **Step 1: Executar suíte local completa**

```bash
python3 -m pytest -q
python3 -m compileall -q app tests scripts
git diff --check
```

Expected: zero falhas e zero erros de compilação/whitespace. Avisos de depreciação existentes devem ser relatados, não ocultados.

- [ ] **Step 2: Construir e verificar Docker**

```bash
docker compose up -d --build
docker compose ps
docker compose exec -T app pip install -q -r requirements-dev.txt
docker compose exec -T app python -m pytest -q
```

Expected: `db` e `app` healthy; teste do LibreOffice não pulado; suíte verde no Python 3.12 da imagem.

- [ ] **Step 3: Validar upgrade PostgreSQL real sem apagar dados**

Antes do restart, registrar contagem e uma amostra sem PII:

```bash
docker compose exec -T db psql -U propostas -d propostas_db -Atc \
  "SELECT count(*) FROM proposals;"
docker compose restart app
docker compose exec -T db psql -U propostas -d propostas_db -Atc \
  "SELECT origem, count(*) FROM proposals GROUP BY origem ORDER BY origem;"
```

Expected: contagem total preservada; registros anteriores classificados como `sistema`; novo restart idempotente. Não truncar, recriar volume nem rodar comando destrutivo.

- [ ] **Step 4: Smoke HTTP sem mutação**

Verificar 200 em:

```text
/
/web/proposals
/web/proposals/upload-externo
/web/board
/web/contas-a-receber
/web/contas-a-pagar
/import-proposals
```

Verificar que um detalhe com DOCX oferece download/reenvio e que a rota de download devolve MIME DOCX e `Content-Disposition: attachment`.

- [ ] **Step 5: Teste funcional controlado dos dois fluxos**

Usar banco/arquivos de teste, nunca propostas operacionais:

1. gerar proposta estruturada de teste;
2. baixar DOCX, alterar somente o valor dentro do content control e reenviar;
3. confirmar mesmo número, revisão seguinte, arquivos anteriores intactos e novo PDF;
4. subir DOCX externo com cliente/total detectáveis e editar a confirmação;
5. subir PDF textual;
6. subir PDF escaneado e preencher cliente/valor manualmente;
7. confirmar que previews não alteram contagens nem `output`.

- [ ] **Step 6: Inspecionar desktop e mobile se houver navegador conectado**

Em `http://localhost:8000`, validar visualmente:

- lista com badge de origem e botão Upload externo;
- detalhes estruturado e documental;
- painel Word após seleção de cliente;
- reenvio com marcador e fallback manual;
- externo com sugestão, ambiguidade e PDF escaneado;
- larguras desktop e mobile, foco, contraste e mensagens.

Se não houver navegador conectado, não afirmar validação visual; registrar explicitamente a indisponibilidade.

- [ ] **Step 7: Auditoria final do escopo e do Git**

```bash
git diff --check
git status --short
git diff --stat
git diff --name-only
```

Confirmar que não há mudança em `app/services/proposal_service.create_proposal()`, no POST estruturado de `/web/proposals/new` nem no contrato de `/api/import-proposals`.

- [ ] **Checkpoint final: entregar sem commit**

Relatar:

- arquivos criados/alterados;
- resultados exatos das suítes local e Docker;
- resultado da compatibilidade PostgreSQL;
- cenários manuais executados;
- QA visual executado ou indisponível;
- avisos/depreciações restantes;
- confirmação explícita de que nenhum commit ou push foi realizado.
