export class VoiceSessionController {
  constructor(options) {
    this.options = options;
    this.silenceMs = options.silenceMs ?? 1200;
    this.speechThreshold = options.speechThreshold ?? 0.018;
    this.maxUtteranceMs = options.maxUtteranceMs ?? 30000;
    this.idleTimeoutMs = options.idleTimeoutMs ?? 120000;
    this.active = false;
    this.state = "idle";
    this.generation = 0;
    this.stream = null;
    this.capture = null;
    this.currentAudio = null;
    this.lastReply = null;
    this.lastAudioBlob = null;
    this.heardSpeech = false;
    this.lastSpeechAt = 0;
    this._inFlight = Promise.resolve();
    this._utteranceTimer = 0;
    this._idleTimer = 0;
  }

  _setState(state) {
    if (state !== "listening") this._clearListeningTimers();
    this.state = state;
    this.options.onState?.(state);
  }

  _isCurrent(generation) {
    return this.active && generation === this.generation;
  }

  async start() {
    if (this.active) return;
    const generation = ++this.generation;
    this.active = true;
    this._setState("requesting");
    try {
      const stream = await this.options.getStream();
      if (!this._isCurrent(generation)) {
        releaseStream(stream);
        return;
      }
      this.stream = stream;
      this._beginListening(generation);
    } catch (_error) {
      if (generation !== this.generation) return;
      const microphoneWasGranted = Boolean(this.stream);
      this.capture?.cancel();
      this.capture = null;
      releaseStream(this.stream);
      this.stream = null;
      this.active = false;
      this._setState("idle");
      this.options.onError?.(new Error(
        microphoneWasGranted
          ? "O navegador permitiu o microfone, mas nao conseguiu gravar neste formato."
          : "Nao foi possivel acessar o microfone. Verifique a permissao do navegador."
      ));
    }
  }

  _beginListening(generation) {
    if (!this._isCurrent(generation) || !this.stream) return;
    this.heardSpeech = false;
    this.lastSpeechAt = 0;
    this.capture = this.options.captureFactory(
      this.stream,
      (level, now) => this.observeLevel(level, now),
    );
    this.capture.start();
    this._setState("listening");
    this._utteranceTimer = setTimeout(() => this.finishUtterance(), this.maxUtteranceMs);
    this._idleTimer = setTimeout(() => {
      if (!this.active || this.state !== "listening" || this.heardSpeech) return;
      this.stop();
      this.options.onError?.(new Error("Conversa encerrada por falta de fala."));
    }, this.idleTimeoutMs);
  }

  observeLevel(level, now = performance.now()) {
    if (!this.active || this.state !== "listening") return;
    if (level >= this.speechThreshold) {
      this.heardSpeech = true;
      this.lastSpeechAt = now;
      return;
    }
    if (this.heardSpeech && now - this.lastSpeechAt >= this.silenceMs) {
      this._inFlight = this.finishUtterance();
    }
  }

  finishUtterance() {
    if (!this.active || this.state !== "listening" || !this.capture) {
      return Promise.resolve();
    }
    const generation = this.generation;
    const capture = this.capture;
    this.capture = null;
    this._setState("transcribing");
    const work = this._processUtterance(capture, generation);
    this._inFlight = work;
    return work;
  }

  async _processUtterance(capture, generation) {
    try {
      const blob = await capture.stop();
      if (!this._isCurrent(generation)) return;
      const transcript = await this.options.transcribe(blob);
      if (!this._isCurrent(generation)) return;
      this.options.onTranscript?.(transcript.text);
      this._setState("processing");
      const reply = await this.options.sendText(transcript.text);
      if (!this._isCurrent(generation)) return;
      this.lastReply = reply;
      this.lastAudioBlob = null;
      this.options.onReply?.(reply);
      await this._requestSpeech(reply, generation);
    } catch (error) {
      if (!this._isCurrent(generation)) return;
      this._failSession(error instanceof Error ? error : new Error(String(error)));
    }
  }

  async _requestSpeech(reply, generation) {
    this._setState("speaking");
    try {
      const blob = await this.options.synthesize(reply);
      if (!this._isCurrent(generation)) return;
      this.lastAudioBlob = blob;
      this._startPlayback(blob, generation);
    } catch (error) {
      if (!this._isCurrent(generation)) return;
      this._setState("error");
      this.options.onError?.(new Error(
        `A resposta foi concluida, mas o audio falhou: ${error.message || error}`
      ));
    }
  }

  _startPlayback(blob, generation) {
    if (!this._isCurrent(generation)) return;
    this.currentAudio?.stop();
    const audio = this.options.audioFactory(blob);
    this.currentAudio = audio;
    this._setState("speaking");
    Promise.resolve(audio.play()).then(
      () => this._afterPlayback(audio, generation),
      (error) => {
        if (!this._isCurrent(generation) || this.currentAudio !== audio) return;
        this.currentAudio = null;
        this._setState("error");
        this.options.onError?.(error instanceof Error ? error : new Error(String(error)));
      },
    );
  }

  _afterPlayback(audio, generation) {
    if (!this._isCurrent(generation) || this.currentAudio !== audio) return;
    this.currentAudio = null;
    this._beginListening(generation);
  }

  stopPlayback() {
    if (!this.currentAudio) return;
    const audio = this.currentAudio;
    this.currentAudio = null;
    audio.stop();
    if (this.active) this._beginListening(this.generation);
  }

  async repeatSpeech() {
    if (!this.active || !this.lastAudioBlob) return;
    if (this.capture) {
      this.capture.cancel();
      this.capture = null;
    }
    this._startPlayback(this.lastAudioBlob, this.generation);
  }

  async retrySpeech() {
    if (!this.active || !this.lastReply) return;
    await this._requestSpeech(this.lastReply, this.generation);
  }

  stop() {
    ++this.generation;
    this.active = false;
    this.capture?.cancel();
    this.capture = null;
    this.currentAudio?.stop();
    this.currentAudio = null;
    releaseStream(this.stream);
    this.stream = null;
    this._setState("idle");
  }

  _failSession(error) {
    ++this.generation;
    this.active = false;
    this.capture?.cancel();
    this.capture = null;
    this.currentAudio?.stop();
    this.currentAudio = null;
    releaseStream(this.stream);
    this.stream = null;
    this._setState("error");
    this.options.onError?.(error);
  }

  _clearListeningTimers() {
    clearTimeout(this._utteranceTimer);
    clearTimeout(this._idleTimer);
    this._utteranceTimer = 0;
    this._idleTimer = 0;
  }

  whenSettled() {
    return this._inFlight;
  }
}


export function createBrowserCapture(stream, onLevel) {
  const mimeType = selectMimeType();
  const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
  const chunks = [];
  let stopped = false;
  let resolveStop;
  const stoppedPromise = new Promise((resolve) => { resolveStop = resolve; });
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  const context = new AudioContextClass();
  const source = context.createMediaStreamSource(stream);
  const analyser = context.createAnalyser();
  analyser.fftSize = 1024;
  const samples = new Uint8Array(analyser.fftSize);
  source.connect(analyser);
  let animationFrame = 0;
  let contextClosed = false;

  function closeContext() {
    if (contextClosed) return;
    contextClosed = true;
    Promise.resolve(context.close()).catch(() => {});
  }

  recorder.addEventListener("dataavailable", (event) => {
    if (event.data?.size) chunks.push(event.data);
  });
  recorder.addEventListener("stop", () => {
    stopped = true;
    cancelAnimationFrame(animationFrame);
    closeContext();
    resolveStop(new Blob(chunks, { type: recorder.mimeType || mimeType || "audio/webm" }));
  });

  function sample() {
    if (stopped) return;
    analyser.getByteTimeDomainData(samples);
    let squared = 0;
    for (const value of samples) {
      const normalized = (value - 128) / 128;
      squared += normalized * normalized;
    }
    onLevel(Math.sqrt(squared / samples.length), performance.now());
    animationFrame = requestAnimationFrame(sample);
  }

  return {
    start() {
      recorder.start(250);
      animationFrame = requestAnimationFrame(sample);
    },
    stop() {
      if (recorder.state !== "inactive") recorder.stop();
      return stoppedPromise;
    },
    cancel() {
      if (recorder.state !== "inactive") recorder.stop();
      stopped = true;
      cancelAnimationFrame(animationFrame);
      closeContext();
    },
  };
}


export function createBrowserAudio(blob) {
  const url = URL.createObjectURL(blob);
  const element = new Audio(url);
  let settled = false;
  let resolvePlayback;
  let rejectPlayback;
  const playback = new Promise((resolve, reject) => {
    resolvePlayback = resolve;
    rejectPlayback = reject;
  });
  const finish = () => {
    if (settled) return;
    settled = true;
    URL.revokeObjectURL(url);
    resolvePlayback();
  };
  element.addEventListener("ended", finish, { once: true });
  element.addEventListener("error", () => {
    if (settled) return;
    settled = true;
    URL.revokeObjectURL(url);
    rejectPlayback(new Error("Nao foi possivel reproduzir a resposta."));
  }, { once: true });
  return {
    async play() {
      try {
        await element.play();
      } catch (error) {
        if (!settled) {
          settled = true;
          URL.revokeObjectURL(url);
        }
        throw error;
      }
      return playback;
    },
    stop() {
      element.pause();
      element.currentTime = 0;
      finish();
    },
  };
}


function selectMimeType() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}


function releaseStream(stream) {
  stream?.getTracks?.().forEach((track) => track.stop());
}
