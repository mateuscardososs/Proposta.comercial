from __future__ import annotations

import json
import re
from collections.abc import Sequence

from pydantic import ValidationError

from app.assistant.contracts import (
    AssistantCommand,
    ConversationCommand,
    TaskCreateCommand,
)
from app.assistant.dates import normalize_text
from app.assistant.evidence import (
    references_prior_email_context,
    validate_execution_claims,
)
from app.assistant.provider import ProviderToolResult

TASK_STATUS_TERMS = (
    "a fazer",
    "em andamento",
    "servico feito",
    "aguardando cliente",
    "concluido",
)
UNAVAILABLE_OPERATION_PATTERN = re.compile(
    r"\b(pagamento|financeiro|conta paga|pag(?:ar|ue)(?: a)? conta|nota fiscal|emitir nota|"
    r"enviar (?:e-mail|email|mensagem)|excluir|apagar)\b"
)
SERVICE_OPERATION_PATTERN = re.compile(
    r"\b(?:registr\w*|cadastr\w*|salv\w*|anot\w*|consult\w*|mostr\w*|list\w*|verific\w*)\b"
    r".{0,80}\b(?:atendimentos?|servicos?|chamados?)\b"
)
EMAIL_READ_QUERY_PATTERN = re.compile(
    r"\b(?:e[- ]?mails?|emails?|mensagens?|caixa(?: de entrada)?|inbox)\b"
    r"|\b(?:o que chegou|o que recebi|quem (?:esta )?(?:esperando|aguardando)|"
    r"ficou alguem esperando|ficou alguem aguardando)\b"
)
EMAIL_WRITE_COMMAND_PATTERN = re.compile(
    r"^\s*(?:pague|marque|emita|envie|exclua|apague|mova|altere|baixe|"
    r"registre|crie|movimente)\b"
)
SERVICE_TOOLS = frozenset(
    {"consultar_servicos", "registrar_evento_servico", "corrigir_registro_servico", "criar_lembretes_servico"}
)
def _validate_conversation_grounding(
    command: AssistantCommand,
    *,
    tool_results: Sequence[ProviderToolResult],
    latest_assistant: str = "",
    latest_email_evidence: str = "",
    current_message: str = "",
) -> AssistantCommand:
    if not isinstance(command, ConversationCommand):
        return command
    internal_markers = (
        "HISTORICO_JSON=",
        "CAPACIDADES_JSON=",
        "ULTIMA_RESPOSTA_ASSISTENTE=",
        "ACAO_PENDENTE_JSON=",
        "RESULTADOS_FERRAMENTAS_JSON=",
        "PEDIDO_ATUAL=",
        "INSTRUCAO_DE_SAIDA=",
    )
    if any(marker in command.message for marker in internal_markers):
        raise ValueError("A resposta expos o envelope interno de contexto.")
    normalized_request = normalize_text(current_message)
    normalized_answer = normalize_text(command.message)
    historical_email_label = bool(
        latest_email_evidence
        and re.search(
            r"\b(?:resultado|consulta|mensagens?|e[- ]?mails?)\s+(?:anterior|anteriores)\b|"
            r"\bapresentad[oa]s? anteriormente\b",
            normalized_answer,
        )
    )
    validate_execution_claims(
        command.message,
        tool_results=tool_results,
        allow_historical_email_claim=historical_email_label,
    )
    requests_board_facts = (
        any(term in normalized_request for term in ("tarefa", "pendencia", "quadro", "prazo"))
        and any(
            term in normalized_request
            for term in ("analise", "consulte", "mostre", "liste", "qual", "recomende", "tenho")
        )
    )
    asserts_board_state = any(
        term in normalized_answer
        for term in (
            "nao ha tarefa",
            "nao ha pendencia",
            "nenhuma tarefa",
            "pendencias registradas",
            "tarefas registradas",
        )
    )
    if requests_board_facts and asserts_board_state and not tool_results:
        raise ValueError("A resposta alegou estado do quadro sem consulta real.")
    using_historical_email_source = False
    if tool_results:
        source = json.dumps(
            [result.model_dump(mode="json") for result in tool_results],
            ensure_ascii=False,
        ).casefold()
    elif latest_assistant.startswith("Encontrei estas tarefas:"):
        source = latest_assistant.casefold()
    elif (
        "Mensagens exibidas nesta resposta:" in latest_email_evidence
        and references_prior_email_context(current_message)
    ):
        source = latest_email_evidence.casefold()
        using_historical_email_source = True
        if not historical_email_label:
            raise ValueError("Fatos historicos de e-mail devem ser identificados como resultado anterior.")
    else:
        return command
    answer = command.message.casefold()
    unsupported_consequences = (
        "compromet",
        "impact",
        "gerar inconsist",
        "agrav",
        "prejudic",
        "garant",
        "risco",
        "consequenc",
        "essencial",
        "falha",
        "afet",
        "urgenc",
        "necessidade de",
        "inacabad",
        "imediat",
    )
    has_task_tool_results = any(result.tool == "consultar_tarefas" for result in tool_results)
    has_email_tool_results = any(result.tool == "consultar_emails" for result in tool_results)
    if has_task_tool_results:
        sentences = re.split(r"(?<=[.!?])\s+", command.message.strip())
        grounded_sentences: list[str] = []
        grounding_adjusted = False
        for sentence in sentences:
            candidate = sentence
            def unsafe(value: str) -> bool:
                return any(
                    term in value.casefold() and term not in source
                    for term in unsupported_consequences
                )

            if unsafe(candidate):
                for marker in (", o que", ", pois isso", " para garantir", " para evitar"):
                    prefix, separator, _suffix = candidate.partition(marker)
                    if separator and prefix.strip() and not unsafe(prefix):
                        candidate = prefix.rstrip(" ,;:") + "."
                        grounding_adjusted = True
                        break
            if not unsafe(candidate):
                grounded_sentences.append(candidate)
            else:
                grounding_adjusted = True
        if not grounded_sentences:
            raise ValueError("A resposta inventou consequencia para uma tarefa consultada.")
        if grounding_adjusted:
            command = command.model_copy(update={"message": " ".join(grounded_sentences)})
            answer = command.message.casefold()
    source_dates = set(re.findall(r"\b\d{2}/\d{2}/\d{4}\b", source))
    source_dates.update(
        f"{day}/{month}/{year}"
        for year, month, day in re.findall(
            r"\b(\d{4})-(\d{2})-(\d{2})(?=[Tt]|[\s\",}])", source
        )
    )
    answer_dates = set(re.findall(r"\b\d{2}/\d{2}/\d{4}\b", answer))
    for service_result in tool_results:
        if service_result.tool == "consultar_servicos" and service_result.state in {"success", "empty"}:
            _validate_service_facts(command.message, service_result.payload)
    source_ids = set(re.findall(r'(?:(?:"id":\s*)|#)(\d+)', source))
    answer_ids = set(re.findall(r"#(\d+)", answer))
    source_statuses = {status for status in TASK_STATUS_TERMS if status in source}
    answer_statuses = {status for status in TASK_STATUS_TERMS if status in answer}
    if not answer_dates.issubset(source_dates):
        raise ValueError("A resposta conversacional inventou uma data de tarefa.")
    if not answer_ids.issubset(source_ids):
        raise ValueError("A resposta conversacional inventou um identificador de tarefa.")
    if not answer_statuses.issubset(source_statuses):
        raise ValueError("A resposta conversacional alterou o status consultado.")
    if "oficial" in answer and "oficial" not in source:
        raise ValueError("A resposta conversacional inventou uma qualificacao de e-mail.")
    if has_email_tool_results or using_historical_email_source:
        _validate_email_facts(command.message, source)
    return command


def _validate_service_facts(message: str, payload: dict[str, object]) -> None:
    """Check explicit claims tied to a shown service-call id against its result."""

    normalized = normalize_text(message)
    calls = payload.get("service_calls", [])
    if not isinstance(calls, list):
        return
    answer_refs: list[tuple[dict[str, object], str]] = []
    for sentence in re.split(r"(?<=[.!?])\s+", normalized):
        id_match = re.search(r"#(\d+)\b", sentence)
        call = None
        if id_match:
            call = next((row for row in calls if isinstance(row, dict) and row.get("id") == int(id_match.group(1))), None)
            if call is None:
                raise ValueError("A resposta citou um chamado que nao consta na consulta.")
        else:
            name_matches = [row for row in calls if isinstance(row, dict)
                            and normalize_text(str(row.get("client", "")))
                            and normalize_text(str(row.get("client", ""))) in sentence]
            if len(name_matches) == 1:
                call = name_matches[0]
            elif len(calls) == 1 and isinstance(calls[0], dict):
                call = calls[0]
        if call is not None:
            answer_refs.append((call, sentence))
    for call, nearby in answer_refs:
        execution_status = call.get("execution_status")
        if re.search(r"\b(?:execucao|servico|reparo)\b.{0,35}\b(?:concluid[oa]|finalizad[oa]|em andamento|nao iniciad[oa])\b", nearby):
            expected = {
                "completed": r"\b(?:concluid[oa]|finalizad[oa])\b",
                "in_progress": r"\bem andamento\b",
                "not_started": r"\bnao iniciad[oa]\b",
            }.get(str(execution_status))
            if expected is None or not re.search(expected, nearby):
                raise ValueError("A resposta contradiz a situacao tecnica consultada do chamado.")
        if re.search(r"\b(?:chamado|administrativamente)\b.{0,35}\b(?:encerrad[oa]|abert[oa])\b", nearby):
            expected_admin = "encerrad" if call.get("administrative_status") == "closed" else "abert"
            if expected_admin not in nearby:
                raise ValueError("A resposta contradiz a situacao administrativa consultada do chamado.")
        step_rows = call.get("workflow_steps", [])
        if not isinstance(step_rows, list):
            continue
        step_names = {
            "report": ("relatorio", "report"),
            "proposal": ("proposta", "proposal"),
            "proposal_sent": ("proposta enviada", "proposal_sent"),
            "invoice": ("nota fiscal", "invoice"),
            "receipt": ("recebimento", "receipt"),
        }
        status_claims = {
            "pending": ("pendente", "falta"),
            "waiting_customer": ("aguardando cliente", "aguardando aprovacao", "esperando cliente"),
            "completed": ("concluida", "concluido", "finalizada", "finalizado"),
            "not_applicable": ("dispensada", "dispensado", "nao aplicavel"),
            "unknown": ("nao informada", "nao informado", "desconhecida"),
        }
        for row in step_rows:
            if not isinstance(row, dict):
                continue
            kind = str(row.get("step_type"))
            status = str(row.get("status"))
            names = step_names.get(kind, ())
            if not names or not any(name in nearby for name in names):
                continue
            mentioned = [word for words in status_claims.values() for word in words if word in nearby]
            if mentioned and not any(word in nearby for word in status_claims.get(status, ())):
                raise ValueError("A resposta contradiz o estado administrativo consultado do chamado.")
        event_types = call.get("event_types", [])
        if not isinstance(event_types, list):
            event_types = []
        inspection_claims = bool(re.search(
            r"\b(?:inspecao|vistoria)\b.{0,70}\b(?:realizada|realizado|feita|feito|ocorreu|"
            r"executada|executado|iniciada|iniciado|nao iniciada|nao iniciado|"
            r"nao foi realizada|nao foi realizado|nao foi feita|nao foi feito|"
            r"nao foi executada|nao foi executado|nao aconteceu|nao ocorreu)\b", nearby,
        ))
        inspection_negative = bool(re.search(
            r"\b(?:inspecao|vistoria)\b.{0,70}\b(?:nao iniciada|nao iniciado|nao comecou|"
            r"nao foi realizada|nao foi realizado|nao foi feita|nao foi feito|nao foi executada|"
            r"nao foi executado|nao aconteceu|nao ocorreu)\b", nearby,
        ))
        if inspection_claims and inspection_negative and "inspection" in event_types:
            raise ValueError("A resposta contradiz o evento de inspecao registrado.")
        if inspection_claims and not inspection_negative and "inspection" not in event_types:
            raise ValueError("A resposta afirmou inspecao sem evento correspondente no historico.")


def _validate_email_facts(message: str, source: str) -> None:
    normalized_source = normalize_text(source)
    for quoted in re.findall(r'["“]([^"”]{2,500})["”]', message):
        if normalize_text(quoted) not in normalized_source:
            raise ValueError("A resposta de e-mail inventou um assunto ou trecho citado.")
    for email_address in re.findall(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", message):
        if email_address.casefold().rstrip(".,;:") not in source.casefold():
            raise ValueError("A resposta de e-mail inventou um endereco.")
    for amount in re.findall(r"R\$\s*\d[\d.]*,\d{2}", message, flags=re.IGNORECASE):
        if amount.casefold().replace(" ", "") not in source.casefold().replace(" ", ""):
            raise ValueError("A resposta de e-mail inventou um valor.")

    common_capitalized = {
        "a", "ao", "as", "com", "de", "do", "e", "em", "este", "esta", "esse", "essa",
        "foram", "foi", "ha", "hoje", "na", "nao", "no", "o", "os", "pela", "pelo",
        "por", "primeiro", "resultado", "segundo", "tambem", "um", "uma",
    }
    for match in re.finditer(
        r"(?<![\w@])([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][\wÀ-ÿ-]{2,}(?:\s+(?:da|de|do|dos|das|-)?\s*"
        r"[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][\wÀ-ÿ-]{2,})*)",
        message,
    ):
        phrase = match.group(1)
        normalized_phrase = normalize_text(phrase).strip()
        if normalized_phrase in common_capitalized:
            continue
        preceding = normalize_text(message[max(0, match.start() - 24) : match.start()])
        capitalized_words = re.findall(r"[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][\wÀ-ÿ-]{2,}", phrase)
        if len(capitalized_words) == 1 and not re.search(
            r"\b(?:por|de|da|do|empresa|remetente)\s*$", preceding
        ):
            continue
        if normalized_phrase not in normalized_source:
            raise ValueError("A resposta de e-mail inventou remetente, empresa ou entidade.")


def _validate_tool_scope(
    command: AssistantCommand,
    *,
    current_message: str,
    allowed_tools: set[str] | None = None,
    tool_results: Sequence[ProviderToolResult] = (),
) -> AssistantCommand:
    normalized_request = normalize_text(current_message)
    unavailable_request = UNAVAILABLE_OPERATION_PATTERN.search(normalized_request)
    service_request = SERVICE_OPERATION_PATTERN.search(normalized_request)
    email_read_query = bool(
        EMAIL_READ_QUERY_PATTERN.search(normalized_request)
        and not EMAIL_WRITE_COMMAND_PATTERN.search(normalized_request)
        and re.search(
            r"\b(?:quais?|tem|o que|me diga|mostre|resuma|resume|leia|quem|ficou|"
            r"cheg\w*|receb\w*|urgente|prioridade|esperando|aguardando)\b",
            normalized_request,
        )
    )
    explicit_task_request = bool(
        re.search(
            r"\b(?:crie|criar|adicione|adicionar|registre|registrar)\s+"
            r"(?:(?:uma?|um)\s+)?(?:tarefa|lembrete)\b",
            normalized_request,
        )
    )
    if isinstance(command, TaskCreateCommand) and (unavailable_request or service_request) and not explicit_task_request:
        raise ValueError("Uma operacao indisponivel nao pode ser convertida em tarefa.")
    if isinstance(command, ConversationCommand):
        normalized_reply = normalize_text(command.message)
        future_creation = re.search(
            r"\btarefas?\b.{0,80}\b(?:sera|serao|vai ser|vao ser)\s+criad[ao]s?\b",
            normalized_reply,
        )
        if future_creation and "nao sera criad" not in normalized_reply:
            raise ValueError("A resposta prometeu uma criacao ainda nao executada.")
        states_limitation = re.search(
            r"\b(?:ainda )?nao (?:posso|consigo|cadastro|registro|executo|esta disponivel|tenho suporte)\b|"
            r"\bindisponivel\b",
            normalized_reply,
        )
        service_tools_available = bool(allowed_tools and SERVICE_TOOLS.intersection(allowed_tools))
        service_query_succeeded = any(
            result.tool == "consultar_servicos" and result.state in {"success", "empty"}
            for result in tool_results
        )
        unavailable_needs_limit = bool(unavailable_request) and not email_read_query
        service_needs_limit = bool(
            service_request
            and not service_tools_available
            and not service_query_succeeded
            and not email_read_query
        )
        if (unavailable_needs_limit or service_needs_limit) and not states_limitation:
            raise ValueError("A resposta omitiu a limitacao da funcao solicitada.")
    return command


def _repair_reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "schema_validation"
    if isinstance(exc, (KeyError, TypeError, json.JSONDecodeError)):
        return "malformed_response"
    message = str(exc).casefold()
    if "envelope interno" in message:
        return "internal_context_exposure"
    if "estado do quadro sem consulta" in message:
        return "ungrounded_task_claim"
    if "fatos historicos de e-mail" in message:
        return "unlabeled_historical_email_evidence"
    if "inventou consequencia" in message:
        return "unsupported_task_consequence"
    if "estado de tarefa sem consulta" in message:
        return "unqueried_task_state"
    if "inspecao sem evento correspondente" in message:
        return "ungrounded_service_event"
    if "contradiz o evento de inspecao" in message:
        return "service_event_conflict"
    if ("contradiz a situacao" in message or "contradiz o estado administrativo" in message
            or "contradiz a consulta de servicos" in message or "status consultado" in message):
        return "service_projection_conflict"
    if "chamado que nao consta" in message or "evento de servico sem evidencia" in message:
        return "ungrounded_service_event"
    if "consulta de servico sem evidencia" in message or "consulta de servico que falhou" in message:
        return "ungrounded_service_query"
    if "inventou uma data de tarefa" in message or "inventou um identificador de tarefa" in message:
        return "ungrounded_fact"
    if "inventou" in message or "status consultado" in message:
        return "ungrounded_task_fact"
    if "servic" in message:
        if "vazi" in message or "encontrad" in message or "quantidade" in message:
            return "service_result_conflict"
        if "inspec" in message or "evento" in message:
            return "service_event_conflict"
        if "status" in message or "estado" in message or "situacao" in message:
            return "service_projection_conflict"
        if "registr" in message or "execut" in message:
            return "unconfirmed_service_action"
        if "consulta" in message or "consult" in message:
            return "ungrounded_service_query"
        return "ungrounded_service_fact"
    if "tarefa" in message or "quadro" in message:
        return "unqueried_task_state"
    if "discriminador" in message or "ferramenta" in message or "tool" in message:
        return "tool_scope_violation"
    if "nao permitida" in message or "indisponivel" in message or "operacao" in message:
        return "scope_violation"
    if "no maximo uma ferramenta" in message:
        return "multiple_tool_calls"
    return "validation_rejected"


def _repair_hint(
    reason: str | None,
    tool_results: Sequence[ProviderToolResult] = (),
) -> str:
    if reason == "service_event_conflict":
        return (
            " O historico consultado confirma evento de inspecao. Nao confunda a ausencia de execucao "
            "com ausencia de visita/inspecao; corrija a frase usando os eventos do chamado."
        )
    if reason == "service_projection_conflict":
        return " Use exatamente a situacao tecnica ou administrativa retornada na consulta do chamado."
    if reason == "ungrounded_service_query":
        return " A consulta foi executada: use o resultado real e nao diga que nao foi consultado ou que houve falha."
    if reason == "service_result_conflict":
        result = next((item for item in tool_results if item.tool == "consultar_servicos"), None)
        count = result.payload.get("count") if result is not None else None
        if isinstance(count, int):
            return (
                f" A consulta real retornou {count} chamado(s). Nao diga que nao encontrou nenhum nem que a lista esta vazia; "
                "responda sobre o(s) registro(s) que aparecem nos dados."
            )
        return " Nao contradiga a quantidade ou o resultado da consulta; descreva apenas os chamados retornados."
    if reason == "unconfirmed_service_action":
        return " A consulta nao registrou nem executou nada. Remova alegacoes de gravacao, conclusao ou mudanca."
    if reason == "ungrounded_service_fact":
        return " Remova fatos de servico que nao aparecem nos chamados e eventos retornados."
    if reason == "ungrounded_fact":
        return " Remova datas e identificadores que nao aparecam literalmente nos resultados consultados."
    if reason == "unqueried_task_state":
        return (
            " Voce consultou chamados, nao tarefas. Remova qualquer afirmacao sobre tarefas, rascunhos "
            "ou quadro; nao afirme que existem nem que nao existem."
        )
    if reason == "response_grounding_rejected":
        return (
            " Corrija a resposta usando somente cliente, chamado, eventos e etapas que aparecem em "
            "RESULTADOS_FERRAMENTAS_JSON. Nao deduza fatos ausentes, nao fale de tarefas sem consulta "
            "ao quadro e nao contradiga os estados retornados. Se faltar base, diga isso explicitamente."
        )
    if reason == "tool_scope_rejected":
        return " Use somente uma ferramenta autorizada nesta rodada ou responda sem alegar execucao."
    if reason == "command_schema_rejected":
        return " Gere o formato estruturado exato, sem campos extras, ou uma resposta conversacional valida."
    if reason in {"ungrounded_task_claim", "ungrounded_task_fact"}:
        return " Remova a afirmacao de tarefa sem fonte ou use somente os dados de consultar_tarefas."
    if reason == "ungrounded_service_event":
        return " Nao afirme uma visita ou inspecao sem evento correspondente; use somente o historico retornado."
    return " Reescreva apenas com afirmacoes comprovadas pelos resultados desta solicitacao."
