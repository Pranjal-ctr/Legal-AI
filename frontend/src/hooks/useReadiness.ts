import { useCallback, useEffect, useState } from "react";

import { ApiError, getHealth, getReady } from "../services/api";
import type { HealthResponse, ReadyResponse } from "../types/api";

export type ReadinessState =
  | { status: "checking" }
  | { status: "online"; health: HealthResponse; ready: ReadyResponse }
  | { status: "offline"; error: ApiError };

const FAST_POLL_MS = 3_000; // while models load
const SLOW_POLL_MS = 30_000;

/** Backend liveness + per-feature readiness, polled (quickly while models are loading). */
export function useReadiness(): { state: ReadinessState; retry: () => void } {
  const [state, setState] = useState<ReadinessState>({ status: "checking" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const [health, ready] = await Promise.all([getHealth(controller.signal), getReady(controller.signal)]);
        setState({ status: "online", health, ready });
        const loading = Object.values(ready).includes("loading");
        timer = setTimeout(() => void poll(), loading ? FAST_POLL_MS : SLOW_POLL_MS);
      } catch (err) {
        if (controller.signal.aborted) return;
        setState({ status: "offline", error: err instanceof ApiError ? err : new ApiError("Unexpected error.") });
      }
    };
    setState({ status: "checking" });
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, retry };
}

/** Feature flags for the chat derived from readiness (optimistic while unknown). */
export function featuresOf(state: ReadinessState): { speechInput: boolean; speechOutput: boolean; loading: boolean } {
  if (state.status !== "online") return { speechInput: true, speechOutput: true, loading: false };
  const usable = (r: string) => r === "ready" || r === "loading" || r === "on_demand";
  return {
    speechInput: usable(state.ready.speech_input),
    speechOutput: usable(state.ready.speech_output),
    loading: state.ready.answers === "loading",
  };
}
