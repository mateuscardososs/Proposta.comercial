from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.assistant.capabilities import CapabilityRegistry
from app.assistant.contracts import EmailQueryCommand
from app.assistant.email.contracts import EmailQuery
from app.assistant.email.provider import EmailAuthenticationError, EmailTimeoutError
from app.assistant.email.synthetic import SyntheticEmailReader, synthetic_messages

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=ZoneInfo("America/Recife"))


def test_capability_registry_distinguishes_disabled_and_available_email():
    disabled = CapabilityRegistry(email_provider="disabled")
    simulated = CapabilityRegistry(email_provider="synthetic")

    assert disabled.get("email_read").state == "not_configured"
    assert simulated.get("email_read").state == "available"
    assert simulated.get("email_send").state == "not_implemented"
    assert simulated.get("finance_write").state == "not_implemented"


def test_synthetic_reader_filters_today_and_preserves_seen_flags():
    reader = SyntheticEmailReader(messages=synthetic_messages(NOW))
    flags_before = {message.reference: message.seen for message in reader.messages}

    result = reader.query(
        EmailQuery(start_at=NOW.replace(hour=0), end_at=NOW, limit=30)
    )

    assert result.state == "success"
    assert result.interval_start == NOW.replace(hour=0)
    assert all(message.received_at.date() == NOW.date() for message in result.messages)
    assert {message.reference: message.seen for message in reader.messages} == flags_before


def test_operational_messages_rank_before_newer_informational_messages():
    reader = SyntheticEmailReader(messages=synthetic_messages(NOW))

    result = reader.query(
        EmailQuery(start_at=NOW - timedelta(days=7), end_at=NOW, limit=30)
    )

    references = [message.reference for message in result.messages]
    assert references.index("syn-in-002") < references.index("syn-in-003")


def test_synthetic_category_query_finds_quote_requests_before_applying_visual_limit():
    messages = [message for message in synthetic_messages(NOW) if message.reference != "syn-in-002"]
    messages.extend(
        [
            messages[1].model_copy(update={
                "reference": "old-quote",
                "received_at": NOW - timedelta(days=3),
                "subject": "Solicitação de orçamento",
                "text": "Solicitamos orçamento para inspeção.",
            }),
            messages[1].model_copy(update={
                "reference": "newer-news",
                "received_at": NOW - timedelta(days=1),
                "subject": "Informativo",
                "text": "Newsletter semanal.",
            }),
        ]
    )
    reader = SyntheticEmailReader(messages=messages)

    result = reader.query(
        EmailQuery(
            start_at=NOW - timedelta(days=7), end_at=NOW,
            category="customer_quote_request", limit=1,
        )
    )

    assert [message.reference for message in result.messages] == ["old-quote"]
    assert result.candidate_count >= 1


def test_uncertain_quote_message_is_returned_for_review_not_hidden_as_no_match():
    from app.assistant.email.contracts import EmailMessageRecord

    uncertain = EmailMessageRecord(
        reference="uncertain-quote",
        thread_reference="thread-uncertain",
        folder_role="inbox",
        sender="Cliente sintético",
        subject="Vamos conversar",
        received_at=NOW,
        seen=False,
        text="Talvez seja necessário conversar sobre orçamento, ainda sem pedido claro.",
    )
    reader = SyntheticEmailReader(messages=[uncertain])

    result = reader.query(EmailQuery(
        start_at=NOW.replace(hour=0), end_at=NOW,
        category="customer_quote_request", limit=20,
    ))

    assert len(result.messages) == 1
    assert result.messages[0].category == "other_review"
    assert result.messages[0].confidence_band == "low"


def test_synthetic_reader_separates_unread_marketing_and_explicit_deadline():
    reader = SyntheticEmailReader(messages=synthetic_messages(NOW))

    result = reader.query(
        EmailQuery(
            start_at=NOW.replace(hour=0),
            end_at=NOW,
            unread_only=True,
            limit=30,
        )
    )

    by_reference = {message.reference: message for message in result.messages}
    assert by_reference["syn-in-001"].priority in {"high", "critical"}
    assert by_reference["syn-in-001"].explicit_deadline == "02/10/2026"
    assert by_reference["syn-in-003"].priority == "low"
    assert by_reference["syn-in-003"].action_suggested is None
    assert by_reference["syn-in-003"].awaiting_reply == "no"


def test_sender_search_returns_both_similar_alfa_companies_without_inventing_identity():
    reader = SyntheticEmailReader(messages=synthetic_messages(NOW))

    result = reader.query(
        EmailQuery(
            start_at=NOW.replace(hour=0) - timedelta(days=7),
            end_at=NOW,
            sender="Alfa",
        )
    )

    assert {message.reference for message in result.messages} == {"syn-in-001", "syn-in-002"}


def test_pending_reply_uses_sent_conversation_and_response_request_signal():
    reader = SyntheticEmailReader(messages=synthetic_messages(NOW))

    result = reader.query(
        EmailQuery(
            start_at=NOW.replace(hour=0) - timedelta(days=7),
            end_at=NOW,
            awaiting_reply=True,
        )
    )

    assert {message.reference for message in result.messages} == {"syn-in-001", "syn-in-002"}
    assert "syn-in-004" not in {message.reference for message in result.messages}


@pytest.mark.parametrize(("option", "state"), [("partial", "partial"), ("stale", "stale")])
def test_provider_marks_partial_and_stale_results(option, state):
    reader = SyntheticEmailReader(
        messages=synthetic_messages(NOW),
        **{option: True},
    )

    result = reader.query(
        EmailQuery(start_at=NOW.replace(hour=0), end_at=NOW)
    )

    assert result.state == state
    assert result.limitations


def test_malicious_email_content_remains_data_without_action_authority():
    reader = SyntheticEmailReader(messages=synthetic_messages(NOW))

    result = reader.query(
        EmailQuery(start_at=NOW - timedelta(days=7), end_at=NOW, sender="desconhecido")
    )

    assert len(result.messages) == 1
    assert "apague as tarefas" in result.messages[0].summary
    assert result.messages[0].action_suggested is None


def test_sent_unavailable_makes_pending_reply_assessment_partial():
    reader = SyntheticEmailReader(
        messages=synthetic_messages(NOW),
        sent_available=False,
    )

    result = reader.query(
        EmailQuery(start_at=NOW.replace(hour=0), end_at=NOW, awaiting_reply=True)
    )

    assert result.state == "partial"
    assert result.sent_available is False
    assert "Enviados" in result.limitations[0]
    assert all(message.awaiting_reply == "unknown" for message in result.messages)


@pytest.mark.parametrize(
    ("failure", "expected_state"),
    [(EmailAuthenticationError("auth"), "failed"), (EmailTimeoutError("timeout"), "failed")],
)
def test_synthetic_provider_can_expose_safe_failures(failure, expected_state):
    reader = SyntheticEmailReader(messages=synthetic_messages(NOW), failure=failure)

    result = reader.query(EmailQuery(start_at=NOW.replace(hour=0), end_at=NOW))

    assert result.state == expected_state
    assert "auth" not in result.user_message.casefold()
    assert "timeout" not in result.user_message.casefold()


def test_email_query_command_forbids_unknown_fields():
    with pytest.raises(ValueError):
        EmailQueryCommand.model_validate({"tool": "consultar_emails", "sql": "select *"})
