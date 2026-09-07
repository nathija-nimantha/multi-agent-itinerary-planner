import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ChatPane from "./components/ChatPane";
import TracePanel from "./components/TracePanel";
import { chat, health, streamPlan } from "./api";
import type {
  AgentTrace,
  ChatMessage,
  DeterministicReport,
  ReviewerReport,
  TraceEvent,
} from "./types";

const OPENER =
  "Tell me about the trip you have in mind — who is travelling, roughly when, and what you want out of it.";

/** Folds the raw event stream into one record per agent, in first-seen order. */
function foldTraces(events: TraceEvent[]): AgentTrace[] {
  const byAgent = new Map<string, AgentTrace>();
  const ensure = (name: string): AgentTrace => {
    let t = byAgent.get(name);
    if (!t) {
      t = {
        name,
        tier: "",
        model: "",
        tools: [],
        outputs: [],
        tokens: { input: 0, output: 0 },
        cost: 0,
        elapsed: 0,
        status: "running",
        stateKeys: [],
        declaredTools: [],
      };
      byAgent.set(name, t);
    }
    return t;
  };

  for (const ev of events) {
    switch (ev.kind) {
      case "agent_prompt": {
        const t = ensure(ev.agent);
        t.tier = ev.tier;
        t.model = ev.model;
        t.prompt = ev.system;
        t.stateKeys = ev.state_keys;
        t.declaredTools = ev.tools;
        break;
      }
      case "tool_call":
        ensure(ev.agent).tools.push({ tool: ev.tool, args: ev.args });
        break;
      case "tool_result": {
        const t = ensure(ev.agent);
        // Attach to the most recent unresolved call of the same tool.
        const open = [...t.tools].reverse().find(
          (c) => c.tool === ev.tool && c.result === undefined,
        );
        if (open) open.result = ev.result;
        else t.tools.push({ tool: ev.tool, args: ev.args, result: ev.result });
        break;
      }
      case "agent_output": {
        const t = ensure(ev.agent);
        t.tier = ev.tier;
        t.model = ev.model;
        t.outputs.push(ev.content);
        t.tokens.input += ev.tokens.input;
        t.tokens.output += ev.tokens.output;
        t.cost += ev.cost_usd;
        t.elapsed = ev.elapsed_s;
        t.status = "done";
        break;
      }
    }
  }
  return [...byAgent.values()];
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "agent", text: OPENER },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [showTrace, setShowTrace] = useState(false);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [deterministic, setDeterministic] = useState<DeterministicReport | null>(null);
  const [reviewer, setReviewer] = useState<ReviewerReport | null>(null);
  const [provider, setProvider] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  const sessionRef = useRef<string | null>(null);
  const transcriptRef = useRef<string[]>([]);
  const traces = useMemo(() => foldTraces(events), [events]);

  useEffect(() => {
    health()
      .then((h) => {
        setProvider(h.provider);
        if (!h.ok) setBanner(`Backend is missing credentials: ${h.missing_keys.join(", ")}`);
      })
      .catch((e) => setBanner(`Backend unreachable — ${e.message}`));
  }, []);

  // The panel is hidden by default; ⌘/Ctrl+I reveals it.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "i") {
        e.preventDefault();
        setShowTrace((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const runPlan = useCallback(async (brief: string) => {
    setStage("starting the planning run");
    setEvents([]);
    setDeterministic(null);
    setReviewer(null);
    try {
      await streamPlan(brief, (ev) => {
        if (ev.kind !== "done") setEvents((prev) => [...prev, ev]);
        switch (ev.kind) {
          case "stage":
            setStage(`${ev.agent} working`);
            break;
          case "result": {
            setDeterministic(ev.deterministic ?? null);
            setReviewer(ev.reviewer ?? null);

            // A plan that failed review must not be handed over looking final.
            // The repair loop is bounded, so it can genuinely run out of
            // attempts — and when it does, that belongs in the conversation,
            // not only behind the trace panel toggle.
            const critical = [
              ...(ev.deterministic?.issues ?? []),
              ...(ev.reviewer?.issues ?? []),
            ].filter((i) => i.severity === "critical");
            const seen = new Set<string>();
            const unique = critical.filter((i) =>
              seen.has(i.code) ? false : (seen.add(i.code), true),
            );

            setMessages((prev) => [
              ...prev,
              ...(unique.length
                ? [
                    {
                      role: "system" as const,
                      tone: "warn" as const,
                      text:
                        `This plan did not pass review and is not bookable as it stands — ` +
                        `${unique.length} unresolved problem${unique.length > 1 ? "s" : ""}:\n\n` +
                        unique.map((i) => `• ${i.message}`).join("\n") +
                        `\n\nThe itinerary below is shown so you can see what was attempted. ` +
                        `Adjust the brief and try again.`,
                    },
                  ]
                : []),
              {
                role: "agent" as const,
                text: ev.document || "The run finished but produced no document.",
              },
            ]);
            break;
          }
          case "error":
            setMessages((prev) => [
              ...prev,
              { role: "system", text: `Run failed — ${ev.message}` },
            ]);
            break;
        }
      });
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: "system", text: `Run failed — ${(e as Error).message}` },
      ]);
    } finally {
      setStage(null);
    }
  }, []);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setMessages((prev) => [...prev, { role: "user", text }]);
    transcriptRef.current.push(`Traveller: ${text}`);

    try {
      const res = await chat(text, sessionRef.current);
      sessionRef.current = res.session_id;
      setEvents((prev) => [...prev, ...res.events]);
      setMessages((prev) => [...prev, { role: "agent", text: res.reply }]);
      transcriptRef.current.push(`Consultant: ${res.reply}`);

      if (res.profile_complete) {
        setMessages((prev) => [
          ...prev,
          { role: "system", text: "Brief complete — planning the itinerary" },
        ]);
        await runPlan(transcriptRef.current.join("\n\n"));
      }
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: "system", text: `Could not reach the consultant — ${(e as Error).message}` },
      ]);
    } finally {
      setBusy(false);
    }
  }, [busy, input, runPlan]);

  return (
    <div className="flex h-full flex-col bg-white dark:bg-ink-950">
      <header className="flex items-center gap-3 border-b border-ink-200 px-5 py-3 dark:border-ink-800">
        <h1 className="text-sm font-semibold tracking-tight">Itinerary Planner</h1>
        <span className="font-mono text-[10px] uppercase tracking-widest text-ink-400">
          multi-agent · ADK
        </span>
        <button
          onClick={() => setShowTrace((v) => !v)}
          aria-pressed={showTrace}
          className="ml-auto flex items-center gap-2 rounded border border-ink-200 px-2.5 py-1 font-mono text-[11px] text-ink-600 transition hover:border-petrol-500 hover:text-petrol-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-petrol-500 dark:border-ink-800 dark:text-ink-400 dark:hover:text-petrol-400"
        >
          {showTrace ? "Hide" : "Show"} agent trace
          {traces.length > 0 && (
            <span className="rounded bg-ink-100 px-1 text-[10px] dark:bg-ink-800">
              {traces.length}
            </span>
          )}
          <kbd className="text-ink-400">⌘I</kbd>
        </button>
      </header>

      {banner && (
        <p className="border-b border-amber-300 bg-amber-50 px-5 py-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
          {banner}
        </p>
      )}

      <div className="flex min-h-0 flex-1">
        <main className="min-w-0 flex-1">
          <ChatPane
            messages={messages}
            input={input}
            busy={busy || stage !== null}
            activity={stage ?? (busy ? "consultant is thinking" : null)}
            onInput={setInput}
            onSend={send}
          />
        </main>
        {showTrace && (
          <div className="w-[26rem] max-w-[46vw] shrink-0">
            <TracePanel
              traces={traces}
              deterministic={deterministic}
              reviewer={reviewer}
              provider={provider}
              onClose={() => setShowTrace(false)}
            />
          </div>
        )}
      </div>
    </div>
  );
}
