"""Characterize provider declarations before extracting the shared protocol."""

import pytest

from app.assistant.gemini import _gemini_function_declarations, _google_schema
from app.assistant.ollama import DEFAULT_TOOL_NAMES, TOOL_DEFINITIONS, _ollama_tools
from app.assistant.tool_protocol import function_declarations


@pytest.mark.parametrize("allowed", [None, set(), {"consultar_tarefas"}, {"responder_conversa", "consultar_emails"}])
def test_declarations_keep_catalog_order_schema_and_provider_projection(allowed):
    effective = DEFAULT_TOOL_NAMES if allowed is None else allowed
    declarations = _ollama_tools(allowed)
    assert [item["function"]["name"] for item in declarations] == [
        name for name, _, _ in TOOL_DEFINITIONS if name in effective
    ]
    expected = []
    for name, description, model in TOOL_DEFINITIONS:
        if name not in effective:
            continue
        parameters = model.model_json_schema()
        parameters["properties"].pop("tool", None)
        parameters["required"] = [field for field in parameters.get("required", []) if field != "tool"]
        expected.append({"type": "function", "function": {
            "name": name, "description": description, "parameters": parameters,
        }})
    assert declarations == expected
    assert function_declarations(allowed) == [item["function"] for item in expected]
    assert _gemini_function_declarations(effective) == [
        {"name": item["function"]["name"], "description": item["function"]["description"],
         "parameters": _google_schema(item["function"]["parameters"], item["function"]["parameters"].get("$defs", {}))}
        for item in expected
    ]


def test_historical_ollama_policy_helpers_are_explicit_shared_aliases():
    from app.assistant import ollama, response_policy, tool_protocol

    assert ollama._prompt_tool_results is tool_protocol._prompt_tool_results
    for name in (
        "_validate_conversation_grounding", "_validate_service_facts",
        "_validate_email_facts", "_validate_tool_scope", "_repair_reason", "_repair_hint",
    ):
        assert getattr(ollama, name) is getattr(response_policy, name)
