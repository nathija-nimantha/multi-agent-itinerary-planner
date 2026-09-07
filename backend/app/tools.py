"""Tools the agents call.

`validate_itinerary` is the heart of the design: it is pure Python, it reads the
stored itinerary straight out of session state, and it decides pass/fail without
consulting a model. Every check here is one an LLM reviewer would perform
unreliably and expensively. The Validator agent's job is only to interpret what
this function returns and to catch the qualitative problems it cannot express.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from google.adk.tools import ToolContext

from .rag import cost_rates, currency_rate, load_kb, places_by_id, search, travel_hours

PACE_ACTIVITY_CAP = {"relaxed": 2, "moderate": 3, "packed": 4}
# Floor, not just ceiling. A plan that under-delivers against the brief is as
# wrong as one that overreaches — it just fails quietly, which is worse.
# Measured in hours, not activity count: a 5h safari is a day and a 0.5h
# waterfall stop is not. Targets calibrated against runs judged good by review
# (3.8-5.1h/day) versus one judged thin (3.2h/day with a dead day).
PACE_HOURS_TARGET = {"relaxed": 3.0, "moderate": 4.0, "packed": 5.5}
DEGENERATE_RATIO = 0.5        # of target, below which the plan is not a trip
MIN_VARIETY_RATIO = 0.7       # distinct places per full day, below which it is thin
MIN_BUDGET_USE = 0.15         # activity spend as a share of stated budget
MAX_DAY_HOURS = 11.0
MAX_TRANSFER_HOURS = 6.0
BUDGET_TOLERANCE = 1.05
FX_TOLERANCE = 0.05           # how far a model's own conversion may drift


def kb_search(query: str, kind: str = "") -> dict[str, Any]:
    """Search the destination knowledge base for places and practical notes.

    Args:
        query: What you are looking for, in natural language. Describe the
            traveller's need ("calm beach suitable for a five-year-old") rather
            than guessing a place name.
        kind: Optional filter. "place" for attractions only, "note" for
            practical planning advice only, "" for both.

    Returns:
        Ranked matches. Every place carries the id you must use in the
        itinerary, its base location, cost and typical duration.
    """
    hits = search(query, top_k=6, kind=kind or None)
    out = []
    for h in hits:
        item = {"id": h["id"], "kind": h["kind"], "text": h["text"], "score": h["score"]}
        if h["kind"] == "place":
            p = places_by_id()[h["id"]]
            item |= {
                "base": p["base"], "entry_cost_usd_pp": p["entry_cost_usd_pp"],
                "suggested_hours": p["suggested_hours"], "best_months": p["best_months"],
            }
        out.append(item)
    return {"results": out}


def travel_time(from_base: str, to_base: str) -> dict[str, Any]:
    """Road travel hours between two base locations.

    Args:
        from_base: Base location id you are leaving, e.g. "kandy".
        to_base: Base location id you are travelling to, e.g. "ella".

    Returns:
        hours, or known=false when the pair is not in the route table. A pair
        that is not in the table is not a route you may put in the itinerary.
    """
    h = travel_hours(from_base, to_base)
    if h is None:
        return {"known": False, "hours": None,
                "bases": sorted({p["base"] for p in load_kb()["places"]})}
    return {"known": True, "hours": h}


def _serves(place: dict[str, Any], interest: str) -> bool:
    """Does this place answer a stated interest? Tolerates beach/beaches."""
    want = interest.strip().lower()
    for tag in place["tags"]:
        t = tag.lower()
        if t == want or want.startswith(t) or t.startswith(want):
            return True
    return False


def _coerce(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def validate_itinerary(tool_context: ToolContext) -> dict[str, Any]:
    """Run every deterministic check against the itinerary currently in state.

    Call this before forming any judgement. It verifies that each place exists
    in the knowledge base, that the day count matches the trip length, that the
    budget holds, that transfers are real routes of sane length, that no day is
    overloaded for the stated pace, and that seasonality fits the travel dates.

    Returns:
        A structured report: passed, plus every issue found with a severity and
        the day it belongs to.
    """
    itin = _coerce(tool_context.state.get("itinerary"))
    profile = _coerce(tool_context.state.get("traveller_profile"))
    if not itin or not profile:
        return {"passed": False, "issues": [
            {"severity": "critical", "code": "missing_state", "day": None,
             "message": "itinerary or traveller_profile is absent or unparseable"}], "computed": {}}

    known = places_by_id()
    party = int(profile.get("party_adults", 0)) + int(profile.get("party_children", 0))
    pace = profile.get("pace", "moderate")
    cap = PACE_ACTIVITY_CAP.get(pace, 3)
    issues: list[dict[str, Any]] = []

    def fail(sev: str, code: str, msg: str, day: int | None = None) -> None:
        issues.append({"severity": sev, "code": code, "day": day, "message": msg})

    days = itin.get("days", [])
    expected = int(profile.get("nights", 0)) + 1
    if len(days) != expected:
        fail("critical", "day_count_mismatch",
             f"{len(days)} days planned but {profile.get('nights')} nights means {expected} days")

    try:
        start = date.fromisoformat(profile["arrival_date"])
    except (KeyError, ValueError):
        start = None
        fail("warning", "unparseable_arrival_date", "arrival_date is not an ISO date")

    seen: dict[str, int] = {}
    computed_cost = 0.0
    prev_base: str | None = None

    for idx, d in enumerate(days):
        dn = d.get("day", idx + 1)
        base = d.get("base")
        acts = d.get("activities", []) or []
        month = (start + timedelta(days=idx)).month if start else None

        transfer_h = 0.0
        tr = d.get("transfer")
        if tr:
            a, b = tr.get("from_base"), tr.get("to_base")
            actual = travel_hours(a, b) if a and b else None
            if actual is None:
                fail("critical", "unknown_route",
                     f"no known road route {a} -> {b}; invented transfers are not allowed", dn)
            else:
                transfer_h = actual
                claimed = float(tr.get("hours", actual))
                if abs(claimed - actual) > 0.75:
                    fail("warning", "transfer_time_wrong",
                         f"claimed {claimed}h for {a} -> {b}, route table says {actual}h", dn)
                if actual > MAX_TRANSFER_HOURS:
                    fail("critical", "transfer_too_long",
                         f"{a} -> {b} is {actual}h, over the {MAX_TRANSFER_HOURS}h single-day limit", dn)
            if prev_base and a and a != prev_base:
                fail("critical", "discontinuous_route",
                     f"day {dn} departs from {a} but the party slept in {prev_base}", dn)

        if len(acts) > cap:
            fail("warning", "overpacked_day",
                 f"{len(acts)} activities on a '{pace}' pace day (cap {cap})", dn)

        activity_h = 0.0
        for a in acts:
            pid = a.get("place_id")
            place = known.get(pid)
            if not place:
                fail("critical", "unknown_place",
                     f"'{pid}' is not in the knowledge base — it cannot be scheduled", dn)
                continue
            activity_h += float(a.get("duration_hours", place["suggested_hours"]))
            computed_cost += float(a.get("cost_usd_pp", place["entry_cost_usd_pp"])) * party
            if pid in seen:
                fail("warning", "duplicate_place",
                     f"{place['name']} already scheduled on day {seen[pid]}", dn)
            else:
                seen[pid] = dn
            if base and place["base"] != base:
                reach = travel_hours(base, place["base"])
                if reach is None or reach > 2.0:
                    fail("warning", "activity_far_from_base",
                         f"{place['name']} is in {place['base']} but the party is based in {base}", dn)
            if month and month not in place["best_months"]:
                fail("warning", "out_of_season",
                     f"{place['name']} is outside its best months in month {month}", dn)

        if activity_h + transfer_h > MAX_DAY_HOURS:
            fail("warning", "day_overflow",
                 f"{activity_h + transfer_h:.1f}h of activity plus transfer exceeds {MAX_DAY_HOURS}h", dn)
        if base:
            prev_base = base

    # ---- lower bounds: is the plan actually delivering the trip? ----
    # Every check above asks "is this too much?". Without these, a near-empty
    # itinerary passes clean — which is the quieter and more damaging failure.
    last = len(days)
    full_days: list[float] = []
    empty: list[int] = []
    for idx, d in enumerate(days):
        dn = d.get("day", idx + 1)
        acts = d.get("activities", []) or []
        # Count each place once. Without this, a planner told to fill the days
        # satisfies the floor by scheduling the same beach three times — which
        # is exactly what happened the first time this check shipped.
        hours = sum(float(a.get("duration_hours", 0) or 0) for a in acts
                    if seen.get(a.get("place_id")) == dn)
        if dn in (1, last):
            continue  # arrival and departure days may legitimately be free
        full_days.append(hours)
        if acts:
            continue
        tr = d.get("transfer")
        moved = travel_hours(tr.get("from_base"), tr.get("to_base")) if tr else 0.0
        if (moved or 0.0) < 4.0:
            empty.append(dn)
            # Critical, not a warning: arrival, departure and long-transfer days
            # are already exempt, so if this fires there is a genuine hole in the
            # trip — and it must reach the reviser rather than pass quietly.
            fail("critical", "empty_day",
                 "no activities scheduled and no long transfer to justify it", dn)

    if len(empty) > 1:
        fail("critical", "trip_has_dead_days",
             f"days {', '.join(str(d) for d in empty)} are empty with no transfer to "
             f"explain them; the traveller is paying for those nights")

    target = PACE_HOURS_TARGET.get(pace, 4.0)
    mean_hours = sum(full_days) / len(full_days) if full_days else 0.0
    if full_days and mean_hours < target * DEGENERATE_RATIO:
        fail("critical", "itinerary_too_thin",
             f"{mean_hours:.1f}h of activity per full day against a '{pace}' target of "
             f"{target:.1f}h — this does not amount to a trip")
    elif full_days and mean_hours < target:
        fail("warning", "itinerary_underfilled",
             f"{mean_hours:.1f}h of activity per full day against a '{pace}' target of "
             f"{target:.1f}h; the traveller paid for those days either way")

    n_full = len(full_days)
    if n_full and len(seen) < n_full * MIN_VARIETY_RATIO:
        fail("critical", "insufficient_variety",
             f"{len(seen)} distinct places across {n_full} full days — repeating stops "
             f"is not the same as filling the trip")
    elif n_full and len(seen) < n_full:
        fail("warning", "insufficient_variety",
             f"{len(seen)} distinct places across {n_full} full days; the plan leans on "
             f"repeat visits where the knowledge base has unused options")

    # Either flag alone is arguable — a quiet trip, a favourite place revisited.
    # Both at once is not: the plan is short on hours AND short on places, which
    # is under-delivery however it is framed.
    thin_codes = {i["code"] for i in issues}
    if {"itinerary_underfilled", "insufficient_variety"} <= thin_codes:
        fail("critical", "plan_under_delivers",
             f"{mean_hours:.1f}h per full day across only {len(seen)} distinct places — "
             f"short on both hours and variety; this is a thinner trip than was asked for")

    bases = [d.get("base") for d in days if d.get("base")]
    changes = sum(1 for a, b in zip(bases, bases[1:]) if a != b)
    allowed = {"relaxed": 0.34, "moderate": 0.55, "packed": 0.8}.get(pace, 0.55)
    if len(days) >= 4 and changes > len(days) * allowed:
        fail("warning", "too_many_base_changes",
             f"{changes} base changes across {len(days)} days on a '{pace}' pace; "
             f"the party spends the trip in the car and re-packing every night")

    interests = [i for i in (profile.get("interests") or []) if str(i).strip()]
    served: set[str] = set()
    if interests:
        served = {i for i in interests for pid in seen if _serves(known[pid], str(i))}
        for missing in [i for i in interests if i not in served]:
            fail("critical", "interest_unserved",
                 f"'{missing}' is a stated interest and nothing in the plan answers it")

    budget = float(profile.get("budget_usd_total", 0))
    if budget and computed_cost < budget * MIN_BUDGET_USE and mean_hours < target:
        fail("warning", "budget_underused",
             f"only {computed_cost:.0f} USD of activities against a {budget:.0f} USD budget "
             f"on an underfilled plan — the traveller asked for a bigger trip than this")

    # ---- currency: verify the conversion instead of trusting it ----
    stated_ccy = str(profile.get("budget_currency", "USD") or "USD").upper()
    stated_amount = float(profile.get("budget_amount", 0) or 0)
    rate = currency_rate(stated_ccy)
    if stated_amount and rate is None:
        fail("critical", "unknown_currency",
             f"budget given in {stated_ccy}, which has no rate in the knowledge base; "
             f"the USD figure cannot be verified")
    elif stated_amount and rate:
        expected = stated_amount / rate
        if budget and abs(expected - budget) > max(1.0, expected * FX_TOLERANCE):
            fail("critical", "currency_conversion_wrong",
                 f"{stated_amount:,.0f} {stated_ccy} is {expected:,.0f} USD at the "
                 f"knowledge-base rate of {rate:g}/USD, but the profile records "
                 f"{budget:,.0f} USD")
        elif not budget:
            budget = expected

    # ---- affordability: the whole trip, not just the ticket prices ----
    # The activity total was never the number that mattered. A plan whose
    # entries fit the budget can still be impossible once the driver, the beds
    # and the meals are counted — which is exactly how a 500 USD trip shipped
    # with a 1,400 USD plan attached.
    rates = cost_rates()
    nights = int(profile.get("nights", 0) or 0)
    est: dict[str, float] = {}
    if budget and nights and party:
        driver_days = sum(1 for d in days if d.get("transfer"))
        lodging = rates.get("lodging_pp_per_night", {}).get("guesthouse", {})
        meals = rates.get("meals_pp_per_day", {})
        driver = rates.get("driver_guide_per_day", {})

        def band(edge: str) -> float:
            return (
                computed_cost
                + party * nights * float(lodging.get(edge, 0))
                + party * (nights + 1) * float(meals.get(edge, 0))
                + driver_days * float(driver.get(edge, 0))
            )

        low, high = band("low"), band("high")
        est = {"all_in_low_usd": round(low, 2), "all_in_high_usd": round(high, 2),
               "driver_days": driver_days}
        if low > budget:
            fail("critical", "budget_impossible",
                 f"the cheapest credible version of this plan is {low:,.0f} USD "
                 f"({computed_cost:,.0f} activities + {party * nights} guesthouse "
                 f"nights + meals + {driver_days} driver days) against a "
                 f"{budget:,.0f} USD budget. It cannot be booked")
        elif high > budget:
            fail("warning", "budget_tight",
                 f"all-in estimate runs {low:,.0f}-{high:,.0f} USD against a "
                 f"{budget:,.0f} USD budget; only the lower end fits")

    if budget and computed_cost > budget * BUDGET_TOLERANCE:
        fail("critical", "budget_exceeded",
             f"activity and entry costs alone total {computed_cost:.0f} USD against a "
             f"{budget:.0f} USD budget, before transport, lodging and meals")

    stated = float(itin.get("estimated_cost_usd", 0) or 0)
    if stated and abs(stated - computed_cost) > max(25.0, computed_cost * 0.1):
        fail("warning", "cost_mismatch",
             f"itinerary claims {stated:.0f} USD, line items sum to {computed_cost:.0f} USD")

    report = {
        "passed": not any(i["severity"] == "critical" for i in issues),
        "issues": issues,
        "computed": {
            "party_size": party, "days_planned": len(days), "days_expected": expected,
            "activity_cost_usd": round(computed_cost, 2), "budget_usd": budget,
            "distinct_places": len(seen), "pace_cap": cap,
            "hours_per_full_day": round(mean_hours, 1), "pace_hours_target": target,
            "empty_days": len(empty), "full_days": len(full_days),
            "base_changes": changes, "budget_currency": stated_ccy,
            "budget_amount": stated_amount, **est,
            "interests_stated": len(interests), "interests_served": len(served),
        },
    }
    # Persist the machine report verbatim. The Validator agent rewrites these
    # findings in its own words, which is useful for the traveller and useless
    # as an audit trail — so keep the unedited version alongside it.
    tool_context.state["deterministic_report"] = report
    return report
