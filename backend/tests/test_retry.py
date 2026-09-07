"""The retry policy must match the errors that actually stopped runs.

ADK matches on `type(exception).__name__`, so an allowlist entry that is
spelled wrong fails silently — the run just dies as before. These tests use
real exception instances rather than trusting the strings.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.adk.workflow._node_state import NodeState
from google.adk.workflow.utils._retry_utils import _get_retry_delay, _should_retry_node

from app.agents import RETRY


def state(attempt: int) -> NodeState:
    s = NodeState()
    s.attempt_count = attempt
    return s


def test_the_error_that_killed_a_live_run_is_retried():
    """google.genai ServerError 503 UNAVAILABLE — observed in production logs."""
    from google.genai.errors import ServerError

    exc = ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}})
    assert type(exc).__name__ in RETRY.exceptions
    assert _should_retry_node(exc, RETRY, state(1))


def test_rate_limiting_is_retried():
    from google.genai.errors import ClientError

    exc = ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}})
    assert _should_retry_node(exc, RETRY, state(1))


def test_programming_errors_are_not_retried():
    """Retrying a real bug just spends money slowly."""
    for exc in (KeyError("itinerary"), ValueError("bad schema"), TypeError("nope")):
        assert not _should_retry_node(exc, RETRY, state(1)), exc


def test_attempts_are_bounded():
    from google.genai.errors import ServerError

    exc = ServerError(503, {"error": {}})
    assert _should_retry_node(exc, RETRY, state(RETRY.max_attempts - 1))
    assert not _should_retry_node(exc, RETRY, state(RETRY.max_attempts))


def test_delay_backs_off():
    first = _get_retry_delay(RETRY, state(1))
    later = _get_retry_delay(RETRY, state(3))
    assert later > first, (first, later)
    assert later <= RETRY.max_delay
