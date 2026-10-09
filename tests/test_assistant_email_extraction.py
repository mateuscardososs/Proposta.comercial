from datetime import datetime
from zoneinfo import ZoneInfo

from app.assistant.email.classification import to_result
from app.assistant.email.contracts import EmailMessageRecord


def _email(subject: str, text: str) -> EmailMessageRecord:
    return EmailMessageRecord(
        reference="synthetic-extraction-1",
        thread_reference="synthetic-thread-1",
        folder_role="inbox",
        sender="Fornecedor Exemplo <fornecedor@example.test>",
        recipients=("ad@example.test",),
        subject=subject,
        received_at=datetime(2026, 10, 6, 10, tzinfo=ZoneInfo("America/Recife")),
        seen=False,
        text=text,
    )


def test_payable_extraction_uses_only_explicit_document_evidence():
    result = to_result(
        _email(
            "Boleto e nota fiscal do fornecedor Acme",
            "Fornecedor: Acme Instrumentos. Total R$ 1.234,56. "
            "Vencimento em 20/10/2026. Nota fiscal nº NF-4821 emitida em 15/10/2026.",
        )
    )

    fields = result.model_dump().get("extracted_fields")
    assert fields == {
        "party_name": "Acme Instrumentos",
        "party_role": "supplier",
        "amount": "1234.56",
        "due_date": "2026-10-20",
        "issue_date": "2026-10-15",
        "invoice_number": "NF-4821",
        "missing_fields": [],
        "uncertainty": [],
        "evidence": ["supplier_label", "currency_amount", "payment_due_date", "issue_date", "invoice_number"],
    }


def test_quote_extraction_does_not_treat_unrelated_dates_as_deadlines_or_amounts():
    result = to_result(
        _email(
            "Pedido de orçamento da empresa Alfa",
            "Solicitamos orçamento para serviço previsto em 20/10/2026. "
            "Pode apresentar as opções?",
        )
    )

    fields = result.model_dump().get("extracted_fields")
    assert fields is not None
    assert fields["party_name"] == "Alfa"
    assert fields["party_role"] == "client"
    assert fields["amount"] is None
    assert fields["due_date"] is None
    assert "prazo de resposta" in fields["missing_fields"]


def test_ambiguous_multiple_amounts_and_due_dates_are_not_guessed():
    result = to_result(
        _email(
            "Conta a pagar",
            "Fornecedor: Acme. Valores de R$ 200,00 e R$ 300,00; "
            "vencimentos em 10/10/2026 e 20/10/2026.",
        )
    )

    fields = result.model_dump().get("extracted_fields")
    assert fields is not None
    assert fields["amount"] is None
    assert fields["due_date"] is None
    assert "valor" in fields["missing_fields"]
    assert "vencimento" in fields["missing_fields"]
    assert fields["uncertainty"]
