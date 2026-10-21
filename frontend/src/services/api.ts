import type { HealthResponse } from "../types/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
const DEFAULT_TIMEOUT_MS = 10_000;

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

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, DEFAULT_TIMEOUT_MS);
  signal?.addEventListener("abort", () => controller.abort(), { once: true });

  try {
    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
    } catch {
      throw new ApiError(timedOut ? "The backend took too long to respond." : "Cannot reach the backend.");
    }

    const requestId = response.headers.get("X-Request-ID");
    if (!response.ok) {
      throw new ApiError(`Request failed with status ${response.status}.`, response.status, requestId);
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request<HealthResponse>("/health", signal);
}
