# ADR 0009: Phases 9–10 speech, faster-whisper ASR and MMS-TTS on CPU

- **Status:** Accepted (Phases 9–10, 2026-11-02)

## Context

Users should be able to ask by voice and hear answers in English, Hindi and Kannada. The
8 GB GPU is full: Ollama gemma4:e4b plus the bge reranker use about 7.6 GB, and Ollama sizes
itself to the free VRAM. Putting speech models on the GPU would push LLM layers to the CPU and
slow every answer. The machine has 16 CPU cores. The C: drive is full, so all weights live
under `models/` on D:.

## Decision

**ASR** (`app/providers/asr.py`, `POST /api/v1/asr`, multipart, max 10 MB / 60 s):

- faster-whisper `large-v3-turbo`, CTranslate2 int8 on CPU (`LEGALAI_ASR_*`), weights in
  `models/whisper`.
- Audio is decoded with our own PyAV decoder (faster-whisper 1.2's helper passes an argument
  that PyAV ≥ 15 removed), resampled to 16 kHz mono, and capped while decoding.
- Silero VAD keeps only speech (silence is where Whisper invents words).
- **Single encoder pass** for clips ≤ 30 s: language detection (restricted to en/hi/kn) and
  decoding share one encoding. `WhisperModel.transcribe` encodes twice when the language is
  unknown. Measured: auto-detect drops from 16.9 s to 8.2 s for a 5 s clip.
- **Ambiguous language:** when the top language is below 0.8, the runner-up is also decoded from
  the same encoding, and the transcript with the higher length-normalised log-probability wins.
  This fixes Kannada speech that Whisper scores as Hindi (it then wrote phonetic Devanagari).
- The transcript is put into the input box for the user to check. It is never sent
  automatically: a misheard legal term should be corrected, not answered.

**TTS** (`app/providers/tts.py`, `POST /api/v1/tts` → WAV):

- Meta MMS-TTS (VITS) `facebook/mms-tts-{eng,hin,kan}` via transformers on CPU, about 145 MB
  each, an LRU cache of 128 clips, and a fixed seed (same text, same audio).
- **The voices cannot read punctuation, Latin script (hi/kn) or most digits.**
  `app/nlp/speech_text.py` therefore removes `[n]` markers, reads `"<English law text>"
  (<translation>)` as the translation only, writes numbers out (English words; Hindi/Kannada
  digit by digit), and splits text into clauses joined with 0.25 s pauses.
- The UI requests audio sentence by sentence (≤ 300 characters) and prefetches the next chunk
  while one plays, so audio starts after about 1–3 s.
- **Licence:** MMS-TTS weights are **CC-BY-NC 4.0**. They are acceptable for this research
  prototype and must be replaced (for example by AI4Bharat Indic-TTS / Parler-TTS) for any
  commercial use.

## Evidence (live, 2026-11-02; TTS-generated speech fed back to ASR)

| lang | said → heard |
|---|---|
| en | exact |
| hi | one letter wrong ("क्रूरता" → "कुरूरता"), detected hi (p 0.98) |
| kn | detected kn after the ambiguity check, small spelling errors ("ಅಡಿಯಲ್ಲಿ" → "ಅಗಿಯಲ್ಲಿ") |

ASR takes 8–12 s on CPU and TTS 1.5–3.5 s per sentence. Synthetic speech is not real speech,
so Phase 13 should record real hi/kn samples.

## Consequences

- Kannada ASR quality is Whisper's weakest. A Kannada-tuned Whisper (converted to CTranslate2)
  can be added per language later behind the same `ASRProvider`.
- Hindi/Kannada numbers are read digit by digit ("धारा एक तीन" for s.13): correct but stilted.
- The `speech` extra (faster-whisper, transformers, torch) is optional. Without it, `/asr` and
  `/tts` answer 503, and CI tests use fakes.
