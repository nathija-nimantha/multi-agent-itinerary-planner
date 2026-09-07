import { useState } from "react";
import type { AgentTrace } from "../types";
import JsonBlock from "./JsonBlock";

const TIER_STYLE: Record<string, string> = {
  reasoning: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  worker: "bg-petrol-400/20 text-petrol-700 dark:text-petrol-400",
  bulk: "bg-ink-200 text-ink-600 dark:bg-ink-800 dark:text-ink-400",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-3 first:mt-0">
      <div className="mb-1 font-mono text-[10px] uppercase tracking-widest text-ink-400">
        {title}
      </div>
      {children}
    </div>
  );
}

export default function AgentCard({ trace }: { trace: AgentTrace }) {
  const [open, setOpen] = useState(false);
  const running = trace.status === "running";

  return (
    <div className="border-b border-ink-200 dark:border-ink-800">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left hover:bg-ink-100/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-petrol-500 dark:hover:bg-ink-900"
      >
        <span
          aria-hidden
          className={`size-1.5 shrink-0 rounded-full ${
            running ? "animate-pulse bg-amber-500" : "bg-petrol-500"
          }`}
        />
        <span className="font-mono text-xs font-medium">{trace.name}</span>
        <span
          className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${
            TIER_STYLE[trace.tier] ?? TIER_STYLE.bulk
          }`}
        >
          {trace.tier}
        </span>
        <span className="ml-auto flex items-center gap-2.5 font-mono text-[10px] tabular-nums text-ink-400">
          {trace.tokens.input > 0 && (
            <span title="input / output tokens">
              {trace.tokens.input.toLocaleString()}↓{" "}
              {trace.tokens.output.toLocaleString()}↑
            </span>
          )}
          {trace.cost > 0 && <span title="cost">${trace.cost.toFixed(4)}</span>}
          <span aria-hidden className="text-ink-400">
            {open ? "−" : "+"}
          </span>
        </span>
      </button>

      {open && (
        <div className="px-3 pb-3">
          <div className="mb-2 font-mono text-[10px] text-ink-400">
            {trace.model}
            {trace.elapsed > 0 && ` · ${trace.elapsed.toFixed(1)}s`}
            {trace.declaredTools.length > 0 && ` · tools: ${trace.declaredTools.join(", ")}`}
          </div>

          {trace.prompt && (
            <Section title={`Instruction (${trace.prompt.full_length.toLocaleString()} chars)`}>
              <pre className="thin-scroll max-h-72 overflow-auto rounded border border-ink-200 bg-ink-50 p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words text-ink-600 dark:border-ink-800 dark:bg-ink-950 dark:text-ink-400">
                {trace.prompt.text}
                {trace.prompt.truncated && (
                  <span className="text-ink-400">{"\n… truncated"}</span>
                )}
              </pre>
            </Section>
          )}

          {trace.tools.length > 0 && (
            <Section title={`Tool calls (${trace.tools.length})`}>
              <div className="space-y-2">
                {trace.tools.map((call, i) => (
                  <div
                    key={i}
                    className="rounded border border-ink-200 p-2 dark:border-ink-800"
                  >
                    <div className="mb-1 font-mono text-[11px] font-medium text-petrol-600 dark:text-petrol-400">
                      {call.tool}
                    </div>
                    <JsonBlock value={call.args} max={600} />
                    {call.result !== undefined && (
                      <div className="mt-1.5">
                        <div className="mb-1 font-mono text-[10px] uppercase tracking-widest text-ink-400">
                          returned
                        </div>
                        <JsonBlock value={call.result} max={1800} />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          )}

          {trace.outputs.length > 0 && (
            <Section title="Output">
              <div className="space-y-2">
                {trace.outputs.map((out, i) => (
                  <JsonBlock key={i} value={out.text} max={3000} />
                ))}
              </div>
            </Section>
          )}

          {trace.stateKeys.length > 0 && (
            <Section title="Session state visible to this agent">
              <div className="flex flex-wrap gap-1">
                {trace.stateKeys.map((k) => (
                  <span
                    key={k}
                    className="rounded bg-ink-100 px-1.5 py-0.5 font-mono text-[10px] text-ink-600 dark:bg-ink-900 dark:text-ink-400"
                  >
                    {k}
                  </span>
                ))}
              </div>
            </Section>
          )}
        </div>
      )}
    </div>
  );
}
