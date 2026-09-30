# Assistente por voz local Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar uma conversa por voz local executavel que transcreve fala, reutiliza o fluxo textual existente e sintetiza respostas sem duplicar tarefas.

**Architecture:** FastAPI ganha adaptadores opcionais para faster-whisper e Piper, protegidos por um executor com capacidade limitada. O navegador implementa uma maquina de estados que alterna captura e reproducao; toda transcricao entra no endpoint textual existente.

**Tech Stack:** Python 3.12, FastAPI, anyio, PyAV, faster-whisper 1.2.1, Piper 1.8.0, JavaScript nativo, MediaRecorder, Web Audio API, pytest e Node test runner.

## Global Constraints

- Manter banco, documentos e volumes operacionais intocados durante desenvolvimento e validacao.
- Nenhuma API paga, nuvem, reconhecimento remoto do navegador, push, deploy ou bind externo.
- Modelos autorizados: `Systran/faster-whisper-small` e `pt_BR-faber-medium`, total abaixo de 2 GB.
- CPU/INT8 para transcricao; nao presumir CUDA ou Metal.
- Audio bruto nao e persistido; temporarios sao removidos inclusive em erro ou timeout.
- Uma inferencia ativa e no maximo uma esperando por componente.
- Criacao de tarefa continua exclusivamente por `/api/assistant/messages` e `AssistantService`.
- Texto continua funcional quando voz esta indisponivel.
- Piper e voz aprovados somente para uso interno; registrar licencas e exigir nova revisao antes de distribuicao.

---

### Task 1: Contratos, configuracao e dependencias opcionais

**Files:**
- Create: `app/assistant/voice/__init__.py`
- Create: `app/assistant/voice/provider.py`
- Create: `requirements-voice.txt`
- Modify: `app/config.py`
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Test: `tests/test_assistant_voice_contracts.py`

**Interfaces:**
- Produces: `TranscriptionResult`, `SynthesizedAudio`, `AudioTranscriber`, `SpeechSynthesizer` e erros `VoiceUnavailableError`, `InvalidAudioError`, `NoSpeechError`, `SuspiciousTranscriptionError`, `VoiceBusyError`.
- Produces configuracoes `voice_enabled`, `voice_model_dir`, `voice_whisper_model`, `voice_whisper_device`, `voice_whisper_compute_type`, limites e timeouts.

- [ ] **Step 1: Write the failing contract/config tests**

```python
def test_transcription_result_rejects_impossible_probabilities():
    with pytest.raises(ValidationError):
        TranscriptionResult(text="sim", language="pt", language_probability=1.5)

def test_voice_settings_have_cpu_safe_defaults(monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None)
    assert settings.voice_whisper_device == "cpu"
    assert settings.voice_whisper_compute_type == "int8"
    assert settings.voice_max_duration_seconds == 30
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_assistant_voice_contracts.py -q`
Expected: FAIL because `app.assistant.voice.provider` and settings do not exist.

- [ ] **Step 3: Implement minimal typed contracts and settings**

Use immutable Pydantic result models and `Protocol` methods:

```python
class AudioTranscriber(Protocol):
    def transcribe(self, path: Path) -> TranscriptionResult: ...

class SpeechSynthesizer(Protocol):
    def synthesize(self, text: str) -> SynthesizedAudio: ...
```

Pin `faster-whisper==1.2.1` and `piper-tts==1.8.0` only in `requirements-voice.txt`.

- [ ] **Step 4: Run GREEN and regression**

Run: `.venv/bin/python -m pytest tests/test_assistant_voice_contracts.py tests/test_assistant_routes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/assistant/voice app/config.py .env.example docker-compose.yml requirements-voice.txt tests/test_assistant_voice_contracts.py
git commit -m "feat: add optional voice provider contracts"
```

### Task 2: Validacao real de audio e politica de transcricao

**Files:**
- Create: `app/assistant/voice/audio.py`
- Create: `app/assistant/voice/policy.py`
- Test: `tests/test_assistant_voice_audio.py`
- Test: `tests/test_assistant_voice_policy.py`

**Interfaces:**
- Consumes: `InvalidAudioError`, `NoSpeechError`, `SuspiciousTranscriptionError`, `TranscriptionResult`.
- Produces: `inspect_audio(path, min_duration_seconds, max_duration_seconds) -> AudioMetadata` e `validate_transcription(result) -> str`.

- [ ] **Step 1: Write failing behavior tests**

Generate WAV fixtures in memory with the standard `wave` module. Assert valid mono PCM duration, reject random bytes, reject no audio stream, reject audio below 250 ms and stop decoding an audio stream after 30 seconds. Add policy cases for blank/punctuation, high no-speech probability and low-confidence short confirmation.

```python
with pytest.raises(SuspiciousTranscriptionError):
    validate_transcription(
        TranscriptionResult(
            text="pode criar",
            language="pt",
            language_probability=0.40,
            no_speech_probability=0.05,
            average_log_probability=-0.2,
        )
    )
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_assistant_voice_audio.py tests/test_assistant_voice_policy.py -q`
Expected: FAIL because validation modules are absent.

- [ ] **Step 3: Implement decode-bounded inspection and policy**

Use `av.open`, require exactly one audio stream, iterate decoded frames and accumulate `frame.samples / sample_rate`; raise immediately once the configured maximum is crossed. Normalize transcript with the existing `normalize_text`, require alphanumeric content, and apply stricter probability thresholds only to the short control vocabulary.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/python -m pytest tests/test_assistant_voice_audio.py tests/test_assistant_voice_policy.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/assistant/voice/audio.py app/assistant/voice/policy.py tests/test_assistant_voice_audio.py tests/test_assistant_voice_policy.py
git commit -m "feat: validate voice audio and transcripts"
```

### Task 3: Adaptadores faster-whisper e Piper

**Files:**
- Create: `app/assistant/voice/faster_whisper.py`
- Create: `app/assistant/voice/piper.py`
- Create: `app/assistant/voice/speech.py`
- Test: `tests/test_assistant_voice_providers.py`
- Test: `tests/test_assistant_voice_speech.py`

**Interfaces:**
- Consumes: contracts from Task 1 and transcript policy from Task 2.
- Produces: `FasterWhisperTranscriber`, `PiperSpeechSynthesizer`, `spoken_text(text: str, kind: str) -> str`.

- [ ] **Step 1: Write failing adapter tests with injected loaders**

Assert lazy single load, complete iteration of Whisper segments, aggregation of confidence values, WAV signature from Piper and deterministic shortening of task lists:

```python
assert spoken_text("Encontrei estas tarefas:\n- A\n- B", "text") == (
    "Encontrei 2 tarefas. Os detalhes estao na tela."
)
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_assistant_voice_providers.py tests/test_assistant_voice_speech.py -q`
Expected: FAIL because adapters are absent.

- [ ] **Step 3: Implement lazy providers without module-level heavy imports**

Import `faster_whisper.WhisperModel` and `piper.PiperVoice` only inside default loader functions. Cache each model per adapter instance and serialize model calls with `threading.Lock`. Piper writes to `io.BytesIO` through `wave.open` and returns `audio/wav`.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/python -m pytest tests/test_assistant_voice_providers.py tests/test_assistant_voice_speech.py -q`
Expected: PASS without requiring installed voice dependencies.

- [ ] **Step 5: Commit**

```bash
git add app/assistant/voice/faster_whisper.py app/assistant/voice/piper.py app/assistant/voice/speech.py tests/test_assistant_voice_providers.py tests/test_assistant_voice_speech.py
git commit -m "feat: add local speech providers"
```

### Task 4: Executor limitado e rotas de voz

**Files:**
- Create: `app/assistant/voice/runtime.py`
- Modify: `app/routers/assistant.py`
- Modify: `app/assistant/contracts.py`
- Test: `tests/test_assistant_voice_runtime.py`
- Test: `tests/test_assistant_voice_routes.py`

**Interfaces:**
- Consumes: audio inspection, providers, settings and existing assistant router.
- Produces: `BoundedVoiceExecutor.submit(callable, timeout)`, `/voice/status`, `/voice/transcriptions`, `/voice/speech`.

- [ ] **Step 1: Write failing runtime and route tests**

Test one active plus one queued job, immediate rejection of a third, event-loop responsiveness, timeout that does not free capacity until the worker actually completes, max upload bytes, temporary cleanup, invalid audio mappings and binary WAV response.

```python
heartbeat = asyncio.create_task(asyncio.sleep(0.01, result="alive"))
voice_call = asyncio.create_task(executor.submit(blocking_job, timeout=1))
assert await heartbeat == "alive"
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_assistant_voice_runtime.py tests/test_assistant_voice_routes.py -q`
Expected: FAIL because runtime and endpoints are absent.

- [ ] **Step 3: Implement bounded execution and thin routes**

Use a dedicated `ThreadPoolExecutor(max_workers=1)` and `threading.BoundedSemaphore(2)`. Acquire without waiting before submit; attach a done callback that releases capacity. Await an `asyncio.wrap_future` under `asyncio.wait_for(asyncio.shield(...))`, so request timeout does not start overlapping inference. Stream upload to a named temporary file with byte counting; transfer cleanup ownership to the background closure.

- [ ] **Step 4: Run GREEN and assistant route regression**

Run: `.venv/bin/python -m pytest tests/test_assistant_voice_runtime.py tests/test_assistant_voice_routes.py tests/test_assistant_routes.py tests/test_assistant_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/assistant/voice/runtime.py app/routers/assistant.py app/assistant/contracts.py tests/test_assistant_voice_runtime.py tests/test_assistant_voice_routes.py
git commit -m "feat: expose bounded local voice endpoints"
```

### Task 5: Sessao de voz no navegador

**Files:**
- Create: `app/static/assistant_voice.js`
- Create: `tests/js/assistant_voice.test.mjs`
- Modify: `app/main.py`
- Modify: `app/templates_web/assistant.html`
- Test: `tests/test_assistant_routes.py`

**Interfaces:**
- Consumes: voice endpoints and existing text form/DOM.
- Produces: `VoiceSessionController` with `start`, `finishUtterance`, `stopPlayback`, `stop` and guarded generation tokens.

- [ ] **Step 1: Write failing JavaScript behavior tests**

Using `node:test`, inject fake media, recorder, fetch and audio factories. Verify denied permission, automatic submit after silence, manual finish, capture suspended during playback, stop releases tracks, and late fetch/audio completion after `stop()` cannot play or restart listening.

```javascript
controller.start();
controller.stop();
transcription.resolve({ text: "Pode criar" });
await flushPromises();
assert.equal(audio.playCalls, 0);
assert.equal(recorder.startCalls, 0);
```

- [ ] **Step 2: Run RED**

Run: `node --test tests/js/assistant_voice.test.mjs`
Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement state machine and existing-design controls**

Mount `/assets` from `app/static`. Add semantic buttons “Iniciar conversa”, “Encerrar fala”, “Interromper audio”, “Repetir audio” and “Encerrar conversa”; keep the current form. Negotiate MediaRecorder MIME types, use analyser RMS for start/silence, and serialize stages `transcribe -> existing send message -> speech`. Every async continuation compares a captured generation before changing state.

- [ ] **Step 4: Run GREEN and HTML regression**

Run: `node --test tests/js/assistant_voice.test.mjs && .venv/bin/python -m pytest tests/test_assistant_routes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/static/assistant_voice.js app/main.py app/templates_web/assistant.html tests/js/assistant_voice.test.mjs tests/test_assistant_routes.py
git commit -m "feat: add local voice conversation session"
```

### Task 6: Componentes reais, fluxo isolado e documentacao

**Files:**
- Create: `scripts/download_assistant_voice_models.py`
- Create: `scripts/validate_assistant_voice_local.py`
- Create: `docs/assistente/validacao-voz-local.md`
- Modify: `docs/assistente/execucao.md`
- Modify: `docs/assistente/plano.md`
- Test: `tests/test_assistant_voice_local_runner.py`

**Interfaces:**
- Consumes: modelos reais, Ollama real, endpoints reais e banco temporario.
- Produces: downloads com origem/tamanho/hash registrados e relatorio JSON de tempos separados.

- [ ] **Step 1: Write failing runner isolation test**

Assert that the runner configures SQLite/output/model paths under a temporary root before importing `app`, seeds fictitious data and never references `propostas.db` or directories operacionais.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/test_assistant_voice_local_runner.py -q`
Expected: FAIL because scripts are absent.

- [ ] **Step 3: Implement download and validation scripts**

Download only `Systran/faster-whisper-small` through the adapter cache and the three arquivos da voz Faber por URLs oficiais, verificando tamanho total e SHA-256 conhecido do ONNX. A validacao sintetiza frases com Piper, transcreve audio real com faster-whisper e executa no banco temporario os fluxos criar, corrigir, confirmar, cancelar, silencio, audio invalido, falha de TTS depois de salvar e confirmacao repetida.

- [ ] **Step 4: Install optional dependencies and download authorized models**

Run:

```bash
.venv/bin/python -m pip install -r requirements-voice.txt
.venv/bin/python scripts/download_assistant_voice_models.py
```

Expected: apenas um modelo Whisper e uma voz Piper, total de modelos inferior a 2 GB.

- [ ] **Step 5: Run automated, real component and full regression validation**

Run:

```bash
.venv/bin/python scripts/validate_assistant_voice_local.py --output /tmp/assistente-voz-validacao.json
.venv/bin/python -m pytest -q
node --test tests/js/assistant_voice.test.mjs
```

Expected: fluxo real completo cria exatamente uma tarefa no banco temporario; suites passam.

- [ ] **Step 6: Document measured results and manual browser script**

Record hardware, versions, licenses, model sizes/origins, transcription/Ollama/synthesis/first-audio timings, synthetic versus human/mock evidence, Windows CPU instructions, secure-context rule and exact scenario:

1. “Crie uma tarefa para revisar o relatorio amanha.”
2. “Na verdade, depois de amanha.”
3. “Pode criar.”

Expected: exactly one task with corrected deadline and spoken success after persistence.

- [ ] **Step 7: Commit**

```bash
git add scripts/download_assistant_voice_models.py scripts/validate_assistant_voice_local.py docs/assistente tests/test_assistant_voice_local_runner.py
git commit -m "docs: validate local voice assistant"
```
