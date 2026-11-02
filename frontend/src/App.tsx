import { Chat } from "./components/Chat";
import { StatusPill } from "./components/StatusPill";
import { featuresOf, useReadiness } from "./hooks/useReadiness";

export default function App() {
  const { state, retry } = useReadiness();

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-900 dark:text-slate-100">
      <header className="border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-3">
          <div>
            <h1 className="text-xl font-bold tracking-tight">Kanoon AI</h1>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Family law information · पारिवारिक कानून की जानकारी · ಕುಟುಂಬ ಕಾನೂನು ಮಾಹಿತಿ
            </p>
          </div>
          <StatusPill state={state} onRetry={retry} />
        </div>
      </header>

      <main className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6">
        <p className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">
          This system provides general legal information, not legal advice. For advice about your situation, consult a
          qualified lawyer or your District Legal Services Authority (free legal aid: 15100).
        </p>

        <Chat features={featuresOf(state)} />
      </main>
    </div>
  );
}
