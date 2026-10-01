from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.assistant.contracts import (
    CancelActionCommand,
    ConversationCommand,
    ConfirmActionCommand,
    TaskDraftCorrectionCommand,
    assistant_command_adapter,
)


@pytest.mark.parametrize(
    ("payload", "expected_type"),
    [
        ({"tool": "confirmar_acao"}, ConfirmActionCommand),
        ({"tool": "cancelar_acao"}, CancelActionCommand),
        (
            {
                "tool": "corrigir_tarefa",
                "title": "Revisar relatorio",
                "due_date": "depois de amanha",
            },
            TaskDraftCorrectionCommand,
        ),
    ],
)
def test_conversation_control_commands_are_typed(payload, expected_type):
    command = assistant_command_adapter.validate_python(payload)

    assert isinstance(command, expected_type)


def test_commands_reject_unexpected_fields():
    with pytest.raises(ValidationError):
        assistant_command_adapter.validate_python(
            {"tool": "confirmar_acao", "sql": "DELETE FROM tasks"}
        )


def test_task_draft_correction_requires_an_explicit_change():
    with pytest.raises(ValidationError):
        TaskDraftCorrectionCommand()


def test_conversation_command_accepts_a_natural_validated_reply():
    command = assistant_command_adapter.validate_python(
        {
            "tool": "responder_conversa",
            "message": "Boa tarde! Posso consultar e criar tarefas no quadro.",
        }
    )

    assert isinstance(command, ConversationCommand)


@pytest.mark.parametrize("message", ["", "x" * 2401])
def test_conversation_command_rejects_empty_or_excessive_replies(message):
    with pytest.raises(ValidationError):
        ConversationCommand(message=message)
