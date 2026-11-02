import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, type ChatOptions, deleteSession, streamChat } from "../services/api";
import type { ChatResponse } from "../types/api";

export type ChatMessage =
  | { id: number; role: "user"; text: string; voice: boolean }
  | { id: number; role: "assistant"; response: ChatResponse; question: string; options: ChatOptions; voice: boolean }
  | { id: number; role: "error"; text: string };

type WithoutId<T> = T extends unknown ? Omit<T, "id"> : never;

/**
 * Conversation state. The server remembers the session (recent turns + clarification answers),
 * so follow-up questions work; `reset` starts over and erases the old session on the server.
 */
export function useChat(): {
  messages: ChatMessage[];
  pending: boolean;
  /** The pipeline step running now (live progress), or null. */
  step: string | null;
  /** `voice`: the question was spoken, so the answer is read aloud too. */
  send: (text: string, options?: ChatOptions, echo?: string, voice?: boolean) => void;
  reset: () => void;
} {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState(false);
  const [step, setStep] = useState<string | null>(null);
  const nextId = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const sessionId = useRef<string | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  const send = useCallback(
    (text: string, options: ChatOptions = {}, echo?: string, voice = false) => {
      const message = text.trim();
      if (!message || pending) return;

      const push = (entry: WithoutId<ChatMessage>) => {
        const id = nextId.current++;
        setMessages((prev) => [...prev, { ...entry, id } as ChatMessage]);
      };

      // `echo` shows what the user chose (e.g. a clarification option) instead of the resent text.
      push({ role: "user", text: echo ?? message, voice });
      setPending(true);
      setStep(null);
      controller.current = new AbortController();
      const { signal } = controller.current;

      streamChat(message, options, sessionId.current, (s) => !signal.aborted && setStep(s), signal)
        .then((response) => {
          if (signal.aborted) return;
          sessionId.current = response.session_id;
          push({ role: "assistant", response, question: message, options, voice });
        })
        .catch((err: unknown) => {
          if (signal.aborted) return;
          push({ role: "error", text: err instanceof ApiError ? err.message : "Unexpected error." });
        })
        .finally(() => {
          if (signal.aborted) return;
          setPending(false);
          setStep(null);
        });
    },
    [pending],
  );

  const reset = useCallback(() => {
    controller.current?.abort();
    const old = sessionId.current;
    sessionId.current = null;
    setMessages([]);
    setPending(false);
    setStep(null);
    if (old) deleteSession(old).catch(() => undefined); // best effort; it also expires on its own
  }, []);

  return { messages, pending, step, send, reset };
}
