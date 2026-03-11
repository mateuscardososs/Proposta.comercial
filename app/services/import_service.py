from __future__ import annotations


def manual_assisted_import_placeholder() -> str:
    return (
        "Manual assisted import: operador seleciona cliente/usuario, "
        "revisa campos e confirma criacao da proposta no sistema."
    )


def csv_import_placeholder() -> str:
    return (
        "CSV import: mapear colunas para proposta, itens e cronograma; "
        "validar dados antes de persistir e registrar erros por linha."
    )


def docx_parsing_placeholder() -> str:
    return (
        "DOCX parsing: extrair placeholders conhecidos, converter para payload "
        "interno e revisar campos nao reconhecidos antes de salvar."
    )
