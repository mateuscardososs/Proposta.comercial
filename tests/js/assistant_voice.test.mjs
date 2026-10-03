import assert from "node:assert/strict";
import test from "node:test";

import {
  VoiceSessionController,
  voiceInputConstraints,
} from "../../app/static/assistant_voice.js";


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
    transcribe: async () => ({ text: "Pode criar", confidence_score: 1 }),
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
    minimumSilenceMs: 100,
    resumeDelayMs: 0,
    ...overrides,
  });
  return { controller, states, errors, levels, tracks, captures, audios };
}


async function finishBySilence(controller, startAt = 0) {
  controller.observeLevel(0.08, startAt);
  controller.observeLevel(0.001, startAt + controller.silenceMs);
  await controller.whenSettled();
}


test("permission failure returns to idle with a useful error", async () => {
  const sample = harness({ getStream: async () => { throw new Error("denied"); } });
  await sample.controller.start();
  assert.equal(sample.controller.active, false);
  assert.equal(sample.states.at(-1), "idle");
  assert.match(sample.errors.at(-1), /microfone/i);
});


test("default speech endpointing allows a natural pause before ending a turn", () => {
  const controller = new VoiceSessionController({});
  assert.equal(controller.silenceMs, 2500);
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


test("silence transcribes, submits automatically, and starts the spoken reply", async () => {
  const sample = harness();
  await sample.controller.start();
  await finishBySilence(sample.controller);
  assert.equal(sample.captures[0].startCalls, 1);
  assert.equal(sample.audios.length, 1);
  assert.equal(sample.controller.state, "speaking");
  assert.equal(sample.controller.pendingTranscript, undefined);
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


test("silence serializes transcription, assistant, and playback without review", async () => {
  const order = [];
  const sample = harness({
    transcribe: async () => { order.push("transcribe"); return { text: "Consulta" }; },
    sendText: async () => { order.push("assistant"); return { message: "Resposta", kind: "text" }; },
    synthesize: async () => { order.push("speech"); return new Blob(["wav"]); },
  });
  await sample.controller.start();
  await finishBySilence(sample.controller);
  assert.deepEqual(order, ["transcribe", "assistant", "speech"]);
  assert.equal(sample.controller.state, "speaking");
  assert.equal(sample.captures.length, 1, "listening remains suspended during playback");
  sample.controller.stop();
});


test("voice submission does not surface transcript text through transcript callbacks", async () => {
  const transcripts = [];
  const sample = harness({
    transcribe: async () => ({ text: "Me diga quase meio", confidence_score: 0.3 }),
    onTranscript: (text) => transcripts.push(text),
  });
  await sample.controller.start();
  await finishBySilence(sample.controller);

  assert.deepEqual(transcripts, []);
  assert.equal(sample.controller.state, "speaking");
  sample.controller.stop();
});


test("ending a session releases tracks and ignores late transcription", async () => {
  const transcription = deferred();
  const sample = harness({ transcribe: () => transcription.promise });
  await sample.controller.start();
  sample.controller.observeLevel(0.08, 0);
  sample.controller.observeLevel(0.001, 100);
  const finishing = sample.controller.whenSettled();
  sample.controller.stop();
  transcription.resolve({ text: "Pode criar" });
  await finishing;
  assert.equal(sample.tracks[0].stopped, 1);
  assert.equal(sample.audios.length, 0);
  assert.equal(sample.captures.length, 1, "late work cannot restart the microphone");
});


test("ending while the assistant is replying prevents late speech playback", async () => {
  const reply = deferred();
  const sample = harness({ sendText: () => reply.promise });
  await sample.controller.start();
  sample.controller.observeLevel(0.08, 0);
  sample.controller.observeLevel(0.001, 100);
  const finishing = sample.controller.whenSettled();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(sample.controller.state, "processing");
  sample.controller.stop();
  reply.resolve({ message: "Resposta tardia" });
  await finishing;

  assert.equal(sample.audios.length, 0);
  assert.equal(sample.tracks[0].stopped, 1);
  assert.equal(sample.controller.state, "idle");
});


test("transcription failure reports the error and resumes the same conversation", async () => {
  const sample = harness({
    transcribe: async () => { throw new Error("stt offline"); },
    errorRecoveryDelayMs: 0,
  });
  await sample.controller.start();
  await finishBySilence(sample.controller);
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(sample.controller.active, true);
  assert.equal(sample.tracks[0].stopped, 0);
  assert.equal(sample.controller.state, "listening");
  assert.match(sample.errors.at(-1), /stt offline/);
  assert.equal(sample.captures.length, 2);
  sample.controller.stop();
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
  await finishBySilence(sample.controller);
  assert.equal(sample.controller.lastAudioBlob, null);
  assert.equal(sample.controller.lastAudioBlob, null, "old audio must not mask a failed new reply");
  await sample.controller.retrySpeech();
  assert.equal(sends, 1);
  assert.equal(speechCalls, 2);
  sample.controller.stop();
});


test("repeating audio suspends a newly resumed capture", async () => {
  const sample = harness();
  await sample.controller.start();
  await finishBySilence(sample.controller);
  sample.audios[0].stop();
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(sample.controller.state, "listening");

  await sample.controller.repeatSpeech();

  assert.equal(sample.captures[1].cancelled, true);
  assert.equal(sample.audios.length, 2);
  sample.controller.stop();
});


test("interrupting the spoken reply resumes listening after a short echo guard", async () => {
  const sample = harness({ resumeDelayMs: 25 });
  await sample.controller.start();
  await finishBySilence(sample.controller);

  sample.controller.stopPlayback();
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(sample.captures.length, 1, "the mic stays closed during the echo guard");
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(sample.captures.length, 2);
  assert.equal(sample.controller.state, "listening");
  sample.controller.stop();
});


test("natural mid-sentence pauses do not submit; only the final silence submits once", async () => {
  let sends = 0;
  const sample = harness({ silenceMs: 2600, sendText: async () => {
    sends += 1;
    return { message: "Resposta", kind: "text" };
  } });
  await sample.controller.start();
  sample.controller.observeLevel(0.08, 0);
  sample.controller.observeLevel(0.001, 1000);
  sample.controller.observeLevel(0.001, 2500);
  assert.equal(sends, 0, "a natural pause shorter than 2.6 seconds is not a turn boundary");

  sample.controller.observeLevel(0.08, 2700);
  sample.controller.observeLevel(0.001, 3000);
  sample.controller.observeLevel(0.001, 5299);
  assert.equal(sends, 0, "the request waits for the full trailing-silence window");
  sample.controller.observeLevel(0.001, 5300);
  sample.controller.observeLevel(0.001, 9000);
  await sample.controller.whenSettled();
  assert.equal(sends, 1, "repeated quiet frames cannot duplicate the request");
  sample.controller.stop();
});


test("long quiet does not end the conversation before the user presses end", async () => {
  const sample = harness({ idleTimeoutMs: 5 });
  await sample.controller.start();
  await new Promise((resolve) => setTimeout(resolve, 20));

  assert.equal(sample.controller.active, true);
  assert.equal(sample.controller.state, "listening");
  sample.controller.stop();
});


test("microphone requests enable browser echo cancellation and noise suppression", () => {
  assert.deepEqual(voiceInputConstraints(), {
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
});
