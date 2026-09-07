# backend

FastAPI over a Google ADK 2.8 agent graph.

| Path | |
|---|---|
| `app/config.py` | Provider/tier resolution. Agents ask for a tier, never a model. |
| `app/agents.py` | The graph: seven `LlmAgent`s, a `LoopAgent`, and `pass_gate`. |
| `app/tools.py` | `kb_search`, `travel_time`, and the deterministic `validate_itinerary`. |
| `app/rag.py` | Embeddings + numpy cosine over ~42 documents. No vector DB at this size. |
| `app/trace.py` | ADK callbacks → typed event stream. What the UI panel renders. |
| `app/schemas.py` | Pydantic contracts every agent writes against. |
| `kb/sri_lanka.json` | 32 places, 62 routes, 10 practical notes. |

## Endpoints

- `GET /api/health` — provider, resolved models, missing credentials
- `POST /api/chat` — one interviewer turn; returns `profile_complete` when the
  brief is done, plus that turn's trace events
- `POST /api/plan` — runs the pipeline, streaming trace events as SSE

## The validator

`validate_itinerary` runs twenty checks in pure Python before any model forms an
opinion, in **two directions**:

*Ceilings* — invented places, invented routes, route continuity, day count,
budget, transfer length, pace caps, duplicates, seasonality, cost arithmetic.

*Floors* — `empty_day`, `interest_unserved`, `itinerary_underfilled`,
`insufficient_variety`, `plan_under_delivers`. These exist because a run once
produced four places across seven days with a dead day in the middle and passed
clean: every check written to that point asked only whether the plan overreached.
Under-delivery is the quieter failure and needs checking as hard as overreach.

The raw report is written to `state["deterministic_report"]` verbatim so it
survives the reviewer rewriting it.

## Swapping provider

```bash
MODEL_PROVIDER=anthropic ANTHROPIC_API_KEY=... uvicorn app.main:app --port 8420
```
