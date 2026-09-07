# multi-agent-itinerary-planner

A multi-agent RAG itinerary planner: a Python **backend** running the agent graph
on Google ADK, and a React **frontend** with a chat view and a hidden panel that
exposes every agent's input and output.

```
multi-agent-itinerary-planner/
├── backend/     FastAPI + Google ADK 2.8 — the agent graph, tools, retrieval
└── frontend/    Vite + React 19 + Tailwind 4 — chat, and the agent trace panel
```

## Run it

Two terminals.

```bash
# backend — http://127.0.0.1:8420
cd backend
uv venv --python 3.12 && uv pip install -r requirements.txt
cp .env.example .env.local # then fill in your keys
./.venv/bin/python -m uvicorn app.main:app --port 8420 --reload
```

```bash
# frontend — http://localhost:5173  (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

`GET /api/health` reports the active provider, the resolved models and any
missing credentials. The frontend shows a banner rather than failing silently if
the backend is unreachable or unconfigured.

## The agent graph

```
interviewer ─► profile_extractor ─► researcher ─► planner ─┐
 (one question       (structured        (RAG over    (day-by-day) │
  at a time)          profile)           the KB)                  ▼
                          writer ◄─ [ validator ─► pass_gate ─► reviser ] ×2
```

`pass_gate` is a plain `BaseAgent` that reads the committed validation report and
escalates in code. The loop exit is deliberately not a model's decision: an agent
asked to both emit a structured report and call `exit_loop` in the same turn will
sometimes escalate before its report reaches state, and the loop then exits
having recorded nothing.

| Agent | Tier | Gemini | Claude |
|---|---|---|---|
| `planner`, `validator` | reasoning | `gemini-3.1-pro-preview` | `claude-sonnet-5` |
| `interviewer`, `reviser`, `writer` | worker | `gemini-3.8-flash` | `claude-haiku-4-5` |
| `profile_extractor`, `researcher` | bulk | `gemini-3.8-flash` | `claude-haiku-4-5` |

Agents are given a **tier**, never a model. `MODEL_PROVIDER=gemini|anthropic`
swaps the whole graph; `MODEL_REASONING` / `MODEL_WORKER` / `MODEL_BULK` override
individual tiers. Gemini is native to ADK; Claude routes through `LiteLlm`.

## The hidden agent panel

Toggled from the header or with **⌘I / Ctrl+I**, hidden by default.

For each agent it shows the tier, model, live token counts, cost and elapsed
time, and expands to reveal:

- **Instruction** — the fully resolved system prompt, *after* ADK has injected
  session state, which is what the model actually saw
- **Tool calls** — every call with its arguments and its return value, paired up
- **Output** — the raw text or structured object the agent produced
- **Session state** — which keys were visible to that agent

Below the agents, the two review layers are shown separately: the deterministic
report (produced with no model in the loop) and the reviewer's judgement. They
are kept apart on purpose — the reviewer rewrites the machine findings in its own
words, which is better for the traveller and useless as an audit trail.

This is all fed by ADK's `before_model` / `after_model` / `before_tool` /
`after_tool` callbacks (see `backend/app/trace.py`), pushed onto a per-run queue
and streamed to the browser as SSE. The callbacks return `None` throughout, so
observing the run cannot change it.

## Measured

One 6-night plan, Gemini, end to end:

| Agent | Model | Input | Output | USD |
|---|---|---:|---:|---:|
| planner | gemini-3.1-pro-preview | 106,469 | 1,603 | 0.2322 |
| validator | gemini-3.1-pro-preview | 47,878 | 208 | 0.0983 |
| researcher | gemini-3.8-flash | 59,886 | 1,838 | 0.0518 |
| writer | gemini-3.8-flash | 26,285 | 1,659 | 0.0259 |
| profile_extractor | gemini-3.8-flash | 190 | 103 | 0.0005 |
| **Total** | | **240,708** | **5,411** | **0.4087** |

28 tool calls, all captured in the trace. Deterministic checks passed with no
issues; the reviewer raised two warnings (`pace_too_packed`,
`frequent_base_changes`).

Input dominates because ADK resends the whole conversation on every tool call —
prompt caching on the stable prefix is the lever, not a cheaper model.

## Known limits

- **Sessions are in-memory.** Restarting the backend drops every conversation.
- **Chat is request/response**; only the planning run streams. A turn takes
  3-8s against Gemini, so the composer shows a live "consultant is thinking"
  line and requests abort after 120s rather than hanging silently. Streaming the
  interviewer would remove the wait entirely and is the obvious next step.
- **No auth and CORS is open to localhost.** Prototype only.
- **The Anthropic path is untested here** — that key is out of credit. The code
  path is the one previously exercised in `../tour-itinerary-adk`.
- **Retrieval needs `OPENAI_API_KEY`** whichever provider runs the graph;
  Anthropic has no embeddings endpoint.
