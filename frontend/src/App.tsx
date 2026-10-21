import { BackendStatus } from "./components/BackendStatus";

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-900 dark:text-slate-100">
      <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-12">
        <header>
          <h1 className="text-3xl font-bold tracking-tight">Kanoon AI</h1>
          <p className="mt-1 text-slate-600 dark:text-slate-400">Family Law Information Assistant</p>
        </header>

        <BackendStatus />

        <p className="text-xs text-slate-500 dark:text-slate-400">
          This system provides general legal information, not legal advice. For advice about your situation,
          consult a qualified lawyer or your District Legal Services Authority.
        </p>
      </main>
    </div>
  );
}
