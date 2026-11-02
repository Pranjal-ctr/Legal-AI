import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import App from "./App";

const healthBody = {
  status: "ok",
  app_name: "Kanoon AI",
  version: "0.1.0",
  environment: "development",
  timestamp: "2026-10-07T00:00:00Z",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "X-Request-ID": "abc123" },
  });
}

function backend(ready: Record<string, string>) {
  return vi.fn((url: string) =>
    Promise.resolve(jsonResponse(url.endsWith("/ready") ? ready : healthBody)),
  );
}

const ALL_READY = { answers: "ready", speech_input: "ready", speech_output: "ready" };

describe("App", () => {
  it("shows Ready when the backend and models are ready", async () => {
    const fetchMock = backend(ALL_READY);
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/health", expect.any(Object));
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/ready", expect.any(Object));
  });

  it("shows that models are loading and tells the user", async () => {
    vi.stubGlobal("fetch", backend({ ...ALL_READY, answers: "loading" }));

    render(<App />);

    expect(await screen.findByText("Loading models…")).toBeInTheDocument();
    expect(screen.getByText(/still loading/)).toBeInTheDocument();
  });

  it("marks speech as off when it is unavailable", async () => {
    vi.stubGlobal("fetch", backend({ ...ALL_READY, speech_input: "unavailable" }));

    render(<App />);

    expect(await screen.findByText("Ready · speech off")).toBeInTheDocument();
  });

  it("shows an error when the backend returns a failure status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 503)));

    render(<App />);

    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(screen.getByText("Request failed with status 503.")).toBeInTheDocument();
  });

  it("recovers on retry after a network error", async () => {
    const ok = backend(ALL_READY);
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockImplementation(ok);
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByText("Cannot reach the backend.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Ready")).toBeInTheDocument();
  });

  it("always shows the legal-information disclaimer", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));

    render(<App />);

    expect(screen.getByText(/not legal advice/i)).toBeInTheDocument();
  });
});
