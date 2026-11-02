import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, synthesize } from "../services/api";
import type { LanguageCode } from "../types/api";

const MAX_CHUNK = 300;

/** Sentences grouped into chunks of at most ~300 characters (the first chunk plays early). */
export function splitForSpeech(text: string): string[] {
  const sentences = text
    .split(/(?<=[.!?।])\s+|\n+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const chunks: string[] = [];
  for (const sentence of sentences) {
    const last = chunks.at(-1);
    if (last !== undefined && last.length + sentence.length + 1 <= MAX_CHUNK) chunks[chunks.length - 1] = `${last} ${sentence}`;
    else chunks.push(sentence.slice(0, 1000));
  }
  return chunks;
}

interface Playback {
  key: number;
  controller: AbortController;
  audio: HTMLAudioElement | null;
}

/** Reads one message at a time aloud; the next chunk is fetched while the current one plays. */
export function useSpeaker(): {
  speaking: number | null;
  /** The last playback error, with the message it belongs to. */
  error: { key: number; message: string } | null;
  speak: (key: number, text: string, language: LanguageCode) => void;
  stop: () => void;
} {
  const [speaking, setSpeaking] = useState<number | null>(null);
  const [error, setError] = useState<{ key: number; message: string } | null>(null);
  const current = useRef<Playback | null>(null);

  const stop = useCallback(() => {
    const playback = current.current;
    current.current = null;
    if (playback) {
      playback.controller.abort();
      playback.audio?.pause();
    }
    setSpeaking(null);
  }, []);

  useEffect(() => stop, [stop]);

  const speak = useCallback(
    (key: number, text: string, language: LanguageCode) => {
      stop();
      const [first, ...rest] = splitForSpeech(text);
      if (first === undefined) return;
      const playback: Playback = { key, controller: new AbortController(), audio: null };
      current.current = playback;
      const { signal } = playback.controller;
      setSpeaking(key);
      setError(null);

      const play = (blob: Blob) =>
        new Promise<void>((resolve, reject) => {
          const url = URL.createObjectURL(blob);
          const audio = new Audio(url);
          playback.audio = audio;
          const finish = () => {
            URL.revokeObjectURL(url);
            resolve();
          };
          audio.onended = finish;
          audio.onerror = () => {
            URL.revokeObjectURL(url);
            reject(new Error("playback failed"));
          };
          signal.addEventListener("abort", finish, { once: true });
          Promise.resolve(audio.play()).catch(reject);
        });

      void (async () => {
        try {
          let next = synthesize(first, language, signal);
          for (let i = 0; i <= rest.length; i++) {
            const blob = await next;
            if (signal.aborted) return;
            const following = rest[i];
            if (following !== undefined) next = synthesize(following, language, signal);
            await play(blob);
            if (signal.aborted) return;
          }
        } catch (err) {
          if (!signal.aborted)
            setError({ key, message: err instanceof ApiError ? err.message : "Could not play the audio." });
        } finally {
          if (current.current === playback) {
            current.current = null;
            setSpeaking(null);
          }
        }
      })();
    },
    [stop],
  );

  return { speaking, error, speak, stop };
}
