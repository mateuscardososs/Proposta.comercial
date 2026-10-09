from __future__ import annotations

from app.assistant.contracts import AssistantReply
from app.services.document_search_service import DocumentSearchResult


def present_document_search(conversation_id: int, result: DocumentSearchResult) -> AssistantReply:
    items = [evidence.as_dict() for evidence in result.evidence]
    if items:
        lines = ["Encontrei estes trechos nos documentos registrados:"]
        for item in items:
            source = str(item["document_name"])
            if item.get("page") is not None:
                source += f", página {item['page']}"
            else:
                source += f", seção {item.get('section') or 'não identificada'}"
            lines.append(f"• “{item['excerpt']}”\n  Fonte: {source}.")
        message = "\n\n".join(lines)
        if result.partial_documents:
            message += (
                f"\n\nA busca é parcial: {result.partial_documents} arquivo(s) foram indexados parcialmente; "
                "a ausência de outras informações não está confirmada."
            )
        if result.unreadable_documents:
            message += (
                f"\n\n{result.unreadable_documents} arquivo(s) registrado(s) não puderam ser consultados; "
                "a ausência de outras informações não está confirmada."
            )
        if result.ocr_unavailable_documents:
            message += document_ocr_limitation(result)
        spoken_message = f"Encontrei {len(items)} trecho(s) com referência de documento. "
        spoken_message += " ".join(
            f"{item['excerpt']} Fonte: {item['document_name']}, "
            f"{'página ' + str(item['page']) if item.get('page') is not None else 'seção ' + str(item.get('section') or 'não identificada')}."
            for item in items[:2]
        )
    elif result.registered_documents == 0:
        message = "Não encontrei documentos importados e registrados para consulta nesta aplicação."
        spoken_message = "Não encontrei documentos registrados para consulta."
    elif result.readable_documents == 0 and result.unreadable_documents:
        message = (
            "Não consegui consultar os arquivos registrados. "
            "Não posso confirmar se a informação solicitada existe nos documentos."
        )
        if result.ocr_unavailable_documents:
            message += document_ocr_limitation(result)
        spoken_message = "Não consegui consultar os arquivos registrados; não posso confirmar essa informação."
    else:
        message = "Não encontrei evidência suficiente nos documentos consultáveis para responder."
        if result.unreadable_documents:
            message += (
                f" A busca é parcial: {result.unreadable_documents} arquivo(s) registrado(s) "
                "não puderam ser consultados; a ausência não está confirmada."
            )
        if result.partial_documents:
            message += (
                f" {result.partial_documents} arquivo(s) foram indexados parcialmente; "
                "a ausência de outras informações não está confirmada."
            )
        if result.ocr_unavailable_documents:
            message += document_ocr_limitation(result)
        spoken_message = "Não encontrei evidência suficiente nos documentos consultáveis para responder."
    if result.unreadable_documents or result.partial_documents:
        spoken_message += " A busca foi parcial, então não posso confirmar ausência de outras informações."
    return AssistantReply(
        conversation_id=conversation_id,
        kind="text",
        message=message,
        spoken_message=spoken_message,
        document_items=items,
        limitations=(
            (
                ["A busca foi parcial porque há arquivos registrados que não puderam ser consultados."]
                + (["OCR local indisponível para alguns PDFs sem camada de texto."] if result.ocr_unavailable_documents else [])
            )
            if result.unreadable_documents or result.partial_documents else []
        ),
    )



def document_ocr_limitation(result) -> str:
    note = (
        f" OCR local não está disponível para {result.ocr_unavailable_documents} PDF(s) "
        "sem texto pesquisável."
    )
    if result.ocr_unavailable_reasons:
        note += " Motivo identificado: " + "; ".join(result.ocr_unavailable_reasons) + "."
    return note
