# ADR 0013 — Hands-free voice questions: in-browser VAD ends the recording

Date: 2026-11-02 · Status: accepted

## Context

Voice mode (2026-11-02) sends a spoken question as soon as it is transcribed and reads the answer
aloud, but the user still had to press **Stop** to end the recording. The user asked for the
recording to end by itself when they stop talking, and chose a speech model over a simple
volume threshold (background noise such as fans or traffic defeats a volume threshold).

This supersedes ADR 0009's rule that a transcript is never sent automatically. That rule guarded
against answering a misheard legal term. The user chose hands-free use instead. The mitigation is
that the transcript is shown as the user's message (marked 🎤), so a mishearing is visible next to
the answer.

## Decision

- **Silero VAD v5 in the browser** via `@ricky0123/vad-web` 0.0.31 (pinned; brings
  `onnxruntime-web` 1.31). It runs on the recording's own `MediaStream`, so the existing
  `MediaRecorder` → `/api/v1/asr` path, and the backend, are unchanged: the VAD is only a trigger.
- **Behaviour** (`frontend/src/hooks/useRecorder.ts`): the recording stops 1.5 s after speech ends
  (`redemptionMs`; shorter pauses are kept); blips under 300 ms are ignored; if no speech starts
  within 8 s it stops and sends nothing; the 60 s cap stays. Stop still works by hand. The UI
  shows "Listening… it sends your question when you pause" while the detector runs.
- **Lazy, self-hosted assets.** The VAD code is a separate chunk loaded by dynamic import on the
  first mic press (~117 KB gzipped). `scripts/copy-vad-assets.mjs` (npm `predev`/`prebuild`)
  copies the model (`silero_vad_v5.onnx`, 2.3 MB), the AudioWorklet and the ONNX runtime
  (`ort-wasm-simd-threaded.{mjs,wasm}`, 14.8 MB) into `public/vad/` (git-ignored), served from our
  own origin, then cached by the browser. No CDN.
- **Single-threaded ONNX runtime** (`numThreads = 1`): threads would need cross-origin isolation
  (COEP); one thread is ample for a 32 ms-frame model.
- **CSP:** production `script-src` gains `'wasm-unsafe-eval'`, which permits compiling
  WebAssembly only (JavaScript `eval` stays blocked).
- **Fallback:** if the detector fails to load, recording continues and waits for Stop.

## Consequences

- First mic press downloads ~17 MB once (instant on localhost; cached afterwards).
- A pause longer than 1.5 s mid-sentence sends the question early; `PAUSE_MS` is one constant.
- Verified in Chrome with a synthetic microphone (TTS audio of an English question): the VAD
  loaded in ~0.4 s, recording ended ~1.2 s after the speech, then ASR (9.9 s) → answer (7.1 s,
  Gemini) → first audio chunk (3.9 s). Not yet tried with a real microphone and room noise.
- Same test in Hindi (क्रूरता question → s.13(1)(ia), answer in Hindi, read aloud) and Kannada
  (custody question → clarification read aloud → "Hindu" → s.26 answer read aloud). ASR adds small
  spelling slips (कुरूरता, ವಿಚ್ಚೆದನ) that did not hurt retrieval. Seen once: the Kannada answer
  (gemini-3.5-flash-lite translation) contained one Bengali-script word (বিধান); worth a script check.
- Tests mock the library (`vi.mock("@ricky0123/vad-web")`); jsdom has no WebAssembly audio.
