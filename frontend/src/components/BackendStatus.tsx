import { useHealth } from "../hooks/useHealth";

export function BackendStatus() {
  const { state, retry } = useHealth();

  return (
    <section
      aria-labelledby="backend-status-heading"
      className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-800"
    >
      <h2 id="backend-status-heading" className="text-sm font-semibold text-slate-500 dark:text-slate-400">
        Backend status
      </h2>

      <div role="status" aria-live="polite" className="mt-3">
        {state.status === "loading" && <p className="text-slate-600 dark:text-slate-300">Checking connection…</p>}

        {state.status === "success" && (
          <div className="space-y-1">
            <p className="flex items-center gap-2 font-medium text-emerald-700 dark:text-emerald-400">
              <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full bg-emerald-500" />
              Connected
            </p>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 text-sm text-slate-600 dark:text-slate-300">
              <dt>Service</dt>
              <dd>{state.data.app_name}</dd>
              <dt>Version</dt>
              <dd>{state.data.version}</dd>
              <dt>Environment</dt>
              <dd>{state.data.environment}</dd>
            </dl>
          </div>
        )}

        {state.status === "error" && (
          <div className="space-y-2">
            <p className="flex items-center gap-2 font-medium text-red-700 dark:text-red-400">
              <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full bg-red-500" />
              Not connected
            </p>
            <p className="text-sm text-slate-600 dark:text-slate-300">{state.error.message}</p>
            <button
              type="button"
              onClick={retry}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-slate-300"
            >
              Retry
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
