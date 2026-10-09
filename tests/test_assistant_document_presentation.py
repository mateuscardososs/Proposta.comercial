from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.assistant import service as service_module
from app.assistant.document_presentation import (
    document_ocr_limitation,
    present_document_search,
)
from app.assistant.service import AssistantService
from app.services.document_search_service import DocumentEvidence, DocumentSearchResult


def evidence(page=None, section=None, excerpt="Trecho"):
    return DocumentEvidence("proposta.docx", 42, "00", page, section, excerpt, 1.0)


PARTIAL_SPOKEN = " A busca foi parcial, então não posso confirmar ausência de outras informações."
LIMITATION = "A busca foi parcial porque há arquivos registrados que não puderam ser consultados."
OCR_NOTE = (
    " OCR local não está disponível para 1 PDF(s) sem texto pesquisável."
    " Motivo identificado: ausente; tempo limite."
)


@pytest.mark.parametrize("result,message,spoken,limitations", [
    (
        DocumentSearchResult((), 0, 0, 0),
        "Não encontrei documentos importados e registrados para consulta nesta aplicação.",
        "Não encontrei documentos registrados para consulta.", [],
    ),
    (
        DocumentSearchResult((), 2, 0, 2),
        ("Não consegui consultar os arquivos registrados. "
         "Não posso confirmar se a informação solicitada existe nos documentos."),
        "Não consegui consultar os arquivos registrados; não posso confirmar essa informação."
        + PARTIAL_SPOKEN, [LIMITATION],
    ),
    (
        DocumentSearchResult((), 1, 1, 0),
        "Não encontrei evidência suficiente nos documentos consultáveis para responder.",
        "Não encontrei evidência suficiente nos documentos consultáveis para responder.", [],
    ),
    (
        DocumentSearchResult((), 3, 1, 2, partial_documents=1),
        ("Não encontrei evidência suficiente nos documentos consultáveis para responder."
        " A busca é parcial: 2 arquivo(s) registrado(s) não puderam ser consultados; "
        "a ausência não está confirmada."
        " 1 arquivo(s) foram indexados parcialmente; "
         "a ausência de outras informações não está confirmada."),
        "Não encontrei evidência suficiente nos documentos consultáveis para responder."
        + PARTIAL_SPOKEN, [LIMITATION],
    ),
    (
        DocumentSearchResult((), 1, 0, 1, 1, ocr_unavailable_reasons=("ausente", "tempo limite")),
        "Não consegui consultar os arquivos registrados. "
        "Não posso confirmar se a informação solicitada existe nos documentos." + OCR_NOTE,
        "Não consegui consultar os arquivos registrados; não posso confirmar essa informação."
        + PARTIAL_SPOKEN, [LIMITATION, "OCR local indisponível para alguns PDFs sem camada de texto."],
    ),
    (
        DocumentSearchResult((), 2, 1, 1, 1, ocr_unavailable_reasons=("ausente", "tempo limite")),
        "Não encontrei evidência suficiente nos documentos consultáveis para responder."
        " A busca é parcial: 1 arquivo(s) registrado(s) não puderam ser consultados; "
        "a ausência não está confirmada." + OCR_NOTE,
        "Não encontrei evidência suficiente nos documentos consultáveis para responder."
        + PARTIAL_SPOKEN, [LIMITATION, "OCR local indisponível para alguns PDFs sem camada de texto."],
    ),
])
def test_document_empty_result_characterization(monkeypatch, result, message, spoken, limitations):
    search = Mock(return_value=result)
    monkeypatch.setattr(service_module, "search_proposal_documents", search)
    db = Mock()
    owner = SimpleNamespace(
        db=db, output_dir="synthetic-output",
        _document_ocr_limitation=AssistantService._document_ocr_limitation,
    )
    reply = AssistantService._execute_document_query(owner, 23, "consulta sintética")
    search.assert_called_once_with(db, output_dir="synthetic-output", query="consulta sintética")
    assert present_document_search(23, result) == reply
    assert (reply.conversation_id, reply.kind) == (23, "text")
    assert (reply.message, reply.spoken_message, reply.document_items, reply.limitations) == (
        message, spoken, [], limitations,
    )


@pytest.mark.parametrize("partial", [False, True])
def test_document_evidence_exact_citations_and_two_spoken_excerpts(monkeypatch, partial):
    items = (evidence(3, "Ignorada", "Primeiro"), evidence(section="Pagamento", excerpt="Segundo"),
             evidence(excerpt="Terceiro"))
    result = DocumentSearchResult(
        items, 3, 2, int(partial), int(partial), int(partial),
        ("ausente", "tempo limite") if partial else (),
    )
    monkeypatch.setattr(service_module, "search_proposal_documents", Mock(return_value=result))
    owner = SimpleNamespace(
        db=Mock(), output_dir="synthetic-output",
        _document_ocr_limitation=AssistantService._document_ocr_limitation,
    )
    reply = AssistantService._execute_document_query(owner, 23, "consulta")
    assert present_document_search(23, result) == reply
    message = (
        "Encontrei estes trechos nos documentos registrados:\n\n"
        "• “Primeiro”\n  Fonte: proposta.docx, página 3.\n\n"
        "• “Segundo”\n  Fonte: proposta.docx, seção Pagamento.\n\n"
        "• “Terceiro”\n  Fonte: proposta.docx, seção não identificada."
    )
    spoken = (
        "Encontrei 3 trecho(s) com referência de documento. "
        "Primeiro Fonte: proposta.docx, página 3. Segundo Fonte: proposta.docx, seção Pagamento."
    )
    if partial:
        message += (
            "\n\nA busca é parcial: 1 arquivo(s) foram indexados parcialmente; "
            "a ausência de outras informações não está confirmada."
            "\n\n1 arquivo(s) registrado(s) não puderam ser consultados; "
            "a ausência de outras informações não está confirmada." + OCR_NOTE
        )
        spoken += PARTIAL_SPOKEN
    assert reply.message == message
    assert reply.spoken_message == spoken
    assert reply.document_items == [item.as_dict() for item in items]
    assert reply.limitations == (
        [LIMITATION, "OCR local indisponível para alguns PDFs sem camada de texto."] if partial else []
    )


@pytest.mark.parametrize("reasons,suffix", [
    ((), ""), (("ausente", "tempo limite"), " Motivo identificado: ausente; tempo limite."),
])
def test_document_ocr_historical_helper_exact(reasons, suffix):
    result = DocumentSearchResult((), 1, 0, 1, 1, ocr_unavailable_reasons=reasons)
    assert AssistantService._document_ocr_limitation is document_ocr_limitation
    assert AssistantService._document_ocr_limitation(result) == (
        " OCR local não está disponível para 1 PDF(s) sem texto pesquisável." + suffix
    )
