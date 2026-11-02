import { type FormEvent, type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";

import { type ChatMessage, useChat } from "../hooks/useChat";
import { speechInputSupported, useRecorder } from "../hooks/useRecorder";
import { useSpeaker } from "../hooks/useSpeaker";
import { EXAMPLES, I18nContext, STRINGS, useT } from "../i18n";
import { postFeedback, type TranscriptResponse } from "../services/api";
import type { ChatResponse, ClarifyOption, LanguageCode, Source } from "../types/api";

const MAX_LENGTH = 2000;

const LANGUAGE_NAMES: Record<LanguageCode, string> = { en: "English", hi: "हिन्दी", kn: "ಕನ್ನಡ" };

const STEP_LABEL: Record<string, string> = {
  translate_query: "Translated the question to English",
  understand: "Understood the question",
  retrieve_1: "Searched the sources",
  assess: "Checked the evidence",
  retrieve_2: "Searched again for missing information",
  generate: "Wrote and verified the answer",
  translate_answer: "Translated the answer",
};

const LINK = "text-xs font-medium text-indigo-700 hover:underline dark:text-indigo-300";

export interface ChatFeatures {
  speechInput: boolean;
  speechOutput: boolean;
  /** Models are still loading on the server. */
  loading: boolean;
}

type Speaker = ReturnType<typeof useSpeaker>;
type AssistantEntry = Extract<ChatMessage, { role: "assistant" }>;

/** Renders `[n]` markers as links to the matching source below the answer. */
function AnswerText({ messageId, text }: { messageId: number; text: string }) {
  const parts = text.split(/(\[\d+\])/);
  return (
    <p className="whitespace-pre-line leading-relaxed">
      {parts.map((part, i) => {
        const match = /^\[(\d+)\]$/.exec(part);
        if (!match) return part;
        return (
          <a
            key={i}
            href={`#src-${messageId}-${match[1]}`}
            className="mx-0.5 align-super text-xs font-semibold text-indigo-700 hover:underline dark:text-indigo-300"
          >
            [{match[1]}]
          </a>
        );
      })}
    </p>
  );
}

function sourceMeta(source: Source): string {
  const parts = [source.citation, source.court, source.decision_date].filter(Boolean);
  const pages = source.page_start === source.page_end ? `p. ${source.page_start}` : `pp. ${source.page_start}–${source.page_end}`;
  return [...parts, pages].join(" · ");
}

function SourceList({ messageId, sources }: { messageId: number; sources: Source[] }) {
  const t = useT();
  return (
    <ol className="mt-3 space-y-2" aria-label={t.sources}>
      {sources.map((source) => (
        <li key={source.n} id={`src-${messageId}-${source.n}`}>
          <details
            className={`rounded-lg border px-3 py-2 text-sm ${
              source.cited
                ? "border-indigo-200 bg-indigo-50/60 dark:border-indigo-900 dark:bg-indigo-950/40"
                : "border-slate-200 opacity-75 dark:border-slate-700"
            }`}
          >
            <summary className="cursor-pointer">
              <span className="font-semibold">[{source.n}]</span> {source.title} — {source.label}
              {!source.cited && <span className="ml-2 text-xs text-slate-500">{t.notCited}</span>}
            </summary>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{sourceMeta(source)}</p>
            <blockquote
              lang="en"
              className="mt-2 max-h-80 overflow-y-auto border-l-2 border-slate-300 pl-3 whitespace-pre-line text-slate-700 dark:border-slate-600 dark:text-slate-300"
            >
              {source.text}
            </blockquote>
          </details>
        </li>
      ))}
    </ol>
  );
}

function Notices({ response }: { response: ChatResponse }) {
  if (response.notices.length === 0) return null;
  return (
    <ul className="mb-3 space-y-2" aria-label="Notices">
      {response.notices.map((notice) => {
        const urgent = response.emergency && /112/.test(notice);
        return (
          <li
            key={notice}
            role={urgent ? "alert" : "note"}
            className={`rounded-lg px-3 py-2 text-sm ${
              urgent
                ? "border border-red-300 bg-red-50 font-semibold text-red-800 dark:border-red-800 dark:bg-red-950/50 dark:text-red-200"
                : "border border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
            }`}
          >
            {notice}
          </li>
        );
      })}
    </ul>
  );
}

function Trace({ response }: { response: ChatResponse }) {
  const t = useT();
  const total = response.trace.reduce((sum, s) => sum + s.ms, 0);
  return (
    <details className="mt-2 text-xs text-slate-500 dark:text-slate-400">
      <summary className="cursor-pointer">
        {t.howMade} · {LANGUAGE_NAMES[response.language]} · {response.model} · {(total / 1000).toFixed(1)}s
      </summary>
      <ol className="mt-1 list-decimal space-y-0.5 pl-5" lang="en">
        {response.trace.map((s, i) => (
          <li key={i}>
            {STEP_LABEL[s.step] ?? s.step} ({(s.ms / 1000).toFixed(1)}s)
          </li>
        ))}
      </ol>
      {response.english_query && (
        <p className="mt-1" lang="en">
          Searched as: {response.english_query}
        </p>
      )}
      {response.validation.unquoted.length > 0 && (
        <p className="mt-1" lang="en">
          {response.validation.unquoted.length} paraphrase(s) were not presented as quotations because they are not
          verbatim source text.
        </p>
      )}
    </details>
  );
}

function ListenButton({ id, text, language, speaker }: { id: number; text: string; language: LanguageCode; speaker: Speaker }) {
  const t = useT();
  const active = speaker.speaking === id;
  return (
    <>
      <button
        type="button"
        onClick={() => (active ? speaker.stop() : speaker.speak(id, text, language))}
        aria-pressed={active}
        className={LINK}
      >
        {active ? t.stopReading : t.listen}
      </button>
      {speaker.error?.key === id && (
        <span role="alert" className="text-xs text-red-700 dark:text-red-400">
          {speaker.error.message}
        </span>
      )}
    </>
  );
}

function copyText(response: ChatResponse, text: string): string {
  const cited = response.sources.filter((s) => s.cited);
  if (cited.length === 0) return text;
  const lines = cited.map((s) => `[${s.n}] ${s.title} — ${s.label}${s.citation ? ` (${s.citation})` : ""}`);
  return `${text}\n\n${lines.join("\n")}`;
}

function Feedback({ entry }: { entry: AssistantEntry }) {
  const t = useT();
  const [sent, setSent] = useState<"up" | "down" | null>(null);
  const rate = (rating: "up" | "down") => {
    setSent(rating);
    postFeedback({
      session_id: entry.response.session_id,
      rating,
      language: entry.response.language,
      question: entry.question,
      answer_en: entry.response.answer_en,
    }).catch(() => undefined); // feedback is best effort
  };
  if (sent) return <span className="text-xs text-slate-500 dark:text-slate-400">{t.thanks}</span>;
  return (
    <span className="inline-flex gap-1">
      <button type="button" onClick={() => rate("up")} aria-label={t.helpful} title={t.helpful} className="rounded px-1 hover:bg-slate-100 dark:hover:bg-slate-700">
        👍
      </button>
      <button type="button" onClick={() => rate("down")} aria-label={t.notHelpful} title={t.notHelpful} className="rounded px-1 hover:bg-slate-100 dark:hover:bg-slate-700">
        👎
      </button>
    </span>
  );
}

function AssistantMessage({
  entry,
  onClarify,
  speaker,
  features,
}: {
  entry: AssistantEntry;
  onClarify: (option: ClarifyOption) => void;
  speaker: Speaker;
  features: ChatFeatures;
}) {
  const t = useT();
  const { id, response } = entry;
  const [showEnglish, setShowEnglish] = useState(false);
  const [copied, setCopied] = useState(false);
  const translated = response.language !== "en" && response.answer !== response.answer_en;
  const text = showEnglish ? response.answer_en : response.answer;
  const copy = () => {
    void navigator.clipboard?.writeText(copyText(response, text)).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-800">
      <Notices response={response} />
      <div lang={showEnglish ? "en" : response.language}>
        <AnswerText messageId={id} text={text} />
      </div>
      {response.clarification && (
        <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label={t.chooseOne}>
          {response.clarification.options.map((option) => (
            <button
              key={`${option.field}:${option.value}`}
              type="button"
              onClick={() => onClarify(option)}
              className="rounded-full border border-slate-300 px-3 py-1 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-700"
            >
              {option.label}
            </button>
          ))}
        </div>
      )}
      {response.kind === "answer" && !response.grounded && (
        <p role="note" className="mt-2 text-sm font-medium text-amber-700 dark:text-amber-400">
          {t.uncited}
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
        {features.speechOutput && (
          <ListenButton id={id} text={text} language={showEnglish ? "en" : response.language} speaker={speaker} />
        )}
        {translated && (
          <button type="button" onClick={() => setShowEnglish((v) => !v)} className={LINK}>
            {showEnglish ? t.showTranslation : t.showEnglish}
          </button>
        )}
        <button type="button" onClick={copy} className={LINK}>
          {copied ? t.copied : t.copy}
        </button>
        {response.kind === "answer" && <Feedback entry={entry} />}
      </div>
      {response.sources.length > 0 && <SourceList messageId={id} sources={response.sources} />}
      {response.trace.length > 0 && <Trace response={response} />}
    </article>
  );
}

function Welcome({ language, onAsk, disabled }: { language: LanguageCode | ""; onAsk: (q: string) => void; disabled: boolean }) {
  const t = useT();
  const examples = language
    ? EXAMPLES[language]
    : [EXAMPLES.en[0], EXAMPLES.hi[0], EXAMPLES.kn[0], EXAMPLES.en[1]].filter((q): q is string => q !== undefined);
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-800">
      <h2 className="text-lg font-semibold">{t.welcomeTitle}</h2>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{t.welcomeText}</p>
      <h3 className="mt-4 text-xs font-semibold tracking-wide text-slate-500 uppercase dark:text-slate-400">{t.examplesTitle}</h3>
      <ul className="mt-2 flex flex-wrap gap-2">
        {examples.map((q) => (
          <li key={q}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onAsk(q)}
              className="rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-left text-sm text-indigo-900 hover:bg-indigo-100 disabled:opacity-50 dark:border-indigo-900 dark:bg-indigo-950/40 dark:text-indigo-200 dark:hover:bg-indigo-900/50"
            >
              {q}
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
        <p className="font-semibold">{t.helpTitle}</p>
        <p>
          {t.helpEmergency} · {t.helpWomen} · {t.helpLegalAid}
        </p>
      </div>
    </section>
  );
}

function MessageView({
  message,
  onClarify,
  speaker,
  features,
}: {
  message: ChatMessage;
  onClarify: (message: AssistantEntry, option: ClarifyOption) => void;
  speaker: Speaker;
  features: ChatFeatures;
}) {
  switch (message.role) {
    case "user":
      return (
        <p className="ml-auto max-w-[85%] rounded-xl bg-slate-900 px-4 py-2 whitespace-pre-line text-white dark:bg-slate-100 dark:text-slate-900">
          {message.voice && <span aria-hidden="true">🎤 </span>}
          {message.text}
        </p>
      );
    case "assistant":
      return (
        <AssistantMessage entry={message} onClarify={(o) => onClarify(message, o)} speaker={speaker} features={features} />
      );
    case "error":
      return (
        <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
          {message.text}
        </p>
      );
  }
}

const ALL_FEATURES: ChatFeatures = { speechInput: true, speechOutput: true, loading: false };

export function Chat({ features = ALL_FEATURES }: { features?: ChatFeatures }) {
  const { messages, pending, step, send, reset } = useChat();
  const [draft, setDraft] = useState("");
  const [language, setLanguage] = useState<LanguageCode | "">("");
  // Auto-detect: the interface follows the language of the latest answer.
  const lastAnswer = [...messages].reverse().find((m): m is AssistantEntry => m.role === "assistant");
  const t = STRINGS[language || lastAnswer?.response.language || "en"];
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (messages.length > 0) bottom.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [messages.length, pending]);
  const input = useRef<HTMLTextAreaElement>(null);
  // Voice mode: a spoken question is sent straight away (with any typed text before it), in the
  // spoken language unless one is selected; its answer is then read aloud (effect below).
  const latest = useRef({ draft, language, send });
  latest.current = { draft, language, send };
  const onTranscript = useCallback((result: TranscriptResponse) => {
    const { draft: typed, language: chosen, send: sendNow } = latest.current;
    const text = typed.trim() ? `${typed.trim()} ${result.text}` : result.text;
    setDraft("");
    sendNow(text, { language: chosen || result.language || null }, undefined, true);
  }, []);
  const recorder = useRecorder(onTranscript);
  const speaker = useSpeaker();
  const canSpeak = features.speechInput && speechInputSupported();

  const spoken = useRef(-1);
  useEffect(() => {
    const last = messages.at(-1);
    if (!features.speechOutput || last?.role !== "assistant" || !last.voice || last.id <= spoken.current) return;
    spoken.current = last.id;
    speaker.speak(last.id, last.response.answer, last.response.language);
  }, [messages, features.speechOutput, speaker]);

  const ask = (text: string) => send(text, { language: language || null });

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!draft.trim() || pending) return;
    ask(draft);
    setDraft("");
  };

  const clarify = (message: AssistantEntry, option: ClarifyOption) => {
    const facts = { ...message.options.facts, [option.field]: option.value };
    send(message.question, { ...message.options, facts }, option.label, message.voice);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) submit(event);
  };

  return (
    <I18nContext.Provider value={t}>
      <section aria-labelledby="chat-heading" className="flex flex-col gap-4" lang={language || undefined}>
        <h2 id="chat-heading" className="sr-only">
          {t.askHeading}
        </h2>

        {features.loading && (
          <p role="note" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            {t.modelsLoading}
          </p>
        )}

        {messages.length === 0 ? (
          <Welcome language={language} onAsk={ask} disabled={pending} />
        ) : (
          <div className="flex items-center justify-between gap-2 text-xs text-slate-500 dark:text-slate-400">
            <span>{t.followUpNote}</span>
            <button
              type="button"
              onClick={() => {
                speaker.stop();
                reset();
                setDraft("");
              }}
              className="shrink-0 rounded-md border border-slate-300 px-3 py-1 font-medium text-slate-700 hover:bg-slate-100 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-700"
            >
              {t.newConversation}
            </button>
          </div>
        )}

        <div className="flex flex-col gap-3" aria-live="polite">
          {messages.map((message) => (
            <MessageView key={message.id} message={message} onClarify={clarify} speaker={speaker} features={features} />
          ))}
          {pending && (
            <p role="status" className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
              <span aria-hidden="true" className="inline-block h-2 w-2 animate-pulse rounded-full bg-indigo-500" />
              {(step && t.progress[step]) ?? t.starting}
            </p>
          )}
          <div ref={bottom} />
        </div>

        <form onSubmit={submit} className="sticky bottom-0 flex flex-col gap-2 bg-slate-50 pt-2 pb-3 dark:bg-slate-900">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label htmlFor="chat-input" className={messages.length > 0 ? "sr-only" : "text-sm font-medium"}>
              {t.questionLabel}
            </label>
            <label className="flex items-center gap-2 text-sm">
              <span>{t.language}</span>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value as LanguageCode | "")}
                className="rounded-md border border-slate-300 bg-white px-2 py-1 dark:border-slate-600 dark:bg-slate-800"
              >
                <option value="">{t.auto}</option>
                <option value="en">English</option>
                <option value="hi">हिन्दी (Hindi)</option>
                <option value="kn">ಕನ್ನಡ (Kannada)</option>
              </select>
            </label>
          </div>
          <textarea
            id="chat-input"
            ref={input}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            maxLength={MAX_LENGTH}
            rows={messages.length > 0 ? 2 : 3}
            placeholder={t.placeholder}
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 focus-visible:outline-2 focus-visible:outline-slate-900 dark:border-slate-600 dark:bg-slate-800"
          />
          {recorder.state === "recording" && recorder.autoStop && (
            <p role="status" className="text-sm text-slate-600 dark:text-slate-300">
              {t.listening}
            </p>
          )}
          {recorder.error && (
            <p role="alert" className="text-sm text-red-700 dark:text-red-400">
              {recorder.error}
            </p>
          )}
          <div className="flex items-center justify-end gap-2">
            {canSpeak && (
              <button
                type="button"
                onClick={() => {
                  if (recorder.state === "recording") return recorder.stop();
                  speaker.stop(); // talking over the answer interrupts it
                  void recorder.start(language || null);
                }}
                disabled={recorder.state === "transcribing" || pending}
                aria-pressed={recorder.state === "recording"}
                className={`rounded-md border px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${
                  recorder.state === "recording"
                    ? "animate-pulse border-red-400 bg-red-50 text-red-700 dark:border-red-700 dark:bg-red-950/50 dark:text-red-300"
                    : "border-slate-300 hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-700"
                }`}
              >
                {recorder.state === "recording" ? t.stopRecording : recorder.state === "transcribing" ? t.transcribing : t.speak}
              </button>
            )}
            <button
              type="submit"
              disabled={pending || !draft.trim()}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
            >
              {t.ask}
            </button>
          </div>
        </form>
      </section>
    </I18nContext.Provider>
  );
}
