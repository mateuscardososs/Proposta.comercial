from __future__ import annotations

import re

from app.assistant.contracts import EmailQueryCommand, TaskQueryCommand
from app.assistant.dates import normalize_text


def ground_task_query(message: str, command: TaskQueryCommand) -> TaskQueryCommand:
    normalized = normalize_text(message)
    priority_cues = (
        "prioridade",
        "priorizar",
        "primeiro",
        "por onde comecar",
        "por onde começo",
        "recomende",
        "recomendacao",
    )
    if not command.priorities and any(cue in normalized for cue in priority_cues):
        return command.model_copy(update={"priorities": True})
    return command



def ground_email_query(message: str, command: EmailQueryCommand) -> EmailQueryCommand:
    normalized = normalize_text(message)
    updates: dict[str, object] = {}
    general_listing = any(
        cue in normalized
        for cue in (
            "quais e-mails",
            "quais emails",
            "chegaram",
            "recebi",
            "resume",
            "resuma",
        )
    )
    if command.attention_only and general_listing:
        updates["attention_only"] = False
    if "esta semana" in normalized or "desta semana" in normalized:
        updates["period"] = "week"
    elif "hoje" in normalized:
        updates["period"] = "today"
    if any(cue in normalized for cue in ("nao li", "não li", "nao lidos", "não lidos")):
        updates["unread_only"] = True
    if "esperando minha resposta" in normalized or "resposta pendente" in normalized:
        updates["awaiting_reply"] = True
    return command.model_copy(update=updates) if updates else command



def direct_email_query(message: str) -> EmailQueryCommand | None:
    normalized = normalize_text(message)
    words = " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())
    explicit_email_scope = bool(
        re.search(
            r"\b(?:e ?mails?|caixa(?: de entrada)?|inbox|mensagens?|correio)\b",
            words,
        )
    )
    other_scope = bool(
        re.search(
            r"\b(?:quadro|tarefas?|oficina|entrega|encomenda|materiais?|pecas?|equipamentos?)\b",
            words,
        )
    )
    if other_scope and not explicit_email_scope:
        return None

    category: str | None = None
    if re.search(
        r"\b(?:cotacao recebida|cotacao do fornecedor|fornecedor.{0,30}cotacao)\b",
        words,
    ):
        category = "vendor_quotation"
    elif re.search(r"\b(?:orcamento|cotacao)\b", words) and re.search(
        r"\b(?:pedido|solicitacao|pedem|pedindo|solicito|solicitamos|orcamento|cotacao)\b",
        words,
    ):
        category = "customer_quote_request"
    elif re.search(r"\b(?:ordem de compra|pedido de compra|purchase order)\b", words):
        category = "purchase_order"
    elif re.search(
        r"\b(?:emitir|emissao|enviar|envio).{0,35}\bnota fiscal\b|"
        r"\bsolicitacao.{0,30}\bnota fiscal\b",
        words,
    ):
        category = "invoice_request"
    elif re.search(
        r"\b(?:nota fiscal recebida|recebi.{0,30}nota fiscal|nf e recebida|nfe recebida)\b",
        words,
    ):
        category = "invoice_received"
    elif re.search(r"\b(?:conta a pagar|contas a pagar|boleto|fatura para pagamento)\b", words):
        category = "accounts_payable"
    elif re.search(r"\b(?:conta a receber|cobranca|cobrar cliente|cobranca pendente)\b", words):
        category = "accounts_receivable"
    elif re.search(r"\b(?:comprovante de pagamento|comprovante pix)\b", words):
        category = "payment_proof"
    elif re.search(r"\b(?:chamado|solicitacao de servico|pedido de atendimento)\b", words):
        category = "service_request"

    awaiting_reply = bool(
        re.search(
            r"\b(?:alguem|quem|conversas?|mensagens?)\b.{0,45}"
            r"\b(?:esperando|aguardando)\b.{0,25}\b(?:meu retorno|minha resposta)\b|"
            r"\b(?:respostas? pendentes?|falta responder|devo resposta|precisam? (?:do )?meu retorno)\b",
            words,
        )
    )
    unread_phrase = bool(
        re.search(
            r"\b(?:ainda nao (?:li|vi)|nao (?:li|vi)|nao lidas?|por ler)\b",
            words,
        )
    )
    indirect_unread_question = bool(re.search(r"\b(?:o que|quais?) (?:eu )?ainda nao (?:li|vi)\b", words))
    unread_only = unread_phrase and (explicit_email_scope or indirect_unread_question)
    arrived_today = bool(
        re.search(
            r"\b(?:o que chegou hoje|chegou algo hoje|algo chegou hoje|"
            r"o que recebi hoje|recebi algo hoje)\b",
            words,
        )
    )
    arrived_week = bool(
        re.search(
            r"\b(?:o que|quais?)\s+(?:cheg\w*|receb\w*)\b.{0,45}"
            r"\b(?:esta|nesta|essa|na) semana\b",
            words,
        )
    )
    attention_only = bool(
        re.search(
            r"\b(?:urgente|prioridade|precis(?:o|a|e) resolver|precis(?:o|a|e) de atencao|"
            r"merece atencao)\b",
            words,
        )
    )
    explicit_query = explicit_email_scope and bool(
        re.search(
            r"\b(?:tem|quais?|o que|cheg|receb|resum|ler|leia|vi|lidas?|"
            r"urgente|prioridade|resolver|atencao|esperando|aguardando|resposta|retorno)\w*\b",
            words,
        )
    )
    category_question = category is not None and bool(
        explicit_email_scope or re.search(r"\b(?:chegou|recebi|recebidos?|caixa)\b", words)
    )
    if not any(
        (
            explicit_query,
            awaiting_reply,
            unread_only,
            arrived_today,
            arrived_week,
            category_question,
        )
    ):
        return None

    period = "today" if "hoje" in words else "week"
    return EmailQueryCommand(
        period=period,
        unread_only=unread_only,
        attention_only=attention_only,
        awaiting_reply=awaiting_reply,
        category=category,
    )



def direct_document_query(message: str) -> bool:
    normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", normalize_text(message)).split())
    refers_to_document = any(
        term in normalized.split()
        for term in (
            "proposta",
            "propostas",
            "documento",
            "documentos",
            "arquivo",
            "arquivos",
            "relatorio",
            "relatorios",
            "pdf",
            "docx",
        )
    ) or "no arquivo" in normalized or "na proposta" in normalized
    asks_about_content = any(
        re.search(rf"\b{re.escape(cue)}\b", normalized)
        for cue in (
            "qual",
            "quanto",
            "o que",
            "como",
            "quais",
            "me diga",
            "me fale",
            "o que consta",
            "o que diz",
            "informa",
            "menciona",
            "mencione",
            "fala",
            "especifica",
            "contem",
            "explica",
            "aborda",
            "indica",
            "resuma",
            "resume",
            "compare",
            "procure",
            "busque",
            "pesquise",
            "consulte",
            "verifique",
        )
    )
    return refers_to_document and asks_about_content



def direct_board_query(message: str) -> bool:
    normalized = normalize_text(message)
    asks_for_agenda = any(
        term in normalized
        for term in (
            "organize",
            "organizar",
            "planeje",
            "planejar",
            "priorize",
            "priorizar",
            "o que devo fazer",
            "o que tenho para fazer",
            "o que posso fazer",
            "por onde comecar",
            "o que fazer primeiro",
            "recomende",
            "recomendacao",
            "prioridade",
        )
    )
    asks_to_consult = any(
        term in normalized
        for term in (
            "olhe",
            "olhar",
            "veja",
            "verifique",
            "consulte",
            "consultar",
            "mostre",
            "mostrar",
            "liste",
            "listar",
            "quais tarefas",
            "minhas tarefas abertas",
            "quadro de tarefas",
            "quais sao as tarefas",
        )
    )
    has_agenda_scope = "agenda" in normalized
    has_task_scope = any(term in normalized for term in ("quadro", "tarefas", "tarefa", "pendencias", "pendencia"))
    asks_about_today = "hoje" in normalized and any(
        term in normalized for term in ("fazer", "tarefas", "tarefa", "quadro")
    )
    return bool(
        (has_agenda_scope and (asks_for_agenda or asks_to_consult))
        or (has_task_scope and (asks_for_agenda or asks_to_consult or asks_about_today))
        or (asks_about_today and asks_for_agenda)
    )



def direct_daily_brief_request(message: str) -> bool:
    normalized = normalize_text(message)
    normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())
    asks_for_brief = any(
        phrase in normalized
        for phrase in (
            "o que preciso fazer hoje",
            "o que tenho que fazer hoje",
            "o que tenho para fazer hoje",
            "o que devo fazer hoje",
            "o que fazer hoje",
            "resumo operacional de hoje",
            "resumo de hoje",
            "resuma meu dia",
            "resumo do meu dia",
            "prioridades de hoje",
            "agenda de hoje",
            "organize minha agenda",
            "organizar minha agenda",
            "planeje meu dia",
            "planejar meu dia",
            "minha agenda de hoje",
        )
    )
    greeting_and_today = bool(
        re.search(r"\b(?:bom dia|boa tarde|boa noite)\b", normalized)
        and "hoje" in normalized
        and re.search(r"\b(?:preciso|devo|tenho|agenda|fazer|organize|resumo)\b", normalized)
    )
    return asks_for_brief or greeting_and_today



def direct_service_return_query(message: str) -> bool:
    normalized = normalize_text(message)
    asks_for_list = bool(
        re.search(
            r"\b(?:quais|tem|existe|liste|listar|mostre|mostrar|preciso saber|o que)\b",
            normalized,
        )
    )
    return asks_for_list and bool(
        re.search(
            r"\b(?:retorno|retornos)\b.{0,80}\b(?:servico|servicos|chamado|chamados|pendente|precis|agendad)",
            normalized,
        )
        or re.search(
            r"\b(?:servico|servicos|chamado|chamados)\b.{0,80}\b(?:retorno|retornos|voltar|retornar)\b",
            normalized,
        )
    )



def direct_service_report_request(message: str) -> bool:
    normalized = normalize_text(message)
    if re.search(r"\b(?:tarefa|lembrete|quadro)\b", normalized):
        return False
    mentions_report = bool(
        re.search(r"\b(?:relatorio tecnico|laudo tecnico)\b", normalized)
        or re.search(
            r"\brelatorio\b.{0,80}\b(?:servico|chamado|atendimento|execucao|concluido)\b",
            normalized,
        )
        or re.search(
            r"\b(?:servico|chamado|atendimento|execucao|concluido)\b.{0,80}\brelatorio\b",
            normalized,
        )
    )
    asks_for_report = bool(
        re.search(
            r"\b(?:gere|gerar|gera|prepare|preparar|faca|fazer|monta|montar|quero|preciso|crie|criar)\b",
            normalized,
        )
    )
    return mentions_report and asks_for_report



def direct_service_report_correction(message: str) -> bool:
    normalized = normalize_text(message)
    return bool(
        re.search(
            r"\b(?:corrig\w*|altere|alterar|troque|trocar|mude|mudar|substitua|substituir|ajuste|ajustar)\b",
            normalized,
        )
    )



def direct_schedule_save_request(message: str) -> bool:
    normalized = normalize_text(message)
    asks_to_save = any(verb in normalized for verb in ("salve", "salvar", "grave", "gravar", "registre"))
    refers_to_schedule = any(subject in normalized for subject in ("agenda", "plano do dia", "blocos de horario"))
    return asks_to_save and refers_to_schedule



def message_mentions_date(message: str) -> bool:
    normalized = normalize_text(message)
    relative_terms = (
        "hoje",
        "amanha",
        "dia seguinte",
        "esta semana",
        "nesta semana",
        "fim da semana",
        "segunda",
        "terca",
        "quarta",
        "quinta",
        "sexta",
        "sabado",
        "domingo",
        "sem prazo",
    )
    return any(term in normalized for term in relative_terms) or bool(
        re.search(
            r"\b(?:em|daqui a)\s+\d{1,3}\s+dias?\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{4}-\d{2}-\d{2}\b",
            normalized,
        )
    )
