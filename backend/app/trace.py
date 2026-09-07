"""Turns ADK's callback hooks into a typed event stream for the UI.

This is what makes the hidden agent panel possible: every prompt an agent
receives, every tool it calls, every token it spends and every structured
object it returns is captured at the point ADK produces it and pushed onto a
per-run queue that the SSE endpoint drains.

Nothing here changes agent behaviour — the callbacks all return None, which
tells ADK to proceed normally.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

from .config import price

MAX_TEXT = 20_000  # per-field cap, so one runaway prompt cannot flood the stream


def _clip(text: str, limit: int = MAX_TEXT) -> dict[str, Any]:
    text = text or ""
    if len(text) <= limit:
        return {"text": text, "truncated": False, "full_length": len(text)}
    return {"text": text[:limit], "truncated": True, "full_length": len(text)}


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


@dataclass
class Tracer:
    """Collects events for one pipeline run."""

    run_id: str
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    totals: dict[str, dict[str, float]] = field(default_factory=dict)
    _started: dict[str, float] = field(default_factory=dict)

    # ---- emission -------------------------------------------------------

    def emit(self, kind: str, **payload: Any) -> None:
        self.queue.put_nowait({"kind": kind, "run_id": self.run_id,
                               "ts": time.time(), **payload})

    def close(self) -> None:
        self.queue.put_nowait(None)

    def summary(self) -> dict[str, Any]:
        total = sum(v["cost"] for v in self.totals.values())
        return {"agents": self.totals, "total_cost_usd": round(total, 4)}

    # ---- ADK callback factory -------------------------------------------

    def callbacks(self, agent: str, model: str, tier: str) -> dict[str, Any]:
        """kwargs to splat into an LlmAgent so its whole life is observable."""

        def before_model(*, callback_context, llm_request, **_):
            ctx = callback_context
            self._started[agent] = time.time()
            cfg = getattr(llm_request, "config", None)
            system = getattr(cfg, "system_instruction", None) or ""
            if not isinstance(system, str):
                system = str(system)
            contents = getattr(llm_request, "contents", None) or []
            tools = sorted((getattr(llm_request, "tools_dict", None) or {}).keys())
            self.emit("agent_prompt", agent=agent, model=model, tier=tier,
                      system=_clip(system), turns=len(contents), tools=tools,
                      state_keys=sorted(ctx.state.to_dict().keys())
                      if hasattr(ctx.state, "to_dict") else [])
            return None

        def after_model(*, callback_context, llm_response, **_):
            ctx = callback_context
            if getattr(llm_response, "partial", False):
                return None
            usage = getattr(llm_response, "usage_metadata", None)
            tin = getattr(usage, "prompt_token_count", 0) or 0
            tout = getattr(usage, "candidates_token_count", 0) or 0
            cin, cout = price(model)
            cost = tin / 1e6 * cin + tout / 1e6 * cout
            row = self.totals.setdefault(
                agent, {"model": model, "tier": tier, "input": 0, "output": 0, "cost": 0.0})
            row["input"] += tin
            row["output"] += tout
            row["cost"] = round(row["cost"] + cost, 6)

            text = ""
            content = getattr(llm_response, "content", None)
            for part in (getattr(content, "parts", None) or []):
                if getattr(part, "text", None):
                    text += part.text
            if text:
                self.emit("agent_output", agent=agent, model=model, tier=tier,
                          content=_clip(text),
                          tokens={"input": tin, "output": tout},
                          cost_usd=round(cost, 6),
                          elapsed_s=round(time.time() - self._started.get(agent, time.time()), 2))
            return None

        # ADK spells these differently on the two hooks (`args` before,
        # `tool_args` + `result` after), so accept either.
        def before_tool(*, tool=None, args=None, tool_args=None, **_):
            self.emit("tool_call", agent=agent, tool=getattr(tool, "name", str(tool)),
                      args=_jsonable(args if args is not None else tool_args))
            return None

        def after_tool(*, tool=None, args=None, tool_args=None,
                       tool_response=None, result=None, **_):
            payload = tool_response if tool_response is not None else result
            self.emit("tool_result", agent=agent, tool=getattr(tool, "name", str(tool)),
                      args=_jsonable(args if args is not None else tool_args),
                      result=_jsonable(payload))
            return None

        return {
            "before_model_callback": before_model,
            "after_model_callback": after_model,
            "before_tool_callback": before_tool,
            "after_tool_callback": after_tool,
        }
