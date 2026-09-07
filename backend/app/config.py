"""Provider and model-tier configuration.

The graph is provider-agnostic: agents are given a tier (reasoning / worker /
bulk) and this module resolves the tier to a concrete model. Switch the whole
system between Gemini and Claude with one environment variable.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
KB_PATH = ROOT / "kb" / "sri_lanka.json"
APP_NAME = "multi-agent-test"

# tier -> model id, per provider
PROVIDERS: dict[str, dict[str, str]] = {
    "gemini": {
        "reasoning": "gemini-3.1-pro-preview",
        "worker": "gemini-3.8-flash",
        "bulk": "gemini-3.8-flash",
    },
    "anthropic": {
        "reasoning": "claude-sonnet-5",
        "worker": "claude-haiku-4-5",
        "bulk": "claude-haiku-4-5",
    },
}

# USD per 1M tokens: (input, output). Used for the per-agent cost readout.
PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.1-pro-preview": (2.00, 12.00),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-flash-lite-latest": (0.20, 1.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small")

# Transient provider faults only. Retrying a genuine bug just spends money
# slowly, so this is an allowlist rather than "retry everything".
RETRYABLE_EXCEPTIONS = [
    "ServerError",            # google-genai 5xx, e.g. 503 UNAVAILABLE
    "ClientError",            # google-genai 429 rate limit
    "APIConnectionError",     # transport dropped, either provider
    "RateLimitError",         # anthropic / litellm
    "InternalServerError",    # anthropic / litellm
    "APIStatusError",         # anthropic 5xx
    "ServiceUnavailableError",
    "Timeout",
    "APITimeoutError",
]

RETRY_MAX_ATTEMPTS = int(os.environ.get("RETRY_MAX_ATTEMPTS", "4"))


def load_env() -> None:
    # .env.local holds real credentials and is gitignored; .env is the
    # shareable variant. Both are optional. .env.local is read first and
    # nothing here overrides, so it wins wherever the two overlap.
    for name in (".env.local", ".env"):
        path = ROOT / name
        if path.exists():
            load_dotenv(path, override=False)
    # ADK reads GOOGLE_API_KEY; accept the GEMINI_API_KEY spelling too. Drop the
    # alias afterwards — google-genai warns on every single request when both
    # are set, which buries real messages in the log.
    if os.environ.get("GEMINI_API_KEY"):
        os.environ.setdefault("GOOGLE_API_KEY", os.environ["GEMINI_API_KEY"])
        os.environ.pop("GEMINI_API_KEY", None)
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")


def provider() -> str:
    return os.environ.get("MODEL_PROVIDER", "gemini").lower()


def model_id(tier: str) -> str:
    """Resolve a tier to a concrete model id for the active provider."""
    p = provider()
    if p not in PROVIDERS:
        raise SystemExit(f"MODEL_PROVIDER={p!r} is not one of {sorted(PROVIDERS)}")
    override = os.environ.get(f"MODEL_{tier.upper()}")
    return override or PROVIDERS[p][tier]


def build_model(tier: str):
    """Return whatever ADK expects for this provider: a bare id, or a wrapper.

    Gemini is native to ADK and takes a plain string. Claude goes through the
    LiteLlm connector, which needs an `anthropic/` prefix.
    """
    mid = model_id(tier)
    if provider() == "gemini":
        return mid
    from google.adk.models.lite_llm import LiteLlm
    return LiteLlm(model=f"anthropic/{mid}")


def price(model: str) -> tuple[float, float]:
    return PRICES.get(model.replace("anthropic/", ""), (0.0, 0.0))


def missing_keys() -> list[str]:
    """Which credentials the active configuration still needs."""
    need = ["OPENAI_API_KEY"]  # embeddings only; Anthropic has no embeddings API
    need.append("GOOGLE_API_KEY" if provider() == "gemini" else "ANTHROPIC_API_KEY")
    return [k for k in need if not os.environ.get(k)]
