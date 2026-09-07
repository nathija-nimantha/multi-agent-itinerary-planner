import type { AgentTrace, DeterministicReport, Issue, ReviewerReport } from "../types";
import AgentCard from "./AgentCard";

type Props = {
  traces: AgentTrace[];
  deterministic: DeterministicReport | null;
  reviewer: ReviewerReport | null;
  provider: string | null;
  onClose: () => void;
};

function IssueList({ issues }: { issues: Issue[] }) {
  if (issues.length === 0) {
    return <p className="px-3 pb-2 text-xs text-ink-400">No issues raised.</p>;
  }
  return (
    <ul className="space-y-1.5 px-3 pb-3">
      {issues.map((issue, i) => (
        <li key={i} className="flex gap-2 text-xs leading-snug">
          <span
            className={`mt-0.5 shrink-0 rounded px-1 py-0.5 font-mono text-[9px] uppercase ${
              issue.severity === "critical"
                ? "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300"
                : "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-300"
            }`}
          >
            {issue.severity}
          </span>
          <span className="min-w-0">
            <span className="font-mono text-[11px] text-ink-600 dark:text-ink-400">
              {issue.code}
              {issue.day != null && ` · day ${issue.day}`}
            </span>
            <span className="block text-ink-800 dark:text-ink-200">{issue.message}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function Verdict({ passed }: { passed: boolean }) {
  return (
    <span
      className={`rounded px-1.5 py-0.5 font-mono text-[10px] uppercase ${
        passed
          ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
          : "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300"
      }`}
    >
      {passed ? "passed" : "failed"}
    </span>
  );
}

export default function TracePanel({
  traces,
  deterministic,
  reviewer,
  provider,
  onClose,
}: Props) {
  const total = traces.reduce((sum, t) => sum + t.cost, 0);

  return (
    <aside className="flex h-full w-full flex-col border-l border-ink-200 bg-white dark:border-ink-800 dark:bg-ink-900">
      <header className="flex items-center gap-2 border-b border-ink-200 px-3 py-2.5 dark:border-ink-800">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-ink-600 dark:text-ink-400">
          Agent trace
        </h2>
        {provider && (
          <span className="rounded bg-ink-100 px-1.5 py-0.5 font-mono text-[10px] text-ink-600 dark:bg-ink-800 dark:text-ink-400">
            {provider}
          </span>
        )}
        <button
          onClick={onClose}
          className="ml-auto rounded px-1.5 py-0.5 font-mono text-[11px] text-ink-400 hover:bg-ink-100 hover:text-ink-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-petrol-500 dark:hover:bg-ink-800 dark:hover:text-ink-100"
          aria-label="Hide agent trace"
        >
          hide
        </button>
      </header>

      <div className="thin-scroll flex-1 overflow-y-auto">
        {traces.length === 0 ? (
          <p className="p-4 text-xs leading-relaxed text-ink-400">
            Nothing yet. Every prompt an agent receives, each tool it calls with its
            arguments and return value, and what it produces will appear here as the
            run proceeds.
          </p>
        ) : (
          traces.map((t) => <AgentCard key={t.name} trace={t} />)
        )}

        {deterministic && (
          <section className="border-b border-ink-200 dark:border-ink-800">
            <div className="flex items-center gap-2 px-3 py-2.5">
              <span className="font-mono text-xs font-medium">deterministic checks</span>
              <Verdict passed={deterministic.passed} />
              <span className="ml-auto font-mono text-[10px] text-ink-400">no model</span>
            </div>
            <IssueList issues={deterministic.issues} />
          </section>
        )}

        {reviewer && (
          <section className="border-b border-ink-200 dark:border-ink-800">
            <div className="flex items-center gap-2 px-3 py-2.5">
              <span className="font-mono text-xs font-medium">reviewer judgement</span>
              <Verdict passed={reviewer.passed} />
            </div>
            <IssueList issues={reviewer.issues} />
          </section>
        )}
      </div>

      {total > 0 && (
        <footer className="border-t border-ink-200 px-3 py-2 dark:border-ink-800">
          <table className="w-full font-mono text-[10px] tabular-nums">
            <caption className="sr-only">Token spend by agent</caption>
            <tbody>
              {traces.map((t) => (
                <tr key={t.name} className="text-ink-400">
                  <td className="py-0.5">{t.name}</td>
                  <td className="py-0.5 text-right">{t.tokens.input.toLocaleString()}</td>
                  <td className="py-0.5 text-right">{t.tokens.output.toLocaleString()}</td>
                  <td className="py-0.5 text-right text-ink-800 dark:text-ink-200">
                    ${t.cost.toFixed(4)}
                  </td>
                </tr>
              ))}
              <tr className="border-t border-ink-200 font-medium dark:border-ink-800">
                <td className="pt-1">total</td>
                <td />
                <td />
                <td className="pt-1 text-right">${total.toFixed(4)}</td>
              </tr>
            </tbody>
          </table>
        </footer>
      )}
    </aside>
  );
}
