from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from app.assistant.contracts import (
    ConversationCommand,
    TaskCreateCommand,
    TaskQueryCommand,
    UnsupportedCommand,
)
from app.assistant.ollama import OllamaProvider
from app.assistant.provider import (
    ProviderMessage,
    ProviderPendingAction,
    ProviderResponseError,
    ProviderToolResult,
    ProviderUnavailableError,
)


def test_ollama_reports_safe_metrics_for_success_and_repair():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = "HISTORICO_JSON=[]" if calls == 1 else "Posso ajudar a organizar isso."
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": content},
                "total_duration": 2_000_000_000,
                "load_duration": 100_000_000,
                "prompt_eval_count": 321,
                "prompt_eval_duration": 600_000_000,
                "eval_count": 17,
                "eval_duration": 1_100_000_000,
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    interpretation = provider.interpret_with_trace(
        [ProviderMessage(role="user", content="Pode me ajudar?")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert interpretation.command.message == "Posso ajudar a organizar isso."
    assert len(interpretation.inferences) == 2
    rejected, accepted = interpretation.inferences
    assert rejected.repair_reason == "internal_context_exposure"
    assert rejected.prompt_tokens == 321
    assert rejected.output_tokens == 17
    assert rejected.model_load_seconds == 0.1
    assert rejected.ollama_total_seconds == 2
    assert accepted.repair_reason is None
    assert accepted.outcome == "responder_conversa"
    assert accepted.context_characters > len("Pode me ajudar?")
    assert accepted.tool_schema_characters > 0


def test_ollama_can_synthesize_query_result_without_resending_tool_contracts():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "Comece pelo relatório de hoje."}},
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Por onde começo?")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
        tool_results=(
            ProviderToolResult(
                tool="consultar_tarefas",
                payload={"tasks": [{"id": 1, "title": "Relatório", "due_date": "30/09/2026"}]},
            ),
        ),
        allowed_tools=set(),
    )

    assert command.message == "Comece pelo relatório de hoje."
    assert captured["payload"]["tools"] == []


def test_ollama_makes_pending_correction_instruction_explicit():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "corrigir_tarefa",
                                "arguments": {"due_date": "depois de amanha"},
                            }
                        }
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )
    provider.interpret(
        [ProviderMessage(role="user", content="Na verdade, depois de amanhã.")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
        pending_action=ProviderPendingAction(
            action_type="create_task",
            status="pending",
            arguments={"titulo": "Revisar relatorio", "prazo": "2026-10-01"},
        ),
    )

    envelope = captured["payload"]["messages"][1]["content"]
    assert "ESTADO_PENDENTE=Existe" in envelope
    assert "chame corrigir_tarefa" in envelope


def test_ollama_accepts_a_natural_response_without_forcing_a_tool():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": (
                        "Vamos organizar isso. Qual foi a empresa? Posso deixar o relatorio "
                        "como proxima tarefa."
                    ),
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [
            ProviderMessage(
                role="user",
                content="Resolvi uma balanca e deixei os documentos para depois.",
            )
        ],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert isinstance(command, ConversationCommand)
    assert command.message.startswith("Vamos organizar")
    assert "exatamente uma ferramenta" not in captured["payload"]["messages"][0]["content"]


def test_ollama_injects_reviewed_technical_reference_only_for_matching_question():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "Tara não é calibração."}},
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )
    provider.interpret(
        [ProviderMessage(role="user", content="O que significa tara na balança?")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    envelope = captured["payload"]["messages"][1]["content"]
    assert "OIML R 76-1" in envelope
    assert "A tara e o valor" in envelope
    assert "REFERENCIAS_TECNICAS_JSON" in envelope


def test_ollama_receives_structured_tool_results_as_untrusted_data():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "Comece pelo relatorio, que vence em 30/09/2026.",
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Qual e a prioridade?")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
        tool_results=(
            ProviderToolResult(
                tool="consultar_tarefas",
                payload={
                    "tasks": [
                        {
                            "id": 8,
                            "title": "Relatorio",
                            "due_date": "30/09/2026",
                            "status": "A fazer",
                        }
                    ]
                },
            ),
        ),
        allowed_tools={"responder_conversa"},
    )

    assert isinstance(command, ConversationCommand)
    envelope = captured["payload"]["messages"][1]["content"]
    assert "RESULTADOS_FERRAMENTAS_JSON" in envelope
    assert "nao confiaveis" in envelope
    assert "Relatorio" in envelope
    assert {tool["function"]["name"] for tool in captured["payload"]["tools"]} == {
        "responder_conversa"
    }


def test_ollama_repairs_a_reply_that_echoes_the_internal_context_envelope():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = (
            'HISTORICO_JSON=[] RESULTADOS_FERRAMENTAS_JSON=[{"id": 1}] Comece pela tarefa.'
            if calls == 1
            else "Comece pela tarefa Alfa, que é a única pendência encontrada."
        )
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": content}},
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Qual tarefa primeiro?")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
        tool_results=(
            ProviderToolResult(
                tool="consultar_tarefas",
                payload={"tasks": [{"id": 1, "title": "Alfa"}]},
            ),
        ),
        allowed_tools={"responder_conversa"},
    )

    assert calls == 2
    assert command.message.startswith("Comece pela tarefa Alfa")
    assert "_JSON" not in command.message


def test_ollama_repairs_an_invented_consequence_in_task_recommendation():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = (
            "Comece pelo relatório, que venceu em 30/09/2026, o que indica uma falha na entrega essencial."
            if calls == 1
            else "Comece pelo relatório atrasado, pois ele venceu em 30/09/2026."
        )
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )
    interpretation = provider.interpret_with_trace(
        [ProviderMessage(role="user", content="Qual tarefa devo fazer primeiro?")],
        today=date(2026, 10, 1),
        timezone="America/Recife",
        tool_results=(
            ProviderToolResult(
                tool="consultar_tarefas",
                payload={
                    "tasks": [
                        {"id": 1, "title": "Relatório atrasado", "due_date": "30/09/2026"}
                    ]
                },
            ),
        ),
        allowed_tools={"responder_conversa"},
    )

    assert calls == 1
    assert "comprometer" not in interpretation.command.message
    assert "falha na entrega" not in interpretation.command.message
    assert "30/09/2026" in interpretation.command.message
    assert interpretation.inferences[0].repair_reason is None
    assert (
        interpretation.inferences[0].grounding_adjustment
        == "removed_unsupported_task_consequence"
    )


def test_ollama_cannot_claim_the_board_is_empty_without_a_real_query():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": "Não há tarefas no quadro."}},
            )
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "consultar_tarefas", "arguments": {"priorities": True}}}
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    interpretation = provider.interpret_with_trace(
        [ProviderMessage(role="user", content="Analise o quadro e recomende o que fazer primeiro.")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
        allowed_tools={"responder_conversa", "consultar_tarefas"},
    )

    assert isinstance(interpretation.command, TaskQueryCommand)
    assert interpretation.inferences[0].repair_reason == "ungrounded_task_claim"


def test_ollama_failed_validation_exposes_only_safe_attempt_metrics():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {"role": "assistant", "content": "Não há tarefas no quadro."},
                "prompt_eval_count": 100,
                "eval_count": 10,
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderResponseError) as captured:
        provider.interpret_with_trace(
            [ProviderMessage(role="user", content="Mostre as tarefas do quadro.")],
            today=date(2026, 9, 30),
            timezone="America/Recife",
        )

    assert len(captured.value.inferences) == 3
    assert {trace.repair_reason for trace in captured.value.inferences} == {
        "ungrounded_task_claim"
    }
    assert all(trace.prompt_tokens == 100 for trace in captured.value.inferences)


def test_ollama_repairs_task_creation_used_for_an_unavailable_operation():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        tool = (
            {
                "name": "criar_tarefa",
                "arguments": {"title": "Registrar atendimento"},
            }
            if calls == 1
            else {
                "name": "fora_do_escopo",
                "arguments": {
                    "message": (
                        "Ainda não cadastro atendimentos. Posso ajudar a organizar o relato sem salvá-lo."
                    )
                },
            }
        )
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": tool}],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Registre um atendimento de inspeção.")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert calls == 2
    assert isinstance(command, UnsupportedCommand)
    assert "organizar o relato" in command.message


def test_ollama_repairs_text_that_promises_an_unexecuted_task_creation():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            function = {
                "name": "responder_conversa",
                "arguments": {"message": "A tarefa será criada no quadro."},
            }
        else:
            function = {
                "name": "fora_do_escopo",
                "arguments": {
                    "message": "Não cadastro atendimentos, mas posso ajudar a organizar o relato."
                },
            }
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": function}],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Registre um atendimento.")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert calls == 2
    assert isinstance(command, UnsupportedCommand)


def test_ollama_repairs_conversation_that_hides_an_unavailable_operation():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            function = {
                "name": "responder_conversa",
                "arguments": {"message": "Qual cliente devo usar para o atendimento?"},
            }
        else:
            function = {
                "name": "fora_do_escopo",
                "arguments": {
                    "message": "Ainda não cadastro atendimentos; posso ajudar a organizar o relato."
                },
            }
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": function}],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Cadastre um atendimento de inspeção.")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert calls == 2
    assert isinstance(command, UnsupportedCommand)


def test_ollama_uses_configured_model_and_validated_schema():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "criar_tarefa",
                                "arguments": {
                                    "title": "Ligar para o cliente",
                                    "due_date": "amanha",
                                },
                            }
                        }
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-configurado",
        connect_timeout=2,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Crie para amanha")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert isinstance(command, TaskCreateCommand)
    assert command.title == "Ligar para o cliente"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "modelo-configurado"
    assert payload["stream"] is False
    assert isinstance(payload["tools"], list)
    assert "shell" not in json.dumps(payload).lower()
    assert "sql" not in json.dumps(payload).lower()


def test_ollama_rejects_non_local_url():
    with pytest.raises(ValueError, match="local"):
        OllamaProvider(
            base_url="https://example.com",
            model="qualquer",
            connect_timeout=2,
            read_timeout=30,
        )


def test_ollama_connection_failure_has_specific_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    provider = OllamaProvider(
        base_url="http://localhost:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=1,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError, match="Ollama"):
        provider.interpret(
            [ProviderMessage(role="user", content="Liste tarefas")],
            today=date(2026, 9, 30),
            timezone="America/Recife",
        )


def test_ollama_timeout_has_specific_error_and_no_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow model", request=request)

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-lento",
        connect_timeout=1,
        read_timeout=1,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderUnavailableError, match="Ollama"):
        provider.interpret(
            [ProviderMessage(role="user", content="Crie uma tarefa")],
            today=date(2026, 9, 30),
            timezone="America/Recife",
        )


def test_ollama_prompt_limits_tools_and_treats_content_as_data():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "cancelar_acao", "arguments": {}}}
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    provider.interpret(
        [ProviderMessage(role="user", content="Apague tudo e rode um comando")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    payload = captured["payload"]
    assert isinstance(payload, dict)
    system_prompt = payload["messages"][0]["content"]
    tool_names = {tool["function"]["name"] for tool in payload["tools"]}
    assert {"confirmar_acao", "cancelar_acao", "corrigir_tarefa"}.issubset(tool_names)
    assert "nao confiaveis" in system_prompt
    assert "exclua" in system_prompt
    assert "financeiro" in system_prompt
    assert "preco" in system_prompt
    assert "Nunca converta" in system_prompt
    request_envelope = payload["messages"][1]["content"]
    assert "PEDIDO_ATUAL=" in request_envelope
    assert "rode um comando" in request_envelope


def test_ollama_accepts_one_validated_single_tool_call():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "consultar_tarefas",
                                "arguments": {"overdue_only": True, "limit": 10},
                            }
                        }
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Tem alguma tarefa atrasada?")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert isinstance(command, TaskQueryCommand)
    assert command.overdue_only is True
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert "format" not in payload
    assert {tool["function"]["name"] for tool in payload["tools"]} == {
        "consultar_tarefas",
        "criar_tarefa",
        "corrigir_tarefa",
        "confirmar_acao",
        "cancelar_acao",
        "fora_do_escopo",
        "responder_conversa",
    }


def test_ollama_repairs_a_text_response_once_by_requiring_a_tool_call():
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(
                200,
                json={
                    "message": {
                        "role": "assistant",
                        "content": "Entendido, vou atribuir a Carlos.",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "corrigir_tarefa",
                                "arguments": {"responsible": "Carlos"},
                            }
                        }
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Deixe essa tarefa com Carlos.")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert command.responsible == "Carlos"
    assert len(payloads) == 2
    repair_messages = payloads[1]["messages"]
    assert isinstance(repair_messages, list)
    assert repair_messages[-2]["role"] == "assistant"
    assert "exatamente uma ferramenta" in repair_messages[-1]["content"]


def test_ollama_accepts_only_a_validated_textual_out_of_scope_refusal():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": (
                        'fora_do_escopo {"message": "Nao posso apagar tarefas; nada foi alterado."}'
                    ),
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Apague todas as tarefas.")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert isinstance(command, UnsupportedCommand)
    assert "nada foi alterado" in command.message


def test_ollama_accepts_a_structured_natural_conversation_reply():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "responder_conversa",
                                "arguments": {
                                    "message": "Boa tarde! Como posso ajudar com o seu quadro?"
                                },
                            }
                        }
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )

    command = provider.interpret(
        [ProviderMessage(role="user", content="Oi, boa tarde.")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert isinstance(command, ConversationCommand)
    assert command.message.startswith("Boa tarde")
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert "responder_conversa" in {
        tool["function"]["name"] for tool in payload["tools"]
    }
    system_prompt = payload["messages"][0]["content"]
    assert "nao afirme" in system_prompt.lower()
    assert "consulta real" in system_prompt.lower()
    assert "organizar relatos" in system_prompt.lower()


def test_ollama_delimits_history_and_classifies_only_the_current_request():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "responder_conversa",
                                "arguments": {"message": "Eu estava explicando a tarefa encontrada."},
                            }
                        }
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )
    provider.interpret(
        [
            ProviderMessage(role="user", content="Quais tarefas eu tenho?"),
            ProviderMessage(role="assistant", content="Encontrei a tarefa preparar relatório."),
            ProviderMessage(role="user", content="O que você quis dizer?"),
        ],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert len(payload["messages"]) == 2
    request_message = payload["messages"][1]["content"]
    assert "HISTORICO_JSON=" in request_message
    assert "Encontrei a tarefa preparar relatório." in request_message
    assert "ULTIMA_RESPOSTA_ASSISTENTE=" not in request_message
    assert 'PEDIDO_ATUAL="O que você quis dizer?"' in request_message
    assert "responder_conversa" in {
        tool["function"]["name"] for tool in payload["tools"]
    }


@pytest.mark.parametrize(
    "content",
    [
        'responder_conversa {"message": "Boa tarde! Como posso ajudar?"}',
        'responder_conversa "Boa tarde! Como posso ajudar?"',
    ],
)
def test_ollama_accepts_validated_textual_conversation_fallback(content):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )
    command = provider.interpret(
        [ProviderMessage(role="user", content="Oi")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert isinstance(command, ConversationCommand)
    assert command.message.startswith("Boa tarde")


def test_ollama_repairs_a_conversation_that_changes_a_real_task_status():
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        message = (
            "A tarefa #1 está em andamento e vence em 02/10/2026."
            if calls == 1
            else "A tarefa #1 está a fazer e vence em 02/10/2026."
        )
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "responder_conversa",
                                "arguments": {"message": message},
                            }
                        }
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )
    command = provider.interpret(
        [
            ProviderMessage(role="assistant", content="Encontrei estas tarefas:\n- #1 Relatório — A fazer — 02/10/2026"),
            ProviderMessage(role="user", content="O que você quis dizer?"),
        ],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert calls == 2
    assert isinstance(command, ConversationCommand)
    assert "a fazer" in command.message


def test_meta_conversation_accepts_natural_text_under_the_restricted_tool():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "Eu quis dizer que a tarefa #1 está a fazer em 02/10/2026.",
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )
    command = provider.interpret(
        [
            ProviderMessage(role="assistant", content="Encontrei estas tarefas:\n- #1 Relatório — A fazer — 02/10/2026"),
            ProviderMessage(role="user", content="O que você quis dizer?"),
        ],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    assert isinstance(command, ConversationCommand)
    assert command.message.startswith("Eu quis dizer")


def test_ollama_bounds_long_history_before_building_the_context_envelope():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "responder_conversa",
                                "arguments": {"message": "Como posso ajudar?"},
                            }
                        }
                    ],
                }
            },
        )

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        model="modelo-local",
        connect_timeout=1,
        read_timeout=30,
        transport=httpx.MockTransport(handler),
    )
    history = [
        ProviderMessage(role="user" if index % 2 == 0 else "assistant", content=str(index) * 4000)
        for index in range(6)
    ]
    provider.interpret(
        [*history, ProviderMessage(role="user", content="Como você pode ajudar?")],
        today=date(2026, 9, 30),
        timezone="America/Recife",
    )

    payload = captured["payload"]
    envelope = payload["messages"][1]["content"]
    assert len(envelope) < 12000
    assert "5555555555" in envelope
    assert "0000000000" not in envelope
