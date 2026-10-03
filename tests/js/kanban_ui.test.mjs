import assert from "node:assert/strict";
import test from "node:test";

import { filterCards, postMove, taskMatchesFilters } from "../../app/static/kanban_ui.js";


test("postMove sends the exact payload to the existing endpoint", async () => {
  const calls = [];
  await postMove({
    id: 12,
    payload: { status: "em_andamento", ordem: 2 },
    endpointTemplate: "/api/tasks/{id}/move",
    fetchImpl: async (url, options) => {
      calls.push([url, options.method, JSON.parse(options.body)]);
      return { ok: true };
    },
  });

  assert.deepEqual(calls, [[
    "/api/tasks/12/move",
    "POST",
    { status: "em_andamento", ordem: 2 },
  ]]);
});


test("postMove rejects a failed response so the caller can roll back", async () => {
  await assert.rejects(
    postMove({
      id: 3,
      payload: { status: "concluido", ordem: 0 },
      endpointTemplate: "/api/tasks/{id}/move",
      fetchImpl: async () => ({ ok: false, status: 400 }),
    }),
    /Não foi possível mover/,
  );
});


test("task filters include free-text clients and deadline states", () => {
  const task = {
    search: "preparar orçamento roca",
    status: "a_fazer",
    owner: "carlos",
    client: "roca",
    deadline: "2026-10-02",
  };

  assert.equal(taskMatchesFilters(task, {
    search: "roca",
    status: "a_fazer",
    owner: "carlos",
    client: "roca",
    deadline: "today",
    today: "2026-10-02",
  }), true);
  assert.equal(taskMatchesFilters(task, { deadline: "overdue", today: "2026-10-03" }), true);
  assert.equal(taskMatchesFilters(task, { client: "outro" }), false);
});


test("filterCards hides non-matching cards and returns the visible count", () => {
  const cards = [
    { dataset: { search: "cliente alfa", status: "a_fazer", deadline: "" }, hidden: false },
    { dataset: { search: "cliente beta", status: "concluido", deadline: "2026-10-01" }, hidden: false },
  ];

  const visible = filterCards(cards, { search: "alfa" });

  assert.equal(visible, 1);
  assert.deepEqual(cards.map((card) => card.hidden), [false, true]);
});
