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

describe("App", () => {
  it("shows backend details when the health check succeeds", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(healthBody));
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
    expect(screen.getByText("development")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/health", expect.any(Object));
  });

  it("shows an error when the backend returns a failure status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, 503)));

    render(<App />);

    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(screen.getByText("Request failed with status 503.")).toBeInTheDocument();
  });

  it("recovers on retry after a network error", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(jsonResponse(healthBody));
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByText("Cannot reach the backend.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Connected")).toBeInTheDocument();
  });

  it("always shows the legal-information disclaimer", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));

    render(<App />);

    expect(screen.getByText(/not legal advice/i)).toBeInTheDocument();
  });
});
