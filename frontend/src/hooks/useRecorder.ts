import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, transcribe, type TranscriptResponse } from "../services/api";
import type { LanguageCode } from "../types/api";

export type RecorderState = "idle" | "recording" | "transcribing";

const MAX_RECORDING_MS = 60_000; // the backend rejects longer recordings
/** Give up (and send nothing) if no speech starts within this time of listening. */
const NO_SPEECH_MS = 8_000;
/** Silence after speech that ends the question (pauses shorter than this are kept). */
const PAUSE_MS = 1_500;
/** Served from our own origin (copied by scripts/copy-vad-assets.mjs). */
const VAD_ASSETS = `${import.meta.env.BASE_URL}vad/`;

function pickMimeType(): string | undefined {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  return candidates.find((type) => MediaRecorder.isTypeSupported?.(type));
}

export function speechInputSupported(): boolean {
  return typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && "MediaRecorder" in window;
}

interface Detector {
  destroy: () => Promise<void>;
}

/**
 * Silero VAD (in the browser) on the recording's own stream: calls `onPause` once the speaker
 * stops talking. The model and ONNX runtime load on first use (dynamic import, ~15 MB, cached).
 */
async function startDetector(
  stream: MediaStream,
  events: { onSpeech: () => void; onPause: () => void },
): Promise<Detector> {
  const { MicVAD } = await import("@ricky0123/vad-web");
  return MicVAD.new({
    model: "v5",
    baseAssetPath: VAD_ASSETS,
    onnxWASMBasePath: VAD_ASSETS,
    ortConfig: (ort) => {
      ort.env.logLevel = "error";
      ort.env.wasm.numThreads = 1; // no worker threads (would need cross-origin isolation)
    },
    // The MediaRecorder owns the microphone: share its stream, never stop it here.
    getStream: () => Promise.resolve(stream),
    pauseStream: () => Promise.resolve(),
    resumeStream: () => Promise.resolve(stream),
    redemptionMs: PAUSE_MS,
    minSpeechMs: 300,
    onSpeechRealStart: events.onSpeech,
    onSpeechEnd: events.onPause,
    startOnLoad: true,
  });
}

/**
 * Record from the microphone, then transcribe on the server. Recording stops by itself when the
 * speaker pauses (`autoStop` once the detector is running); the user can always stop it by hand.
 */
export function useRecorder(onTranscript: (result: TranscriptResponse) => void): {
  state: RecorderState;
  error: string | null;
  /** True while pause detection is listening (otherwise the user stops the recording). */
  autoStop: boolean;
  start: (language: LanguageCode | null) => Promise<void>;
  stop: () => void;
} {
  const [state, setState] = useState<RecorderState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [autoStop, setAutoStop] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const maxTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const silenceTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const detector = useRef<Detector | null>(null);
  const discard = useRef(false);
  const controller = useRef<AbortController | null>(null);

  const release = useCallback(() => {
    clearTimeout(maxTimer.current);
    clearTimeout(silenceTimer.current);
    const vad = detector.current;
    detector.current = null;
    setAutoStop(false);
    vad?.destroy().catch(() => undefined);
  }, []);

  const stop = useCallback(() => {
    release();
    if (recorder.current?.state === "recording") recorder.current.stop();
  }, [release]);

  useEffect(
    () => () => {
      controller.current?.abort();
      discard.current = true;
      stop();
    },
    [stop],
  );

  const start = useCallback(
    async (language: LanguageCode | null) => {
      setError(null);
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
      } catch {
        setError("Microphone access was denied or no microphone was found.");
        return;
      }
      const mimeType = pickMimeType();
      const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const chunks: Blob[] = [];
      discard.current = false;
      rec.ondataavailable = (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      };
      rec.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        if (discard.current) {
          setState("idle");
          return;
        }
        const audio = new Blob(chunks, { type: rec.mimeType || mimeType || "audio/webm" });
        if (audio.size === 0) {
          setState("idle");
          setError("Nothing was recorded.");
          return;
        }
        setState("transcribing");
        controller.current = new AbortController();
        transcribe(audio, language, controller.current.signal)
          .then((result) => {
            if (!result.text.trim()) setError("No speech was recognised. Please try again.");
            else onTranscript(result);
          })
          .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Transcription failed."))
          .finally(() => setState("idle"));
      };
      recorder.current = rec;
      rec.start();
      setState("recording");
      maxTimer.current = setTimeout(stop, MAX_RECORDING_MS);

      // Pause detection; if it cannot load, the recording simply waits for the Stop button.
      startDetector(stream, {
        onSpeech: () => clearTimeout(silenceTimer.current),
        onPause: stop,
      })
        .then((vad) => {
          if (recorder.current !== rec || rec.state !== "recording") {
            void vad.destroy().catch(() => undefined); // stopped while the model was loading
            return;
          }
          detector.current = vad;
          setAutoStop(true);
          silenceTimer.current = setTimeout(() => {
            discard.current = true;
            setError("No speech was heard. Press Speak and try again.");
            stop();
          }, NO_SPEECH_MS);
        })
        .catch((err: unknown) => console.warn("pause detection unavailable; stop the recording by hand", err));
    },
    [onTranscript, stop],
  );

  return { state, error, autoStop, start, stop };
}
