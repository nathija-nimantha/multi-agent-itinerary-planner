"""Retrieval over the destination knowledge base.

Deliberately small: ~40 documents do not justify a vector database. Embeddings
are computed once with OpenAI (Anthropic has no embeddings endpoint) and cached
to disk, then scored with numpy cosine similarity. Swap this module for
Firestore vector search or Vertex AI Vector Search when the corpus outgrows
memory — nothing above it changes.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from openai import OpenAI

from .config import EMBED_MODEL, KB_PATH

CACHE_PATH = KB_PATH.parent / ".embeddings.npz"


@lru_cache(maxsize=1)
def load_kb() -> dict[str, Any]:
    return json.loads(KB_PATH.read_text())


@lru_cache(maxsize=1)
def places_by_id() -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in load_kb()["places"]}


def _documents() -> list[dict[str, Any]]:
    """Flatten the KB into retrievable documents."""
    kb = load_kb()
    docs: list[dict[str, Any]] = []
    for p in kb["places"]:
        text = (
            f"{p['name']} ({p['region']}, {p['type']}). {p['summary']} "
            f"Tags: {', '.join(p['tags'])}. Typical visit {p['suggested_hours']}h, "
            f"entry {p['entry_cost_usd_pp']} USD per person. Opening: {p['opening']}."
        )
        docs.append({"id": p["id"], "kind": "place", "base": p["base"], "text": text})
    for n in kb["practical_notes"]:
        docs.append({"id": n["id"], "kind": "note", "base": None,
                     "text": f"[{n['topic']}] {n['text']}"})
    return docs


def _corpus_fingerprint(docs: list[dict[str, Any]]) -> str:
    joined = "\n".join(d["text"] for d in docs)
    return hashlib.sha256((EMBED_MODEL + joined).encode()).hexdigest()


@lru_cache(maxsize=1)
def _index() -> tuple[list[dict[str, Any]], np.ndarray]:
    docs = _documents()
    fp = _corpus_fingerprint(docs)
    if CACHE_PATH.exists():
        cached = np.load(CACHE_PATH, allow_pickle=True)
        if str(cached["fingerprint"]) == fp:
            return docs, cached["vectors"]
    client = OpenAI()
    resp = client.embeddings.create(model=EMBED_MODEL, input=[d["text"] for d in docs])
    vectors = np.array([e.embedding for e in resp.data], dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    np.savez(CACHE_PATH, vectors=vectors, fingerprint=fp)
    return docs, vectors


def search(query: str, top_k: int = 6, kind: str | None = None) -> list[dict[str, Any]]:
    """Semantic search over places and practical notes."""
    docs, vectors = _index()
    client = OpenAI()
    qv = np.array(
        client.embeddings.create(model=EMBED_MODEL, input=[query]).data[0].embedding,
        dtype=np.float32,
    )
    qv /= np.linalg.norm(qv)
    scores = vectors @ qv
    order = np.argsort(-scores)
    results: list[dict[str, Any]] = []
    for i in order:
        doc = docs[int(i)]
        if kind and doc["kind"] != kind:
            continue
        results.append({**doc, "score": round(float(scores[int(i)]), 4)})
        if len(results) >= top_k:
            break
    return results


def currency_rate(code: str) -> float | None:
    """Units of `code` per 1 USD, or None if the currency is not in the table."""
    block = load_kb().get("currency_rates_per_usd", {})
    return block.get("rates", {}).get((code or "USD").strip().upper())


def cost_rates() -> dict[str, Any]:
    return load_kb().get("cost_rates_usd", {})


def travel_hours(a: str, b: str) -> float | None:
    """Road hours between two base locations, or None if the pair is unknown."""
    if a == b:
        return 0.0
    key = "|".join(sorted([a, b]))
    return load_kb()["travel_times_h"].get(key)
