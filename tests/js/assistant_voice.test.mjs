import assert from "node:assert/strict";
import test from "node:test";

import { VoiceSessionController } from "../../app/static/assistant_voice.js";


function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

function harness(overrides = {}) {
  const states = [];
  const errors = [];
  const levels = [];
  const tracks = [{ stopped: 0, stop() { this.stopped += 1; } }];
  const stream = { getTracks: () => tracks };
  const captures = [];
  const audios = [];
  const controller = new VoiceSessionController({
    getStream: async () => stream,
    captureFactory: () => {
      const capture = {
        cancelled: false,
        startCalls: 0,
        start() { this.startCalls += 1; },
        async stop() { return new Blob(["audio"], { type: "audio/webm" }); },
        cancel() { this.cancelled = true; },
      };
      captures.push(capture);
      return capture;
    },
    transcribe: async () => ({ text: "Pode criar" }),
    sendText: async (text) => ({ message: `Resposta para ${text}`, kind: "success" }),
    synthesize: async () => new Blob(["wav"], { type: "audio/wav" }),
    audioFactory: () => {
      const ended = deferred();
      const audio = {
        playCalls: 0,
        stopCalls: 0,
        play() { this.playCalls += 1; return ended.promise; },
        stop() { this.stopCalls += 1; ended.resolve(); },
      };
      audios.push(audio);
      return audio;
    },
    onState: (state) => states.push(state),
    onError: (error) => errors.push(error.message),
    onLevel: (level) => levels.push(level),
    silenceMs: 100,
    ...overrides,
  });
  return { controller, states, errors, levels, tracks, captures, audios };
}


test("permission failure returns to idle with a useful error", async () => {
  const sample = harness({ getStream: async () => { throw new Error("denied"); } });
  await sample.controller.start();
  assert.equal(sample.controller.active, false);
  assert.equal(sample.states.at(-1), "idle");
  assert.match(sample.errors.at(-1), /microfone/i);
});


for (const [name, expected] of [
  ["NotAllowedError", /permiss[aã]o.*microfone/i],
  ["NotFoundError", /nenhum microfone/i],
  ["NotReadableError", /microfone.*uso/i],
]) {
  test(`${name} gives a specific microphone recovery message`, async () => {
    const error = new Error(name);
    error.name = name;
    const sample = harness({ getStream: async () => { throw error; } });

    const starting = sample.controller.start();
    assert.equal(sample.states.at(-1), "requesting", "click must react before permission settles");
    await starting;

    assert.match(sample.errors.at(-1), expected);
    assert.equal(sample.controller.active, false);
  });
}


test("recorder startup failure releases the granted microphone", async () => {
  const sample = harness({ captureFactory: () => { throw new Error("unsupported"); } });
  await sample.controller.start();
  assert.equal(sample.controller.active, false);
  assert.equal(sample.tracks[0].stopped, 1);
  assert.match(sample.errors.at(-1), /gravar/i);
});


test("silence after speech automatically finishes the utterance", async () => {
  const sample = harness();
  await sample.controller.start();
  sample.controller.observeLevel(0.08, 0);
  sample.controller.observeLevel(0.001, 150);
  await sample.controller.whenSettled();
  assert.equal(sample.captures[0].startCalls, 1);
  assert.equal(sample.audios[0].playCalls, 1);
  sample.controller.stop();
});


test("microphone levels are exposed while listening and reset when it stops", async () => {
  const sample = harness();
  await sample.controller.start();
  sample.controller.observeLevel(0.04, 10);
  sample.controller.stop();

  assert.equal(sample.levels[0], 0.04);
  assert.equal(sample.levels.at(-1), 0);
});


test("manual finish serializes transcription, assistant, and playback", async () => {
  const order = [];
  const sample = harness({
    transcribe: async () => { order.push("transcribe"); return { text: "Consulta" }; },
    sendText: async () => { order.push("assistant"); return { message: "Resposta", kind: "text" }; },
    synthesize: async () => { order.push("speech"); return new Blob(["wav"]); },
  });
  await sample.controller.start();
  await sample.controller.finishUtterance();
  assert.deepEqual(order, ["transcribe", "assistant", "speech"]);
  assert.equal(sample.captures.length, 1, "listening remains suspended during playback");
  sample.controller.stop();
});


test("ending a session releases tracks and ignores late transcription", async () => {
  const transcription = deferred();
  const sample = harness({ transcribe: () => transcription.promise });
  await sample.controller.start();
  const finishing = sample.controller.finishUtterance();
  sample.controller.stop();
  transcription.resolve({ text: "Pode criar" });
  await finishing;
  assert.equal(sample.tracks[0].stopped, 1);
  assert.equal(sample.audios.length, 0);
  assert.equal(sample.captures.length, 1, "late work cannot restart the microphone");
});


test("transcription failure releases the microphone and permits a fresh session", async () => {
  const sample = harness({ transcribe: async () => { throw new Error("stt offline"); } });
  await sample.controller.start();
  await sample.controller.finishUtterance();
  assert.equal(sample.controller.active, false);
  assert.equal(sample.tracks[0].stopped, 1);
  assert.equal(sample.controller.state, "error");
});


test("speech retry does not resend the assistant request", async () => {
  let sends = 0;
  let speechCalls = 0;
  const sample = harness({
    sendText: async () => { sends += 1; return { message: "Tarefa criada", kind: "success" }; },
    synthesize: async () => {
      speechCalls += 1;
      if (speechCalls === 1) throw new Error("tts offline");
      return new Blob(["wav"]);
    },
  });
  sample.controller.lastAudioBlob = new Blob(["old-response"]);
  await sample.controller.start();
  await sample.controller.finishUtterance();
  assert.equal(sample.controller.lastAudioBlob, null, "old audio must not mask a failed new reply");
  await sample.controller.retrySpeech();
  assert.equal(sends, 1);
  assert.equal(speechCalls, 2);
  sample.controller.stop();
});


test("repeating audio suspends a newly resumed capture", async () => {
  const sample = harness();
  await sample.controller.start();
  await sample.controller.finishUtterance();
  sample.audios[0].stop();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(sample.controller.state, "listening");

  await sample.controller.repeatSpeech();

  assert.equal(sample.captures[1].cancelled, true);
  assert.equal(sample.audios.length, 2);
  sample.controller.stop();
});
