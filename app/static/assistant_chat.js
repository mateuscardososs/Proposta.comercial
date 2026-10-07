export class AssistantChatController {
  constructor(options) {
    this.options = options;
    this.timeoutMs = options.timeoutMs ?? 95000;
    this.busy = false;
    this.pending = null;
  }

  async send(message, { retry = false, source = "text" } = {}) {
    const cleanMessage = String(message || "").trim();
    if (!cleanMessage) throw new Error("Digite uma mensagem antes de enviar.");
    if (this.busy) throw new Error("O assistente ainda está processando a solicitação anterior.");

    const attempt = retry && this.pending
      ? this.pending
      : { message: cleanMessage, requestId: this.options.makeRequestId(), source };
    if (!retry) this.options.onUserMessage?.(attempt.message);
    this.pending = attempt;
    this.options.onRetryAvailable?.(false);
    this._setBusy(true);

    const abortController = new AbortController();
    const timeout = setTimeout(() => abortController.abort(), this.timeoutMs);
    try {
      const response = await this.options.fetchImpl("/api/assistant/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: attempt.message,
          request_id: attempt.requestId,
          conversation_id: this.options.getConversationId?.() ?? null,
          retry: Boolean(retry),
          source: attempt.source,
        }),
        signal: abortController.signal,
      });
      const payload = await responseJson(response);
      if (!payload || typeof payload.message !== "string" || !payload.message.trim()) {
        throw new Error("O assistente retornou uma resposta vazia.");
      }
      if (!Number.isInteger(payload.conversation_id) || payload.conversation_id < 1) {
        throw new Error("O assistente retornou uma conversa inválida.");
      }
      this.options.setConversationId?.(payload.conversation_id);
      this.options.onAssistantMessage?.(payload);
      if (payload.kind === "error" && payload.retryable === true) {
        this.pending = attempt;
        this.options.onRetryAvailable?.(true);
      } else {
        this.pending = null;
      }
      return payload;
    } catch (error) {
      const safeError = error?.name === "AbortError"
        ? new Error("O assistente demorou para responder. Tente novamente; a mesma solicitação será reconciliada sem duplicar tarefas.")
        : error instanceof Error ? error : new Error(String(error));
      this.options.onAssistantMessage?.({ kind: "error", message: safeError.message });
      this.options.onRetryAvailable?.(true);
      throw safeError;
    } finally {
      clearTimeout(timeout);
      this._setBusy(false);
    }
  }

  retry() {
    if (!this.pending) throw new Error("Não há uma solicitação para tentar novamente.");
    return this.send(this.pending.message, { retry: true, source: this.pending.source });
  }

  _setBusy(value) {
    this.busy = value;
    this.options.onBusy?.(value);
  }
}


export async function responseJson(response) {
  let payload;
  try {
    const raw = await response.text();
    payload = raw ? JSON.parse(raw) : null;
  } catch (_error) {
    throw new Error("O servidor retornou uma resposta inválida.");
  }
  if (!response.ok) {
    throw new Error(payload?.detail || "A operação não foi concluída.");
  }
  return payload;
}


export async function fetchWithTimeout(fetchImpl, url, options = {}, timeoutMs = 95000) {
  const abortController = new AbortController();
  const timeout = setTimeout(() => abortController.abort(), timeoutMs);
  try {
    return await fetchImpl(url, { ...options, signal: abortController.signal });
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error("A operação demorou demais. Tente novamente.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}


export function bootstrapAssistantChat(root = document) {
  const form = root.getElementById("assistant-form");
  if (!form) return null;
  const input = root.getElementById("assistant-message");
  const send = root.getElementById("assistant-send");
  const history = root.getElementById("assistant-history");
  const empty = root.getElementById("assistant-empty");
  const status = root.getElementById("assistant-status");
  const retryButton = root.getElementById("assistant-retry");
  const initialConversation = new URLSearchParams(window.location.search).get("conversation_id");
  let conversationId = initialConversation ? Number(initialConversation) : null;

  function makeRequestId() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return `assistant-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function setBusy(value, text = "") {
    input.disabled = value;
    send.disabled = value;
    status.textContent = value ? (text || "Consultando o assistente local...") : "";
    status.classList.toggle("is-busy", value);
  }

  function updateConversation(id) {
    conversationId = id;
    const url = new URL(window.location.href);
    url.searchParams.set("conversation_id", String(id));
    window.history.replaceState({}, "", url);
  }

  function appendMessage(role, content, kind = "text", details = {}) {
    empty?.remove();
    const article = document.createElement("article");
    article.className = `assistant-message ${role}${kind === "error" || kind === "success" ? ` ${kind}` : ""}`;
    if (!article.dataset) article.dataset = {};
    article.dataset.messageRole = role;
    article.dataset.responseKind = kind;
    const label = document.createElement("span");
    label.className = "assistant-message-label";
    label.textContent = role === "user" ? "Você" : "Assistente";
    const text = document.createElement("span");
    text.textContent = content;
    article.append(label, text);

    if (kind === "confirmation" && details.action_id && details.confirmation_token) {
      const controls = document.createElement("div");
      controls.className = "assistant-confirm-actions";
      const confirm = document.createElement("button");
      confirm.type = "button";
      confirm.className = "btn btn-primary";
      confirm.textContent = details.report_fields ? "Confirmar e gerar DOCX/PDF" : "Confirmar";
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "btn btn-ghost";
      cancel.textContent = "Cancelar";
      confirm.addEventListener("click", () => runAction(details, "confirm", controls));
      cancel.addEventListener("click", () => runAction(details, "cancel", controls));
      controls.append(confirm, cancel);
      article.appendChild(controls);
    }
    if (Array.isArray(details.report_candidates) && details.report_candidates.length) {
      const list = document.createElement("div");
      list.className = "assistant-confirm-actions";
      for (const candidate of details.report_candidates) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-ghost";
        button.textContent = `Preparar chamado #${candidate.id} · ${candidate.client || "Cliente não informado"} · ${candidate.summary || "Sem resumo"}`;
        button.addEventListener("click", () => controller.send(
          `Prepare o relatório técnico do chamado #${candidate.id}`,
        ));
        list.appendChild(button);
      }
      article.appendChild(list);
    }
    if (details.action_id && details.confirmation_token && details.report_fields) {
      const form = document.createElement("form");
      form.className = "assistant-report-preview";
      const missing = new Set(details.report_missing_fields || []);
      for (const [field, value] of Object.entries(details.report_fields)) {
        const label = document.createElement("label");
        label.className = missing.has(field) ? "assistant-report-missing" : "";
        const caption = document.createElement("span");
        caption.textContent = `${details.report_field_labels?.[field] || field}${missing.has(field) ? " · revisar (sem informação registrada)" : ""}`;
        const input = document.createElement("textarea");
        input.name = field;
        input.dataset.reportField = field;
        input.value = value || "";
        input.rows = field === "client_address" || ["reported_problem", "analysis", "work_performed", "verification_result"].includes(field) ? 3 : 1;
        label.append(caption, input);
        form.appendChild(label);
      }
      const update = document.createElement("button");
      update.type = "submit";
      update.className = "btn btn-ghost";
      update.textContent = "Atualizar prévia e pedir nova confirmação";
      form.appendChild(update);
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        runReportPreviewEdit(details, form, update);
      });
      article.appendChild(form);
    }
    if (details.task_url) {
      const controls = document.createElement("div");
      controls.className = "assistant-confirm-actions";
      const link = document.createElement("a");
      link.className = "btn btn-ghost";
      link.href = details.task_url;
      link.textContent = "Abrir tarefa no quadro";
      controls.appendChild(link);
      article.appendChild(controls);
    }
    if (details.service_url || details.proposal_url || (Array.isArray(details.task_urls) && details.task_urls.length)) {
      const controls = document.createElement("div");
      controls.className = "assistant-confirm-actions";
      if (details.service_url) {
        const link = document.createElement("a");
        link.className = "btn btn-ghost";
        link.href = details.service_url;
        link.textContent = "Abrir chamado";
        controls.appendChild(link);
      }
      if (details.proposal_url) {
        const link = document.createElement("a");
        link.className = "btn btn-ghost";
        link.href = details.proposal_url;
        link.textContent = "Preparar proposta";
        controls.appendChild(link);
      }
      for (const [index, url] of details.task_urls.entries()) {
        const link = document.createElement("a");
        link.className = "btn btn-ghost";
        link.href = url;
        link.textContent = details.task_urls.length > 1 ? `Abrir lembrete ${index + 1}` : "Abrir tarefa no quadro";
        controls.appendChild(link);
      }
      article.appendChild(controls);
    }
    if (details.report_docx_url || details.report_pdf_url) {
      const controls = document.createElement("div");
      controls.className = "assistant-confirm-actions";
      for (const [url, label] of [
        [details.report_docx_url, "Baixar relatório DOCX"],
        [details.report_pdf_url, "Baixar relatório PDF"],
      ]) {
        if (!url) continue;
        const link = document.createElement("a");
        link.className = "btn btn-ghost";
        link.href = url;
        link.textContent = label;
        link.setAttribute("download", "");
        controls.appendChild(link);
      }
      article.appendChild(controls);
    }
    if (Array.isArray(details.email_items) && details.email_items.length) {
      const list = document.createElement("div");
      list.className = "assistant-email-list";
      for (const item of details.email_items) {
        const card = document.createElement("section");
        card.className = "assistant-email-card";
        const heading = document.createElement("strong");
        heading.textContent = item.subject || "(sem assunto)";
        const meta = document.createElement("span");
        const readState = item.seen ? "Lido no servidor" : "Não lido no servidor";
        const date = item.received_at ? new Date(item.received_at).toLocaleString("pt-BR") : "data indisponível";
        meta.textContent = `${item.sender || "Remetente desconhecido"} · ${date} · ${readState}`;
        const summary = document.createElement("p");
        summary.textContent = item.summary || "Sem trecho disponível.";
        const priority = document.createElement("p");
        priority.textContent = `Prioridade sugerida: ${item.priority || "normal"}. ${item.priority_reason || ""}`;
        const categoryLabels = {
          customer_quote_request: "Pedido de orçamento de cliente",
          vendor_quotation: "Cotação de fornecedor",
          purchase_order: "Pedido/ordem de compra",
          invoice_request: "Solicitação de nota fiscal",
          invoice_received: "Nota fiscal recebida",
          accounts_payable: "Conta a pagar",
          accounts_receivable: "Cobrança/conta a receber",
          payment_proof: "Comprovante de pagamento",
          service_request: "Chamado/serviço",
          pending_reply: "Possível resposta pendente",
          informational: "Informativo",
          other_review: "Triagem necessária",
        };
        const category = document.createElement("p");
        const uncertain = item.confidence_band === "low";
        category.textContent = `Categoria: ${categoryLabels[item.category] || "Triagem necessária"} · confiança ${item.confidence_band || "baixa"}${uncertain ? " · revisar" : ""}. ${item.classification_reason || ""}`;
        card.append(heading, meta, summary, priority, category);
        if (item.action_suggested) {
          const action = document.createElement("p");
          action.textContent = `Ação sugerida: ${item.action_suggested}`;
          card.appendChild(action);
        }
        list.appendChild(card);
      }
      if (details.consulted_interval) {
        const interval = document.createElement("small");
        interval.textContent = `Período consultado: ${details.consulted_interval}`;
        list.appendChild(interval);
      }
      for (const limitation of details.limitations || []) {
        const note = document.createElement("small");
        note.className = "assistant-email-limitation";
        note.textContent = limitation;
        list.appendChild(note);
      }
      article.appendChild(list);
    }
    history.appendChild(article);
    history.scrollTop = history.scrollHeight;
  }

  const controller = new AssistantChatController({
    fetchImpl: window.fetch.bind(window),
    makeRequestId,
    getConversationId: () => conversationId,
    setConversationId: updateConversation,
    onUserMessage: (message) => appendMessage("user", message),
    onAssistantMessage: (payload) => appendMessage("assistant", payload.message, payload.kind, payload),
    onBusy: (value) => setBusy(value),
    onRetryAvailable: (available) => { retryButton.hidden = !available; },
  });

  async function runAction(details, action, controls) {
    if (controller.busy) return;
    controls.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    controller._setBusy(true);
    setBusy(true, action === "confirm"
      ? (details.report_fields ? "Gerando relatório técnico..." : "Salvando a tarefa...")
      : "Cancelando...");
    try {
      const response = await fetchWithTimeout(window.fetch.bind(window), `/api/assistant/actions/${details.action_id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation_token: details.confirmation_token }),
      }, 95000);
      const payload = await responseJson(response);
      appendMessage("assistant", payload.message, payload.kind, payload);
    } catch (error) {
      appendMessage("assistant", error.message, "error");
      controls.querySelectorAll("button").forEach((button) => { button.disabled = false; });
    } finally {
      controller._setBusy(false);
      input.focus();
    }
  }

  async function runReportPreviewEdit(details, form, submitButton) {
    if (controller.busy) return;
    const fields = {};
    form.querySelectorAll("[data-report-field]").forEach((input) => {
      fields[input.dataset.reportField] = input.value;
    });
    submitButton.disabled = true;
    controller._setBusy(true);
    setBusy(true, "Atualizando prévia; será necessária nova confirmação...");
    try {
      const response = await fetchWithTimeout(window.fetch.bind(window),
        `/api/assistant/actions/${details.action_id}/report-preview`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirmation_token: details.confirmation_token, fields }),
        }, 95000);
      const payload = await responseJson(response);
      appendMessage("assistant", payload.message, payload.kind, payload);
    } catch (error) {
      appendMessage("assistant", error.message, "error");
      submitButton.disabled = false;
    } finally {
      controller._setBusy(false);
      input.focus();
    }
  }

  async function loadHistory() {
    if (!conversationId) return;
    setBusy(true, "Carregando conversa...");
    try {
      const response = await fetchWithTimeout(
        window.fetch.bind(window),
        `/api/assistant/conversations/${conversationId}`,
        {},
        30000,
      );
      const payload = await responseJson(response);
      for (const message of payload.messages || []) {
        appendMessage(message.role, message.content, message.kind, message.details);
      }
    } catch (error) {
      appendMessage("assistant", error.message, "error");
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message || controller.busy) return;
    input.value = "";
    try { await controller.send(message); } catch (_error) { /* rendered above */ }
    input.focus();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  retryButton.addEventListener("click", async () => {
    retryButton.hidden = true;
    try { await controller.retry(); } catch (_error) { /* rendered above */ }
    input.focus();
  });

  controller.appendMessage = appendMessage;
  controller.loadHistory = loadHistory;
  loadHistory();
  return controller;
}


let browserChat = null;
export function getAssistantChat() { return browserChat; }

if (typeof document !== "undefined") {
  browserChat = bootstrapAssistantChat(document);
  window.assistantChat = browserChat;
  window.dispatchEvent(new CustomEvent("assistant-chat-ready", { detail: browserChat }));
}
