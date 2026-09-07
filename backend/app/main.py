"""FastAPI backend: chat intake, and a traced multi-agent planning run over SSE.

Two surfaces:
  POST /api/chat   one interviewer turn; returns the reply and a completion flag
  POST /api/plan   runs the full pipeline, streaming every agent event as SSE

The SSE stream is what the frontend's hidden agent panel renders. It carries
both the user-facing result and the full internal trace on the same connection,
so the panel is a display toggle rather than a second request.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config import (
    APP_NAME,
    RETRY_MAX_ATTEMPTS,
    RETRYABLE_EXCEPTIONS,
    load_env,
    missing_keys,
    model_id,
    provider,
)

load_env()

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402

from .agents import build_interviewer, build_pipeline  # noqa: E402
from .trace import Tracer  # noqa: E402

app = FastAPI(title="Multi-Agent Itinerary Planner")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Interviewer sessions live for the length of a conversation.
_chat_runners: dict[str, tuple[Any, str, Tracer]] = {}


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


class PlanIn(BaseModel):
    brief: str


@app.get("/api/health")
def health() -> dict[str, Any]:
    missing = missing_keys()
    return {
        "ok": not missing,
        "provider": provider(),
        "models": {t: model_id(t) for t in ("reasoning", "worker", "bulk")},
        "missing_keys": missing,
        "retry": {
            "max_attempts": RETRY_MAX_ATTEMPTS,
            "retryable": RETRYABLE_EXCEPTIONS,
        },
    }


async def _drain(runner, session_id: str, text: str) -> str:
    reply = ""
    async for ev in runner.run_async(
        user_id="traveller", session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=text)]),
    ):
        if ev.content and ev.content.parts and not ev.partial:
            for part in ev.content.parts:
                if part.text:
                    reply = part.text
    return reply


@app.post("/api/chat")
async def chat(body: ChatIn) -> dict[str, Any]:
    """One turn with the interviewer. Creates a session on first call."""
    if missing_keys():
        raise HTTPException(503, f"missing credentials: {', '.join(missing_keys())}")

    sid = body.session_id
    if sid and sid in _chat_runners:
        runner, adk_session, tracer = _chat_runners[sid]
    else:
        sid = uuid.uuid4().hex[:12]
        tracer = Tracer(run_id=sid)
        runner = InMemoryRunner(agent=build_interviewer(tracer), app_name=APP_NAME)
        session = await runner.session_service.create_session(
            app_name=APP_NAME, user_id="traveller")
        adk_session = session.id
        _chat_runners[sid] = (runner, adk_session, tracer)

    try:
        reply = await _drain(runner, adk_session, body.message)
    except Exception as exc:  # provider errors must reach the UI intact
        raise HTTPException(502, f"{type(exc).__name__}: {exc}") from exc

    done = "PROFILE_COMPLETE" in reply
    events: list[dict[str, Any]] = []
    while not tracer.queue.empty():
        item = tracer.queue.get_nowait()
        if item:
            events.append(item)

    return {
        "session_id": sid,
        "reply": reply.replace("PROFILE_COMPLETE", "").strip(),
        "profile_complete": done,
        "events": events,
        "usage": tracer.summary(),
    }


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.post("/api/plan")
async def plan(body: PlanIn) -> StreamingResponse:
    """Run the pipeline, streaming trace events as they happen."""
    if missing_keys():
        raise HTTPException(503, f"missing credentials: {', '.join(missing_keys())}")

    tracer = Tracer(run_id=uuid.uuid4().hex[:12])

    async def run_pipeline() -> None:
        try:
            runner = InMemoryRunner(agent=build_pipeline(tracer), app_name=APP_NAME)
            session = await runner.session_service.create_session(
                app_name=APP_NAME, user_id="traveller")
            tracer.emit("run_started", provider=provider(),
                        models={t: model_id(t) for t in ("reasoning", "worker", "bulk")})

            seen_agent: str | None = None
            async for ev in runner.run_async(
                user_id="traveller", session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=body.brief)]),
            ):
                if ev.author != seen_agent:
                    seen_agent = ev.author
                    tracer.emit("stage", agent=seen_agent)

            final = await runner.session_service.get_session(
                app_name=APP_NAME, user_id="traveller", session_id=session.id)
            state = dict(final.state)

            def parsed(key: str) -> Any:
                value = state.get(key)
                if isinstance(value, str):
                    try:
                        return json.loads(value)
                    except json.JSONDecodeError:
                        return value
                return value

            tracer.emit("result",
                        document=state.get("final_itinerary", ""),
                        itinerary=parsed("itinerary"),
                        profile=parsed("traveller_profile"),
                        deterministic=state.get("deterministic_report"),
                        reviewer=parsed("validation"),
                        usage=tracer.summary())
        except Exception as exc:
            tracer.emit("error", message=f"{type(exc).__name__}: {exc}")
        finally:
            tracer.close()

    async def stream():
        task = asyncio.create_task(run_pipeline())
        try:
            while True:
                item = await tracer.queue.get()
                if item is None:
                    break
                yield _sse(item)
        finally:
            if not task.done():
                task.cancel()
        yield _sse({"kind": "done"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

