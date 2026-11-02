// Mirrors backend/app/schemas. Will be generated from OpenAPI once the API surface grows.

export type Environment = "development" | "test" | "production";

export interface HealthResponse {
  status: "ok";
  app_name: string;
  version: string;
  environment: Environment;
  timestamp: string;
}

export type LanguageCode = "en" | "hi" | "kn";

export interface UserFacts {
  religion?: string | null;
  marriage_type?: string | null;
}

export interface ChatRequest {
  message: string;
  language?: LanguageCode | null;
  facts?: UserFacts | null;
  /** Continue a conversation (returned by the previous response). */
  session_id?: string | null;
}

/** A numbered source; `[n]` in the answer refers to `n` here. */
export interface Source {
  n: number;
  chunk_id: string;
  matched_chunk_ids: string[];
  doc_id: string;
  doc_type: "statute" | "judgment";
  title: string;
  label: string;
  court: string | null;
  citation: string | null;
  decision_date: string | null;
  page_start: number;
  page_end: number;
  text: string;
  score: number;
  cited: boolean;
}

export interface ClarifyOption {
  field: "religion" | "marriage_type";
  value: string;
  label: string;
}

export interface TraceStep {
  step: string;
  ms: number;
  detail: Record<string, unknown>;
}

export interface ChatResponse {
  session_id: string;
  kind: "answer" | "clarification" | "out_of_scope";
  answer: string;
  answer_en: string;
  grounded: boolean;
  sources: Source[];
  model: string;
  language: LanguageCode;
  romanized: boolean;
  english_query: string;
  notices: string[];
  emergency: boolean;
  clarification: { question: string; options: ClarifyOption[] } | null;
  analysis: {
    topic: string;
    religion: string;
    marriage_type: string;
    in_scope: boolean;
    applicability: string | null;
  } | null;
  validation: {
    invalid_citations: number[];
    verified_quotes: number;
    unquoted: string[];
    regenerated: boolean;
    translation_ok: boolean;
  };
  rounds: number;
  trace: TraceStep[];
}

export type Readiness = "loading" | "ready" | "unavailable" | "disabled" | "on_demand";

/** GET /ready: what works right now (models load in the background after startup). */
export interface ReadyResponse {
  answers: Readiness;
  speech_input: Readiness;
  speech_output: Readiness;
}
