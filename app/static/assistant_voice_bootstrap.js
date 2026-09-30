import { fetchWithTimeout, getAssistantChat, responseJson } from "/assets/assistant_chat.js";
import {
  VoiceSessionController,
  createBrowserAudio,
  createBrowserCapture,
} from "/assets/assistant_voice.js";


export async function bootstrapAssistantVoice(root = document, chat = getAssistantChat()) {
  const voiceStart = root.getElementById("voice-start");
  if (!voiceStart || !chat) return null;
  const voiceFinish = root.getElementById("voice-finish");
  const voiceStop = root.getElementById("voice-stop");
  const voiceRepeat = root.getElementById("voice-repeat");
  const voiceEnd = root.getElementById("voice-end");
  const voiceState = root.getElementById("voice-state");
  const voiceLevel = root.getElementById("voice-level");
  let controller = null;
  let voiceReady = false;

  const labels = {
    idle: "Conversa encerrada.",
    requesting: "Solicitando acesso ao microfone...",
    listening: "Ouvindo. Fale naturalmente; o silêncio encerra a fala.",
    transcribing: "Transcrevendo localmente...",
    processing: "Consultando o assistente local...",
    speaking: "Reproduzindo a resposta...",
    error: "A voz encontrou um problema. O texto continua disponível.",
  };

  function renderState(state) {
    const active = controller?.active || false;
    voiceState.dataset.state = state;
    voiceState.textContent = labels[state] || state;
    voiceStart.disabled = !voiceReady || active;
    voiceStart.textContent = state === "requesting" ? "Abrindo microfone..." : "Iniciar conversa";
    voiceFinish.disabled = state !== "listening";
    voiceStop.disabled = state !== "speaking";
    voiceRepeat.disabled = !active || (!controller?.lastAudioBlob && !controller?.lastReply);
    voiceEnd.disabled = !active;
    if (state !== "listening") voiceLevel.value = 0;
  }

  async function transcribe(blob) {
    const body = new FormData();
    body.append("audio", blob, "fala.webm");
    const response = await fetchWithTimeout(window.fetch.bind(window), "/api/assistant/voice/transcriptions", {
      method: "POST",
      body,
    }, 70000);
    return responseJson(response);
  }

  async function synthesize(reply) {
    const response = await fetchWithTimeout(window.fetch.bind(window), "/api/assistant/voice/speech", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: reply.message, kind: reply.kind }),
    }, 40000);
    if (!response.ok) {
      let detail = "Não foi possível gerar o áudio local.";
      try { detail = (await response.json()).detail || detail; } catch (_error) { /* ignore */ }
      throw new Error(detail);
    }
    return response.blob();
  }

  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder || !(window.AudioContext || window.webkitAudioContext)) {
    voiceState.textContent = "Este navegador não oferece os recursos locais de áudio necessários.";
    voiceState.dataset.state = "error";
    return null;
  }

  try {
    const response = await fetchWithTimeout(
      window.fetch.bind(window),
      "/api/assistant/voice/status",
      {},
      15000,
    );
    const configuration = await responseJson(response);
    voiceReady = configuration.enabled && configuration.transcription_available && configuration.synthesis_available;
    controller = new VoiceSessionController({
      getStream: () => navigator.mediaDevices.getUserMedia({ audio: true }),
      captureFactory: createBrowserCapture,
      transcribe,
      sendText: (text) => chat.send(text),
      synthesize,
      audioFactory: createBrowserAudio,
      silenceMs: configuration.silence_ms,
      maxUtteranceMs: configuration.max_duration_seconds * 1000,
      idleTimeoutMs: configuration.idle_timeout_seconds * 1000,
      onState: renderState,
      onLevel: (level) => { voiceLevel.value = Math.min(1, level * 8); },
      onError: (error) => {
        renderState("error");
        voiceState.textContent = error.message;
        voiceState.dataset.state = "error";
      },
    });
    if (voiceReady) {
      voiceState.textContent = "Pronto para uma conversa local por voz.";
      voiceStart.disabled = false;
    } else {
      voiceState.textContent = configuration.message;
      voiceState.dataset.state = "error";
    }
  } catch (error) {
    voiceState.textContent = error.message;
    voiceState.dataset.state = "error";
    return null;
  }

  voiceStart.addEventListener("click", () => controller.start());
  voiceFinish.addEventListener("click", () => controller.finishUtterance());
  voiceStop.addEventListener("click", () => controller.stopPlayback());
  voiceRepeat.addEventListener("click", () => {
    if (controller.lastAudioBlob) controller.repeatSpeech();
    else controller.retrySpeech();
  });
  voiceEnd.addEventListener("click", () => controller.stop());
  window.addEventListener("pagehide", () => controller.stop());
  return controller;
}


if (typeof document !== "undefined") {
  const start = () => bootstrapAssistantVoice(document, getAssistantChat());
  if (getAssistantChat()) start();
  else window.addEventListener("assistant-chat-ready", start, { once: true });
}
