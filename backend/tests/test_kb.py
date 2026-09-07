"""Integrity checks on the knowledge base itself.

The corpus is data, and data rots silently. A route key stored out of sorted
order made 25 of 62 real routes unreachable, which the planner would have
experienced as "that road does not exist" with no error anywhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag import load_kb, travel_hours  # noqa: E402

KB = load_kb()
PLACES = KB["places"]
ROUTES = KB["travel_times_h"]
BASES = {p["base"] for p in PLACES}


def test_place_ids_are_unique():
    ids = [p["id"] for p in PLACES]
    assert len(ids) == len(set(ids))


def test_every_place_has_the_fields_the_validator_reads():
    for p in PLACES:
        for field in ("id", "name", "base", "summary", "tags", "best_months",
                      "suggested_hours", "entry_cost_usd_pp", "opening"):
            assert field in p, f"{p.get('id')} missing {field}"
        assert p["best_months"], f"{p['id']} has no season"
        assert all(1 <= m <= 12 for m in p["best_months"]), p["id"]
        assert p["suggested_hours"] > 0, p["id"]


def test_route_keys_are_stored_in_sorted_order():
    """travel_hours() sorts the pair before lookup, so the key must be sorted."""
    unsorted = [k for k in ROUTES if k != "|".join(sorted(k.split("|")))]
    assert not unsorted, f"unreachable routes: {unsorted}"


def test_route_endpoints_are_real_base_locations():
    endpoints = {e for k in ROUTES for e in k.split("|")}
    assert not endpoints - BASES, f"routes to nowhere: {sorted(endpoints - BASES)}"


def test_every_route_resolves_in_both_directions():
    for key, hours in ROUTES.items():
        a, b = key.split("|")
        assert travel_hours(a, b) == hours
        assert travel_hours(b, a) == hours, f"{b} -> {a} not symmetric"


def test_every_base_is_reachable_from_somewhere():
    connected = {e for k in ROUTES for e in k.split("|")}
    assert not BASES - connected, f"stranded bases: {sorted(BASES - connected)}"


def test_travel_hours_are_plausible():
    for key, hours in ROUTES.items():
        assert 0 < hours <= 9, f"{key} = {hours}h"
