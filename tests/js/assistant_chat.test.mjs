import assert from "node:assert/strict";
import test from "node:test";

import { AssistantChatController, bootstrapAssistantChat } from "../../app/static/assistant_chat.js";


function response(payload, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    async text() { return typeof payload === "string" ? payload : JSON.stringify(payload); },
  };
}


function harness(overrides = {}) {
  const events = [];
  const requests = [];
  let conversationId = null;
  const controller = new AssistantChatController({
    fetchImpl: async (_url, options) => {
      requests.push(JSON.parse(options.body));
      return response({ conversation_id: 7, kind: "text", message: "Resposta natural" });
    },
    makeRequestId: () => "request-fixed",
    getConversationId: () => conversationId,
    setConversationId: (id) => { conversationId = id; },
    onUserMessage: (message) => events.push(["user", message]),
    onAssistantMessage: (payload) => events.push(["assistant", payload.message, payload.kind]),
    onBusy: (busy) => events.push(["busy", busy]),
    onRetryAvailable: (available) => events.push(["retry", available]),
    timeoutMs: 100,
    ...overrides,
  });
  return { controller, events, requests, getConversationId: () => conversationId };
}


test("send gives immediate feedback and always clears busy state", async () => {
  let release;
  const waiting = new Promise((resolve) => { release = resolve; });
  const sample = harness({
    fetchImpl: async () => {
      await waiting;
      return response({ conversation_id: 9, kind: "text", message: "Olá!" });
    },
  });

  const sending = sample.controller.send("Oi");
  assert.deepEqual(sample.events.slice(0, 3), [
    ["user", "Oi"],
    ["retry", false],
    ["busy", true],
  ]);
  release();
  const reply = await sending;

  assert.equal(reply.message, "Olá!");
  assert.equal(sample.getConversationId(), 9);
  assert.deepEqual(sample.events.at(-1), ["busy", false]);
});


test("voice messages appear as one normal user bubble when automatically sent", async () => {
  const sample = harness();
  await sample.controller.send("frase reconhecida de teste", { source: "voice" });

  assert.deepEqual(sample.events.filter((event) => event[0] === "user"), [
    ["user", "frase reconhecida de teste"],
  ]);
  assert.equal(sample.requests[0].message, "frase reconhecida de teste");
  assert.equal(sample.requests[0].source, "voice");
});


test("retrying a voice request retains its id and transcript without duplicating the bubble", async () => {
  let calls = 0;
  const sample = harness({
    fetchImpl: async (_url, options) => {
      const body = JSON.parse(options.body);
      calls += 1;
      sample.requests.push(body);
      return calls === 1
        ? response({ conversation_id: 7, kind: "error", retryable: true, message: "Tente novamente." })
        : response({ conversation_id: 7, kind: "text", message: "Pronto." });
    },
  });
  await sample.controller.send("frase de voz sintética", { source: "voice" });
  await sample.controller.retry();

  assert.equal(sample.requests[0].request_id, sample.requests[1].request_id);
  assert.equal(sample.requests[1].source, "voice");
  assert.deepEqual(sample.events.filter((event) => event[0] === "user"), [
    ["user", "frase de voz sintética"],
  ]);
});


test("voice history shows the stored transcript as a normal user message", async () => {
  const oldWindow = globalThis.window;
  const oldDocument = globalThis.document;
  const makeElement = (tagName = "div") => ({
    tagName, children: [], classList: { toggle() {} }, listeners: {}, dataset: {},
    addEventListener(name, callback) { this.listeners[name] = callback; },
    append(...items) { this.children.push(...items); },
    appendChild(item) { this.children.push(item); },
    remove() { this.removed = true; },
    focus() {}, requestSubmit() {},
    querySelectorAll() { return []; },
  });
  const elements = new Map([
    ["assistant-form", makeElement("form")], ["assistant-message", makeElement("textarea")],
    ["assistant-send", makeElement("button")], ["assistant-history", makeElement("main")],
    ["assistant-empty", makeElement("div")], ["assistant-status", makeElement("div")],
    ["assistant-retry", makeElement("button")],
  ]);
  globalThis.window = {
    location: { href: "http://127.0.0.1:8013/web/assistente?conversation_id=22", search: "?conversation_id=22" },
    history: { replaceState() {} }, crypto: { randomUUID: () => "voice-history" },
    fetch: async () => response({ conversation_id: 22, messages: [
      { role: "user", kind: "text", content: "frase reconhecida no histórico", details: { source: "voice" } },
      { role: "assistant", kind: "text", content: "Resposta audível" },
    ] }),
  };
  globalThis.document = { createElement: makeElement };
  try {
    const controller = bootstrapAssistantChat({ getElementById: (id) => elements.get(id) });
    await controller.loadHistory();
    const rendered = [];
    const walk = (element) => {
      if (element.textContent) rendered.push(element.textContent);
      for (const child of element.children || []) walk(child);
    };
    walk(elements.get("assistant-history"));
    assert.ok(rendered.includes("Resposta audível"));
    assert.ok(rendered.includes("frase reconhecida no histórico"));
  } finally {
    globalThis.window = oldWindow;
    globalThis.document = oldDocument;
  }
});


test("service and reminder links returned after confirmation are rendered in history", async () => {
  const oldWindow = globalThis.window;
  const oldDocument = globalThis.document;
  const makeElement = (tagName = "div") => ({
    tagName, children: [], classList: { toggle() {} }, listeners: {},
    addEventListener(name, callback) { this.listeners[name] = callback; },
    append(...items) { this.children.push(...items); },
    appendChild(item) { this.children.push(item); },
    remove() { this.removed = true; },
    focus() {}, requestSubmit() {},
    querySelectorAll(selector) {
      const matches = [];
      const walk = (item) => {
        if (selector === "button" && item.tagName === "button") matches.push(item);
        for (const child of item.children || []) walk(child);
      };
      walk(this);
      return matches;
    },
  });
  const elements = new Map([
    ["assistant-form", makeElement("form")],
    ["assistant-message", makeElement("textarea")],
    ["assistant-send", makeElement("button")],
    ["assistant-history", makeElement("main")],
    ["assistant-empty", makeElement("div")],
    ["assistant-status", makeElement("div")],
    ["assistant-retry", makeElement("button")],
  ]);
  globalThis.window = {
    location: { href: "http://127.0.0.1:8011/web/assistant" },
    history: { replaceState() {} }, crypto: { randomUUID: () => "ui-test" },
    fetch: async () => response({ conversation_id: 8, kind: "success", message: "Pronto.",
      service_call_id: 7, service_url: "/web/services/7", proposal_url: "/web/proposals/new?client_id=3",
      task_urls: ["/web/board/21/edit", "/web/board/22/edit"] }),
  };
  globalThis.document = { createElement: makeElement };
  try {
    const controller = bootstrapAssistantChat({ getElementById: (id) => elements.get(id) });
    await controller.send("Crie os lembretes");
    const anchors = [];
    const walk = (item) => {
      if (item.tagName === "a") anchors.push([item.textContent, item.href]);
      for (const child of item.children || []) walk(child);
    };
    walk(elements.get("assistant-history"));
    assert.deepEqual(anchors, [
      ["Abrir chamado", "/web/services/7"],
      ["Preparar proposta", "/web/proposals/new?client_id=3"],
      ["Abrir lembrete 1", "/web/board/21/edit"],
      ["Abrir lembrete 2", "/web/board/22/edit"],
    ]);
  } finally {
    globalThis.window = oldWindow;
    globalThis.document = oldDocument;
  }
});


test("email result cards show category evidence and mark uncertain classification for review", async () => {
  const oldWindow = globalThis.window;
  const oldDocument = globalThis.document;
  const makeElement = (tagName = "div") => ({
    tagName, children: [], classList: { toggle() {} }, listeners: {}, textContent: "",
    addEventListener(name, callback) { this.listeners[name] = callback; },
    append(...items) { this.children.push(...items); },
    appendChild(item) { this.children.push(item); },
    remove() {}, focus() {}, requestSubmit() {},
  });
  const elements = new Map([
    ["assistant-form", makeElement("form")], ["assistant-message", makeElement("textarea")],
    ["assistant-send", makeElement("button")], ["assistant-history", makeElement("main")],
    ["assistant-empty", makeElement("div")], ["assistant-status", makeElement("div")],
    ["assistant-retry", makeElement("button")],
  ]);
  globalThis.window = {
    location: { href: "http://127.0.0.1:8011/web/assistente" },
    history: { replaceState() {} }, crypto: { randomUUID: () => "category-ui" },
    fetch: async () => response({ conversation_id: 8, kind: "text", message: "Há uma mensagem para revisar.",
      email_items: [{ subject: "Consulta comercial", sender: "Cliente sintético", received_at: "2026-10-02T10:00:00-03:00",
        seen: false, summary: "Texto sintético", priority: "normal", priority_reason: "Sem prazo confirmado.",
        category: "customer_quote_request", confidence_band: "low", classification_reason: "Menção genérica a orçamento." }] }),
  };
  globalThis.document = { createElement: makeElement };
  try {
    const controller = bootstrapAssistantChat({ getElementById: (id) => elements.get(id) });
    await controller.send("Me mostre esta mensagem");
    const labels = [];
    const walk = (element) => {
      if (element.textContent) labels.push(element.textContent);
      for (const child of element.children) walk(child);
    };
    walk(elements.get("assistant-history"));
    assert.ok(labels.some((text) => text.includes("Pedido de orçamento de cliente")));
    assert.ok(labels.some((text) => text.includes("revisar")));
    assert.ok(labels.some((text) => text.includes("Menção genérica a orçamento.")));
  } finally {
    globalThis.window = oldWindow;
    globalThis.document = oldDocument;
  }
});


test("timeout is visible and retry reuses request id without duplicating user message", async () => {
  let calls = 0;
  const sample = harness({
    timeoutMs: 5,
    fetchImpl: async (_url, options) => {
      calls += 1;
      const body = JSON.parse(options.body);
      sample.requests.push(body);
      if (calls === 1) {
        return new Promise((_resolve, reject) => {
          options.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        });
      }
      return response({ conversation_id: 3, kind: "text", message: "Recuperado" });
    },
  });

  await assert.rejects(sample.controller.send("Consulta"), /demorou/i);
  const reply = await sample.controller.retry();

  assert.equal(reply.message, "Recuperado");
  assert.equal(sample.requests[0].request_id, sample.requests[1].request_id);
  assert.equal(sample.events.filter(([type]) => type === "user").length, 1);
  assert.deepEqual(sample.events.at(-1), ["busy", false]);
});


test("retryable assistant errors keep the same request and do not duplicate the user bubble", async () => {
  let calls = 0;
  const sample = harness({
    fetchImpl: async (_url, options) => {
      calls += 1;
      const payload = JSON.parse(options.body);
      sample.requests.push(payload);
      return calls === 1
        ? response({ conversation_id: 7, kind: "error", retryable: true, message: "Ollama offline." })
        : response({ conversation_id: 7, kind: "text", message: "Consulta retomada." });
    },
  });

  await sample.controller.send("Quais e-mails chegaram?");
  const reply = await sample.controller.retry();

  assert.equal(reply.message, "Consulta retomada.");
  assert.equal(sample.requests[0].request_id, sample.requests[1].request_id);
  assert.equal(sample.requests[1].retry, true);
  assert.equal(sample.events.filter(([type]) => type === "user").length, 1);
});


for (const [name, fetchImpl, pattern] of [
  ["HTTP error", async () => response({ detail: "Ollama indisponível" }, { ok: false, status: 503 }), /Ollama/],
  ["invalid JSON", async () => response("not json"), /resposta inválida/i],
  ["empty payload", async () => response({ conversation_id: 1, kind: "text", message: "" }), /resposta vazia/i],
]) {
  test(`${name} is shown and leaves chat recoverable`, async () => {
    const sample = harness({ fetchImpl });

    await assert.rejects(sample.controller.send("Oi"), pattern);

    assert.equal(sample.controller.busy, false);
    assert.deepEqual(sample.events.at(-1), ["busy", false]);
    assert.ok(sample.events.some((event) => event[0] === "retry" && event[1] === true));
  });
}
