import type { ChatRequest, ChatResponse, HealthResponse, LanguageCode, ReadyResponse, UserFacts } from "../types/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
const DEFAULT_TIMEOUT_MS = 10_000;
// Local LLM generation can take a while (first call also loads the models).
const CHAT_TIMEOUT_MS = 200_000;

export class ApiError extends Error {
  readonly status: number | undefined;
  readonly requestId: string | null;

  constructor(message: string, status?: number, requestId: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
}

/** FastAPI errors carry `{"detail": "..."}`; show that text when it is a plain string. */
async function errorDetail(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // non-JSON error body
  }
  return null;
}

/** fetch with a timeout and the caller's abort signal; network failures become ApiError. */
async function send(path: string, init: RequestInit, signal: AbortSignal | undefined, timeoutMs: number) {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  signal?.addEventListener("abort", () => controller.abort(), { once: true });
  const done = () => clearTimeout(timer);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, { ...init, signal: controller.signal });
    if (!response.ok) {
      done();
      const detail = await errorDetail(response);
      throw new ApiError(
        detail ?? `Request failed with status ${response.status}.`,
        response.status,
        response.headers.get("X-Request-ID"),
      );
    }
    return { response, done, timedOut: () => timedOut };
  } catch (err) {
    done();
    if (err instanceof ApiError) throw err;
    throw new ApiError(timedOut ? "The backend took too long to respond." : "Cannot reach the backend.");
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
  const { response, done } = await send(
    path,
    {
      method,
      headers:
        body === undefined
          ? { Accept: "application/json" }
          : { Accept: "application/json", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
    signal,
    timeoutMs,
  );
  try {
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  } finally {
    done();
  }
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request<HealthResponse>("/health", { signal });
}

export function getReady(signal?: AbortSignal): Promise<ReadyResponse> {
  return request<ReadyResponse>("/ready", { signal });
}

export interface FeedbackBody {
  session_id: string;
  rating: "up" | "down";
  language: LanguageCode;
  question: string;
  answer_en: string;
  comment?: string;
}

export function postFeedback(body: FeedbackBody): Promise<void> {
  return request<void>("/feedback", { method: "POST", body });
}

export interface ChatOptions {
  language?: LanguageCode | null;
  facts?: UserFacts | null;
}

function chatBody(message: string, options: ChatOptions, sessionId: string | null): ChatRequest {
  const body: ChatRequest = { message };
  if (options.language) body.language = options.language;
  if (options.facts) body.facts = options.facts;
  if (sessionId) body.session_id = sessionId;
  return body;
}

export function postChat(
  message: string,
  options: ChatOptions = {},
  sessionId: string | null = null,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: chatBody(message, options, sessionId),
    signal,
    timeoutMs: CHAT_TIMEOUT_MS,
  });
}

interface SseEvent {
  event: string;
  data: string;
}

function parseSse(block: string): SseEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return data.length ? { event, data: data.join("\n") } : null;
}

/**
 * POST /chat/stream: calls `onStep` as each pipeline stage starts (live progress), resolves
 * with the final answer. A plain JSON reply (e.g. from a proxy without streaming) also works.
 */
export async function streamChat(
  message: string,
  options: ChatOptions = {},
  sessionId: string | null = null,
  onStep: (step: string) => void = () => undefined,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const { response, done, timedOut } = await send(
    "/chat/stream",
    {
      method: "POST",
      headers: { Accept: "text/event-stream, application/json", "Content-Type": "application/json" },
      body: JSON.stringify(chatBody(message, options, sessionId)),
    },
    signal,
    CHAT_TIMEOUT_MS,
  );
  try {
    if (!response.body || (response.headers.get("Content-Type") ?? "").includes("application/json")) {
      return (await response.json()) as ChatResponse;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch {
        throw new ApiError(timedOut() ? "The backend took too long to respond." : "The connection was interrupted.");
      }
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      let end: number;
      while ((end = buffer.search(/\r?\n\r?\n/)) >= 0) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end).replace(/^\r?\n\r?\n/, "");
        const sse = parseSse(block);
        if (!sse) continue;
        if (sse.event === "step") {
          onStep((JSON.parse(sse.data) as { step: string }).step);
        } else if (sse.event === "result") {
          return JSON.parse(sse.data) as ChatResponse;
        } else if (sse.event === "error") {
          const err = JSON.parse(sse.data) as { status?: number; detail?: string };
          throw new ApiError(err.detail ?? "The answer failed.", err.status);
        }
      }
    }
    throw new ApiError("The answer stream ended unexpectedly.");
  } finally {
    done();
  }
}

export interface TranscriptResponse {
  text: string;
  language: LanguageCode;
  language_probability: number;
  duration_s: number;
  model: string;
}

/** Speech → text. Voice mode sends the transcript as a question straight away. */
export async function transcribe(
  audio: Blob,
  language: LanguageCode | null = null,
  signal?: AbortSignal,
): Promise<TranscriptResponse> {
  const form = new FormData();
  const ext = audio.type.includes("ogg") ? "ogg" : audio.type.includes("mp4") ? "m4a" : "webm";
  form.append("audio", audio, `question.${ext}`);
  if (language) form.append("language", language);
  // No Content-Type header: the browser sets the multipart boundary.
  const { response, done } = await send(
    "/asr",
    { method: "POST", headers: { Accept: "application/json" }, body: form },
    signal,
    120_000,
  );
  try {
    return (await response.json()) as TranscriptResponse;
  } finally {
    done();
  }
}

/** Text → speech (WAV). Send one or a few sentences per call so playback starts early. */
export async function synthesize(text: string, language: LanguageCode, signal?: AbortSignal): Promise<Blob> {
  const { response, done } = await send(
    "/tts",
    {
      method: "POST",
      headers: { Accept: "audio/wav", "Content-Type": "application/json" },
      body: JSON.stringify({ text, language }),
    },
    signal,
    60_000,
  );
  try {
    return await response.blob();
  } finally {
    done();
  }
}

/** Erase a conversation (messages and remembered facts) on the server. */
export function deleteSession(sessionId: string): Promise<void> {
  return request<void>(`/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
}
