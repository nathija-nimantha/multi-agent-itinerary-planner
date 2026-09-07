# frontend

Vite + React 19 + TypeScript + Tailwind 4. No SSR — it is a single page talking
to the Python backend, proxied at `/api` in dev (see `vite.config.ts`).

| Path | |
|---|---|
| `src/App.tsx` | Orchestration: chat turns, then the streamed planning run. |
| `src/api.ts` | `fetch` client; SSE frames are buffered because they split across chunks. |
| `src/types.ts` | The event contract shared with the backend. |
| `src/components/ChatPane.tsx` | Messages and composer. Markdown for the final itinerary. |
| `src/components/TracePanel.tsx` | The hidden panel: agents, both review layers, cost. |
| `src/components/AgentCard.tsx` | One agent — instruction, tool calls, output, state keys. |

`foldTraces` in `App.tsx` reduces the flat event stream into one record per
agent, pairing each `tool_result` with the matching unresolved `tool_call`.
Costs shown in the footer are derived from those same records rather than a
separate total, so they update live during a run instead of only at the end.

**⌘I / Ctrl+I** toggles the panel; it is hidden on load.
