import type { TraceEvent } from "./types";

/**
 * Where the backend lives.
 *
 * Empty in development: Vite proxies /api to :8420 (see vite.config.ts), so a
 * relative path is already correct. In production the frontend is on Vercel and
 * the backend on Render, so this carries the backend origin and the browser
 * talks to it directly.
 *
 * Deliberately NOT a Vercel rewrite. A rewrite would put Vercel's edge proxy in
 * front of the /api/plan SSE stream, which runs for minutes and would be cut by
 * the proxy's own response timeout. Direct calls with CORS avoid that entirely.
 */
const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

const url = (path: string) => `${API_BASE}${path}`;

export type ChatResponse = {
  session_id: string;
  reply: string;
  profile_complete: boolean;
  events: TraceEvent[];
  usage: { agents: Record<string, never>; total_cost_usd: number };
};

/** A chat turn is a few seconds; a stalled one must fail loudly, not hang. */
const CHAT_TIMEOUT_MS = 120_000;

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return typeof body?.detail === "string" ? body.detail : JSON.stringify(body);
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

export async function health() {
  const res = await fetch(url("/api/health"));
  if (!res.ok) throw new Error(await readError(res));
  return res.json() as Promise<{
    ok: boolean;
    provider: string;
    models: Record<string, string>;
    missing_keys: string[];
  }>;
}

export async function chat(message: string, sessionId: string | null) {
  let res: Response;
  try {
    res = await fetch(url("/api/chat"), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
      signal: AbortSignal.timeout(CHAT_TIMEOUT_MS),
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "TimeoutError") {
      throw new Error(
        `the consultant did not answer within ${CHAT_TIMEOUT_MS / 1000}s`,
      );
    }
    throw err;
  }
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as ChatResponse;
}

/**
 * Streams the planning run. Server-sent events arrive as `data: {...}` frames;
 * frames can split across chunks, so hold a buffer and only parse on a blank
 * line.
 */
export async function streamPlan(
  brief: string,
  onEvent: (event: TraceEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(url("/api/plan"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ brief }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(await readError(res));

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let split: number;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      try {
        onEvent(JSON.parse(line.slice(6)) as TraceEvent);
      } catch {
        // A malformed frame should not kill the run; keep reading.
      }
    }
  }
}
