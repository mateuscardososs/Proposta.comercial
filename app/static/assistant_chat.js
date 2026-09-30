export class AssistantChatController {
  constructor(options) {
    this.options = options;
    this.timeoutMs = options.timeoutMs ?? 95000;
    this.busy = false;
    this.pending = null;
  }

  async send(message, { retry = false } = {}) {
    const cleanMessage = String(message || "").trim();
    if (!cleanMessage) throw new Error("Digite uma mensagem antes de enviar.");
    if (this.busy) throw new Error("O assistente ainda está processando a solicitação anterior.");

    const attempt = retry && this.pending
      ? this.pending
      : { message: cleanMessage, requestId: this.options.makeRequestId() };
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
      this.pending = null;
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
    return this.send(this.pending.message, { retry: true });
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
      confirm.textContent = "Confirmar criação";
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "btn btn-ghost";
      cancel.textContent = "Cancelar";
      confirm.addEventListener("click", () => runAction(details, "confirm", controls));
      cancel.addEventListener("click", () => runAction(details, "cancel", controls));
      controls.append(confirm, cancel);
      article.appendChild(controls);
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
    setBusy(true, action === "confirm" ? "Salvando a tarefa..." : "Cancelando...");
    try {
      const response = await window.fetch(`/api/assistant/actions/${details.action_id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation_token: details.confirmation_token }),
      });
      const payload = await responseJson(response);
      appendMessage("assistant", payload.message, payload.kind, payload);
    } catch (error) {
      appendMessage("assistant", error.message, "error");
      controls.querySelectorAll("button").forEach((button) => { button.disabled = false; });
    } finally {
      setBusy(false);
      input.focus();
    }
  }

  async function loadHistory() {
    if (!conversationId) return;
    setBusy(true, "Carregando conversa...");
    try {
      const response = await window.fetch(`/api/assistant/conversations/${conversationId}`);
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
