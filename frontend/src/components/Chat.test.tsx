import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ChatResponse } from "../types/api";
import { Chat } from "./Chat";

// The in-browser VAD needs WebAssembly + Web Audio; tests drive its callbacks by hand.
const vad = vi.hoisted(() => ({
  options: null as { onSpeechRealStart: () => void; onSpeechEnd: () => void } | null,
}));
vi.mock("@ricky0123/vad-web", () => ({
  MicVAD: {
    new: (options: { onSpeechRealStart: () => void; onSpeechEnd: () => void }) => {
      vad.options = options;
      return Promise.resolve({ destroy: () => Promise.resolve() });
    },
  },
}));

// Placeholder wording: tests must not carry real statute text.
const SESSION = "a".repeat(32);

const chatBody: ChatResponse = {
  session_id: SESSION,
  answer: "Alpha grounds apply [1]. See also [9].",
  grounded: true,
  kind: "answer",
  answer_en: "Alpha grounds apply [1]. See also [9].",
  model: "fake-llm",
  language: "en",
  romanized: false,
  english_query: "What grounds?",
  notices: [],
  emergency: false,
  clarification: null,
  analysis: { topic: "divorce", religion: "hindu", marriage_type: "unknown", in_scope: true, applicability: "applies" },
  validation: { invalid_citations: [], verified_quotes: 0, unquoted: [], regenerated: false, translation_ok: true },
  rounds: 1,
  trace: [
    { step: "understand", ms: 500, detail: {} },
    { step: "retrieve_1", ms: 100, detail: {} },
    { step: "generate", ms: 1400, detail: {} },
  ],
  sources: [
    {
      n: 1,
      chunk_id: "act1:s2",
      matched_chunk_ids: ["act1:s2:ss1"],
      doc_id: "act1",
      doc_type: "statute",
      title: "Example Act, 2000",
      label: "Section 2",
      court: null,
      citation: null,
      decision_date: null,
      page_start: 3,
      page_end: 3,
      text: "2. Grounds.— (1) alpha grounds apply.",
      score: 0.7,
      cited: true,
    },
    {
      n: 2,
      chunk_id: "sc-test:p4",
      matched_chunk_ids: ["sc-test:p4"],
      doc_id: "sc-test",
      doc_type: "judgment",
      title: "A v. B",
      label: "Para 4",
      court: "Supreme Court of India",
      citation: "[2024] 1 S.C.R. 1",
      decision_date: "2024-01-02",
      page_start: 5,
      page_end: 6,
      text: "4. Delta custody.",
      score: 0.6,
      cited: false,
    },
  ],
};

/** Fake microphone + MediaRecorder; returns the track so tests can check it is released. */
function stubMicrophone(): { stop: () => void } {
  const track = { stop: vi.fn() };
  vi.stubGlobal("navigator", {
    ...navigator,
    mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }) },
  });
  class FakeRecorder {
    static isTypeSupported = (type: string) => type === "audio/webm;codecs=opus";
    state = "inactive";
    mimeType = "audio/webm;codecs=opus";
    ondataavailable: ((e: { data: Blob }) => void) | null = null;
    onstop: (() => void) | null = null;
    start() {
      this.state = "recording";
    }
    stop() {
      this.state = "inactive";
      this.ondataavailable?.({ data: new Blob(["sound"], { type: this.mimeType }) });
      this.onstop?.();
    }
  }
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  return track;
}

function stubAudioPlayback(): string[] {
  const played: string[] = [];
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
  vi.spyOn(window.HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
    played.push(this.src);
    return Promise.resolve();
  });
  vi.spyOn(window.HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  return played;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("Chat", () => {
  it("posts the question and renders the cited answer with its sources", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(chatBody));
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await userEvent.type(screen.getByRole("textbox"), "  What grounds?  ");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("Example Act, 2000 — Section 2", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("What grounds?", { selector: "p" })).toBeInTheDocument(); // user's turn
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/chat/stream");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ message: "What grounds?" });

    const marker = screen.getByRole("link", { name: "[1]" });
    expect(marker.getAttribute("href")).toMatch(/^#src-\d+-1$/);
    const sources = screen.getByRole("list", { name: "Sources" });
    expect(within(sources).getAllByRole("listitem")).toHaveLength(2);
    expect(within(sources).getByText("(retrieved, not cited)")).toBeInTheDocument();
    expect(within(sources).getByText(/\[2024\] 1 S\.C\.R\. 1 · Supreme Court of India · 2024-01-02 · pp\. 5–6/)).toBeInTheDocument();
    expect(screen.getByText(/How this answer was made · English · fake-llm · 2\.0s/)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("");
  });

  it("sends the chosen language and toggles to the verified English original", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ ...chatBody, language: "hi", answer: "आधार [1]", answer_en: "Grounds [1]" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await userEvent.selectOptions(screen.getByRole("combobox"), "hi");
    await userEvent.type(screen.getByRole("textbox"), "आधार क्या हैं?{Enter}");

    expect(await screen.findByRole("button", { name: "अंग्रेज़ी मूल दिखाएँ" })).toBeInTheDocument(); // UI follows the language
    expect(screen.getByText(/Searched as:/)).toHaveTextContent("What grounds?");
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ message: "आधार क्या हैं?", language: "hi" });

    await userEvent.click(screen.getByRole("button", { name: "अंग्रेज़ी मूल दिखाएँ" }));
    expect(screen.getByText(/^Grounds/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "अनुवाद दिखाएँ" })).toBeInTheDocument();
  });

  it("asks a clarifying question and resends the question with the chosen fact", async () => {
    const clarification = {
      ...chatBody,
      kind: "clarification",
      answer: "Which law applies depends on your religion.",
      answer_en: "Which law applies depends on your religion.",
      sources: [],
      trace: [{ step: "understand", ms: 900, detail: {} }],
      clarification: {
        question: "Which law applies depends on your religion.",
        options: [
          { field: "religion", value: "hindu", label: "Hindu, Sikh, Jain or Buddhist" },
          { field: "religion", value: "muslim", label: "Muslim" },
        ],
      },
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(clarification))
      .mockResolvedValueOnce(jsonResponse(chatBody));
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await userEvent.type(screen.getByRole("textbox"), "Cruelty divorce?{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: "Muslim" }));

    expect(await screen.findByText("Example Act, 2000 — Section 2", { exact: false })).toBeInTheDocument();
    const [, second] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(JSON.parse(second.body as string)).toEqual({
      message: "Cruelty divorce?",
      facts: { religion: "muslim" },
      session_id: SESSION,
    });
    expect(screen.getAllByText("Muslim")).toHaveLength(2); // chosen option echoed as the user's turn
  });

  it("shows emergency notices as alerts before the answer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({ ...chatBody, emergency: true, notices: ["If you are in immediate danger, call 112."] }),
      ),
    );

    render(<Chat />);
    await userEvent.type(screen.getByRole("textbox"), "help{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("112");
  });

  it("warns when the answer cites no sources", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ ...chatBody, answer: "Not sure.", grounded: false, sources: [] })),
    );

    render(<Chat />);
    await userEvent.type(screen.getByRole("textbox"), "Anything{Enter}");

    expect(await screen.findByRole("note")).toHaveTextContent("cites no sources");
  });

  it("shows the backend's error detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "No index found; run `python -m scripts.build_index`" }, 503)),
    );

    render(<Chat />);
    await userEvent.type(screen.getByRole("textbox"), "Anything{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("scripts.build_index");
  });

  it("does not send an empty question", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox"), "   {Enter}");

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("continues the session for follow-ups and erases it on New conversation", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(chatBody))
      .mockResolvedValueOnce(jsonResponse(chatBody))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(jsonResponse({ ...chatBody, session_id: "b".repeat(32) }));
    vi.stubGlobal("fetch", fetchMock);
    const body = (i: number): unknown =>
      JSON.parse((fetchMock.mock.calls[i] as [string, RequestInit])[1].body as string);

    render(<Chat />);
    await userEvent.type(screen.getByRole("textbox"), "First?{Enter}");
    await vi.waitFor(() => expect(screen.getAllByRole("list", { name: "Sources" })).toHaveLength(1));
    await userEvent.type(screen.getByRole("textbox"), "And then?{Enter}");
    await vi.waitFor(() => expect(screen.getAllByRole("list", { name: "Sources" })).toHaveLength(2));

    expect(body(0)).toEqual({ message: "First?" });
    expect(body(1)).toEqual({ message: "And then?", session_id: SESSION });

    await userEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(screen.queryByText("First?", { selector: "p" })).not.toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect(url).toBe(`/api/v1/sessions/${SESSION}`);
    expect(init.method).toBe("DELETE");

    await userEvent.type(screen.getByRole("textbox"), "Fresh?{Enter}");
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
    expect(body(3)).toEqual({ message: "Fresh?" }); // no session id: a new conversation
  });

  it("shows live progress from the event stream, then the answer", async () => {
    let push: (text: string) => void = () => undefined;
    let close: () => void = () => undefined;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const enc = new TextEncoder();
        push = (text) => controller.enqueue(enc.encode(text));
        close = () => controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(stream, { headers: { "Content-Type": "text/event-stream" } })),
    );

    render(<Chat />);
    await userEvent.type(screen.getByRole("textbox"), "What grounds?{Enter}");

    push('event: step\ndata: {"step": "understand"}\n\n');
    expect(await screen.findByRole("status")).toHaveTextContent("Understanding your question…");
    push('event: step\ndata: {"step": "retrieve_1"}\n\nevent: st');
    expect(await screen.findByText("Searching the law and judgments…")).toBeInTheDocument();
    push(`ep\ndata: {"step": "generate"}\n\nevent: result\ndata: ${JSON.stringify(chatBody)}\n\n`);
    close();

    expect(await screen.findByText("Example Act, 2000 — Section 2", { exact: false })).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows an error event from the stream", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response('event: error\ndata: {"status": 503, "detail": "Language model unavailable: down"}\n\n', {
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );

    render(<Chat />);
    await userEvent.type(screen.getByRole("textbox"), "Anything{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent("Language model unavailable");
  });

  it("voice mode: a spoken question is transcribed, sent in the spoken language and its answer read aloud", async () => {
    const track = stubMicrophone();
    const played = stubAudioPlayback();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ text: "आधार क्या हैं?", language: "hi", language_probability: 0.97, duration_s: 2, model: "m" }),
      )
      .mockResolvedValueOnce(jsonResponse({ ...chatBody, language: "hi", answer: "अल्फा आधार [1]।" }))
      .mockResolvedValue(new Response("RIFF", { headers: { "Content-Type": "audio/wav" } }));
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await userEvent.click(screen.getByRole("button", { name: /speak/i }));
    await userEvent.click(await screen.findByRole("button", { name: /stop recording/i }));

    await vi.waitFor(() => expect(played).toHaveLength(1));
    const [asrUrl, asrInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(asrUrl).toBe("/api/v1/asr");
    const form = asrInit.body as FormData;
    expect(form.get("language")).toBeNull(); // auto: Whisper detects the language
    expect((form.get("audio") as File).name).toBe("question.webm");
    expect(track.stop).toHaveBeenCalled(); // microphone released

    const [chatUrl, chatInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(chatUrl).toBe("/api/v1/chat/stream"); // sent without pressing Ask
    expect(JSON.parse(chatInit.body as string)).toEqual({ message: "आधार क्या हैं?", language: "hi" });
    expect(screen.getByText("आधार क्या हैं?", { exact: false, selector: "p" })).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("");

    const [ttsUrl, ttsInit] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect(ttsUrl).toBe("/api/v1/tts"); // read aloud without pressing Listen
    expect(JSON.parse(ttsInit.body as string)).toEqual({ text: "अल्फा आधार [1]।", language: "hi" });
  });

  it("stops recording by itself when the speaker pauses, then sends the question", async () => {
    stubMicrophone();
    stubAudioPlayback();
    vad.options = null;
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ text: "What grounds?", language: "en", language_probability: 0.9, duration_s: 2, model: "m" }))
      .mockResolvedValueOnce(jsonResponse(chatBody))
      .mockResolvedValue(new Response("RIFF", { headers: { "Content-Type": "audio/wav" } }));
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await userEvent.click(screen.getByRole("button", { name: /speak/i }));
    expect(await screen.findByText(/sends your question when you pause/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    act(() => {
      vad.options?.onSpeechRealStart();
      vad.options?.onSpeechEnd(); // the speaker paused: no Stop click
    });

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual(["/api/v1/asr", "/api/v1/chat/stream", "/api/v1/tts"]);
    expect(screen.queryByText(/sends your question when you pause/)).not.toBeInTheDocument();
  });

  it("does not read typed questions' answers aloud on its own", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(chatBody));
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await userEvent.type(screen.getByRole("textbox"), "Q?{Enter}");
    expect(await screen.findByRole("button", { name: /listen/i })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("explains when the microphone is unavailable", async () => {
    vi.stubGlobal("navigator", {
      ...navigator,
      mediaDevices: { getUserMedia: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    vi.stubGlobal("MediaRecorder", class {});

    render(<Chat />);
    await userEvent.click(screen.getByRole("button", { name: /speak/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Microphone access was denied");
  });

  it("reads the answer aloud sentence by sentence and can stop", async () => {
    const played: string[] = [];
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: vi.fn() }));
    vi.spyOn(window.HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
      played.push(this.src);
      return Promise.resolve();
    });
    vi.spyOn(window.HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ ...chatBody, answer: "First sentence [1]. Second one.", answer_en: "First sentence [1]. Second one." }),
      )
      .mockResolvedValue(new Response("RIFF", { headers: { "Content-Type": "audio/wav" } }));
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await userEvent.type(screen.getByRole("textbox"), "Q?{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: /listen/i }));

    await vi.waitFor(() => expect(played).toHaveLength(1));
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/api/v1/tts");
    expect(JSON.parse(init.body as string)).toEqual({ text: "First sentence [1]. Second one.", language: "en" });
    expect(screen.getByRole("button", { name: /stop reading/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /stop reading/i }));
    expect(await screen.findByRole("button", { name: /listen/i })).toBeInTheDocument();
  });

  it("starts with a welcome screen whose examples can be asked with one click", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(chatBody));
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    expect(screen.getByText("Ask about Indian family law")).toBeInTheDocument();
    expect(screen.getByText(/Women helpline: 181/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Can a wife claim maintenance while the divorce case is pending?" }));

    await screen.findByText("Example Act, 2000 — Section 2", { exact: false });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ message: "Can a wife claim maintenance while the divorce case is pending?" });
    expect(screen.queryByText("Ask about Indian family law")).not.toBeInTheDocument();
  });

  it("switches the interface to Kannada", async () => {
    render(<Chat />);
    await userEvent.selectOptions(screen.getByRole("combobox"), "kn");

    expect(screen.getByRole("button", { name: "ಕೇಳಿ" })).toBeInTheDocument();
    expect(screen.getByText("ಭಾರತೀಯ ಕುಟುಂಬ ಕಾನೂನಿನ ಬಗ್ಗೆ ಕೇಳಿ")).toBeInTheDocument();
  });

  it("sends feedback for an answer", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(chatBody))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<Chat />);
    await userEvent.type(screen.getByRole("textbox"), "What grounds?{Enter}");
    await userEvent.click(await screen.findByRole("button", { name: "Not helpful" }));

    expect(await screen.findByText("Thanks for the feedback.")).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/api/v1/feedback");
    expect(JSON.parse(init.body as string)).toEqual({
      session_id: SESSION,
      rating: "down",
      language: "en",
      question: "What grounds?",
      answer_en: chatBody.answer_en,
    });
  });

  it("hides speech buttons when the server has no speech support", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(chatBody)));
    vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: vi.fn() } });
    vi.stubGlobal("MediaRecorder", class {});

    render(<Chat features={{ speechInput: false, speechOutput: false, loading: true }} />);
    expect(screen.queryByRole("button", { name: /speak/i })).not.toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("still loading");
    await userEvent.type(screen.getByRole("textbox"), "Q?{Enter}");
    await screen.findByText("Example Act, 2000 — Section 2", { exact: false });

    expect(screen.queryByRole("button", { name: /listen/i })).not.toBeInTheDocument();
  });
});
