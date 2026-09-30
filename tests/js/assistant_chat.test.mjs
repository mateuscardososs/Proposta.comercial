import assert from "node:assert/strict";
import test from "node:test";

import { AssistantChatController } from "../../app/static/assistant_chat.js";


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
