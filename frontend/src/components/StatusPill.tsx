import type { ReadinessState } from "../hooks/useReadiness";

const DOT = "inline-block h-2.5 w-2.5 shrink-0 rounded-full";

/** Compact backend status for the header. */
export function StatusPill({ state, onRetry }: { state: ReadinessState; onRetry: () => void }) {
  if (state.status === "checking") {
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
        <span aria-hidden="true" className={`${DOT} bg-slate-400`} />
        Connecting…
      </p>
    );
  }
  if (state.status === "offline") {
    return (
      <div role="status" className="flex flex-wrap items-center gap-2 text-sm">
        <span aria-hidden="true" className={`${DOT} bg-red-500`} />
        <span className="font-medium text-red-700 dark:text-red-400">Not connected</span>
        <span className="text-slate-500 dark:text-slate-400">{state.error.message}</span>
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md border border-slate-300 px-2 py-0.5 text-xs font-medium hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-700"
        >
          Retry
        </button>
      </div>
    );
  }
  const { ready, health } = state;
  const loading = Object.values(ready).includes("loading");
  const speechOff = [ready.speech_input, ready.speech_output].some((r) => r === "unavailable" || r === "disabled");
  const answersDown = ready.answers === "unavailable";
  const [color, label] = answersDown
    ? ["bg-red-500", "Answers unavailable (index missing?)"]
    : loading
      ? ["bg-amber-500 animate-pulse", "Loading models…"]
      : ["bg-emerald-500", speechOff ? "Ready · speech off" : "Ready"];
  return (
    <p
      role="status"
      title={`${health.app_name} ${health.version} (${health.environment})`}
      className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300"
    >
      <span aria-hidden="true" className={`${DOT} ${color}`} />
      {label}
    </p>
  );
}
