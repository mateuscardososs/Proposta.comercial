from __future__ import annotations

from collections.abc import Sequence

from app.assistant.contracts import (
    CancelActionCommand,
    ConfirmActionCommand,
    ConversationCommand,
    CorrectServiceReportCommand,
    EmailQueryCommand,
    PrepareServiceReportCommand,
    ServiceDraftCorrectionCommand,
    ServiceEventDraftCommand,
    ServiceQueryCommand,
    ServiceReminderDraftCommand,
    TaskCreateCommand,
    TaskDraftCorrectionCommand,
    TaskQueryCommand,
    UnsupportedCommand,
)
from app.assistant.provider import ProviderToolResult

CONTEXT_CHARACTER_BUDGET = 3200
PROMPT_DATA_CHARACTER_BUDGET = 8000
DEFAULT_TOOL_NAMES = frozenset(
    {"responder_conversa", "consultar_tarefas", "consultar_emails", "criar_tarefa",
     "corrigir_tarefa", "confirmar_acao", "cancelar_acao", "fora_do_escopo",
     "preparar_relatorio_tecnico", "corrigir_previa_relatorio_tecnico"}
)

TOOL_DEFINITIONS = (
    (
        "responder_conversa",
        "Responder naturalmente quando nenhuma consulta ou acao do sistema for necessaria.",
        ConversationCommand,
    ),
    (
        "consultar_tarefas",
        "Consultar tarefas reais do quadro quando a resposta depende desses dados.",
        TaskQueryCommand,
    ),
    (
        "consultar_emails",
        (
            "Consultar e-mails quando a resposta depender da caixa. Use period=today para hoje, "
            "week para esta semana e custom somente com datas informadas."
        ),
        EmailQueryCommand,
    ),
    (
        "consultar_servicos",
        "Consultar chamados e etapas de servico reais antes de afirmar seu estado.",
        ServiceQueryCommand,
    ),
    (
        "registrar_evento_servico",
        "Preparar registro de chamado, visita, inspecao ou execucao para confirmacao; nao gravar ainda.",
        ServiceEventDraftCommand,
    ),
    (
        "corrigir_registro_servico",
        "Corrigir rascunho ou preparar correcao de evento existente para confirmacao.",
        ServiceDraftCorrectionCommand,
    ),
    (
        "criar_lembretes_servico",
        "Preparar ate cinco lembretes vinculados a chamado para confirmacao independente.",
        ServiceReminderDraftCommand,
    ),
    (
        "preparar_relatorio_tecnico",
        "Localizar um chamado concluído e preparar prévia editável de relatório técnico para confirmação. Nunca gerar antes da confirmação.",
        PrepareServiceReportCommand,
    ),
    (
        "corrigir_previa_relatorio_tecnico",
        "Corrigir somente campos informados da prévia pendente de relatório técnico; a correção exige nova confirmação.",
        CorrectServiceReportCommand,
    ),
    (
        "criar_tarefa",
        (
            "Preparar uma nova tarefa para confirmacao somente quando o usuario pedir explicitamente "
            "uma tarefa, lembrete ou agendamento; nunca substituir uma funcao indisponivel."
        ),
        TaskCreateCommand,
    ),
    (
        "corrigir_tarefa",
        "Corrigir somente os campos informados do rascunho de tarefa pendente.",
        TaskDraftCorrectionCommand,
    ),
    ("confirmar_acao", "Confirmar e salvar a ultima criacao pendente.", ConfirmActionCommand),
    ("cancelar_acao", "Cancelar a ultima criacao pendente sem salvar.", CancelActionCommand),
    (
        "fora_do_escopo",
        "Explicar uma acao indisponivel sem afirmar que ela foi executada.",
        UnsupportedCommand,
    ),
)


def _prompt_tool_results(
    tool_results: Sequence[ProviderToolResult],
) -> list[dict[str, object]]:
    compact: list[dict[str, object]] = []
    for result in tool_results:
        serialized = result.model_dump(mode="json")
        payload = dict(serialized.get("payload") or {})
        if result.tool == "consultar_servicos":
            allowed_fields = (
                "id", "client", "summary", "execution_status", "administrative_status",
                "next_pending_step", "opened_on", "technically_completed_at",
                "administratively_closed_at", "event_types", "effective_event_count",
                "recent_events", "workflow_steps",
            )
            raw_calls = payload.get("service_calls", [])
            string_limits = {
                "client": 120,
                "summary": 180,
                "next_pending_step": 80,
                "execution_status": 40,
                "administrative_status": 40,
                "opened_on": 40,
                "technically_completed_at": 40,
                "administratively_closed_at": 40,
            }
            calls = []
            for item in (raw_calls[:10] if isinstance(raw_calls, list) else []):
                if not isinstance(item, dict):
                    continue
                compact_item = {key: item[key] for key in allowed_fields if key in item}
                for key, limit in string_limits.items():
                    if isinstance(compact_item.get(key), str):
                        compact_item[key] = compact_item[key][:limit]
                compact_item["event_types"] = [
                    str(value)[:32] for value in item.get("event_types", [])[:10]
                ] if isinstance(item.get("event_types"), list) else []
                recent = item.get("recent_events", [])
                compact_item["recent_events"] = [
                    {
                        "event_type": str(event.get("event_type", ""))[:32],
                        "occurred_on": str(event.get("occurred_on", ""))[:40],
                        "description": str(event.get("description", ""))[:240],
                    }
                    for event in (recent[-3:] if isinstance(recent, list) else [])
                    if isinstance(event, dict)
                ]
                steps = item.get("workflow_steps", [])
                compact_item["workflow_steps"] = [
                    {"step_type": str(step.get("step_type", ""))[:32],
                     "status": str(step.get("status", ""))[:32]}
                    for step in (steps[:5] if isinstance(steps, list) else [])
                    if isinstance(step, dict)
                ]
                event_count = item.get("effective_event_count", 0)
                compact_item["effective_event_count"] = min(max(event_count, 0), 10000) if isinstance(event_count, int) else 0
                calls.append(compact_item)
            serialized["payload"] = {
                "count": payload.get("count"),
                "service_calls": calls,
            }
            compact.append(serialized)
            continue
        raw_items = payload.get("messages" if result.tool == "consultar_emails" else "tasks", [])
        if isinstance(raw_items, list):
            if result.tool == "consultar_emails":
                allowed_fields = (
                    "reference", "sender", "subject", "received_at", "seen", "summary", "priority",
                    "priority_reason", "action_suggested", "explicit_deadline", "inferred_deadline",
                    "awaiting_reply", "limitations",
                )
                limits = {
                    "reference": 160,
                    "sender": 240,
                    "subject": 240,
                    "summary": 280,
                    "priority_reason": 240,
                    "action_suggested": 200,
                }
                items = []
                for item in raw_items[:3]:
                    if not isinstance(item, dict):
                        continue
                    compact_item = {key: item.get(key) for key in allowed_fields if key in item}
                    for key, limit in limits.items():
                        if isinstance(compact_item.get(key), str):
                            compact_item[key] = compact_item[key][:limit]
                    items.append(compact_item)
                payload["messages"] = items
            else:
                payload["tasks"] = raw_items[:10]
        serialized["payload"] = payload
        compact.append(serialized)
    return compact


def function_declarations(allowed_tools: set[str] | None = None) -> list[dict[str, object]]:
    effective_tools = DEFAULT_TOOL_NAMES if allowed_tools is None else allowed_tools
    tools: list[dict[str, object]] = []
    for name, description, model in TOOL_DEFINITIONS:
        if name not in effective_tools:
            continue
        parameters = model.model_json_schema()
        properties = dict(parameters.get("properties", {}))
        properties.pop("tool", None)
        parameters["properties"] = properties
        parameters["required"] = [
            field for field in parameters.get("required", []) if field != "tool"
        ]
        tools.append(
            {
                "name": name,
                "description": description,
                "parameters": parameters,
            }
        )
    return tools



