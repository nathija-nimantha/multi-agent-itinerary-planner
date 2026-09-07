"""Regression tests for the deterministic checks.

These run without touching a model or the network, which is the point: the
checks that decide pass/fail must be cheap enough to run on every commit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tools import validate_itinerary  # noqa: E402


class Ctx:
    def __init__(self, state: dict) -> None:
        self.state = state


PROFILE = {
    "party_adults": 2, "party_children": 1, "child_ages": [6],
    "arrival_date": "2027-01-14", "nights": 2, "budget_usd_total": 500,
    "pace": "relaxed",
}


def act(place_id: str, hours: float = 2.0, cost: float = 10.0) -> dict:
    return {"place_id": place_id, "name": place_id, "start_time": "09:00",
            "duration_hours": hours, "cost_usd_pp": cost, "why": "requested"}


def run(days: list[dict], profile: dict | None = None, stated: float = 0.0) -> dict:
    itin = {"title": "t", "summary": "s", "estimated_cost_usd": stated, "days": days}
    return validate_itinerary(Ctx({"itinerary": itin, "traveller_profile": profile or PROFILE}))


def codes(report: dict) -> set[str]:
    return {i["code"] for i in report["issues"]}


def test_clean_itinerary_passes():
    report = run([
        {"day": 1, "base": "galle", "activities": [act("galle_fort", 3, 0)]},
        {"day": 2, "base": "galle", "activities": [act("unawatuna_beach", 3, 0)]},
        {"day": 3, "base": "mirissa",
         "transfer": {"from_base": "galle", "to_base": "mirissa", "hours": 1.0},
         "activities": [act("weligama_surf", 2, 20)]},
    ])
    assert report["passed"], report["issues"]
    assert report["computed"]["activity_cost_usd"] == 60.0  # 20 pp x 3 people


def test_hallucinated_place_is_critical():
    report = run([
        {"day": 1, "base": "galle", "activities": [act("ruwanwelisaya_stupa")]},
        {"day": 2, "base": "galle", "activities": [act("galle_fort")]},
        {"day": 3, "base": "galle", "activities": [act("unawatuna_beach")]},
    ])
    assert not report["passed"]
    assert "unknown_place" in codes(report)


def test_invented_route_is_critical():
    report = run([
        {"day": 1, "base": "kandy", "activities": [act("temple_tooth")]},
        {"day": 2, "base": "jaffna",
         "transfer": {"from_base": "kandy", "to_base": "jaffna", "hours": 2.0},
         "activities": [act("jaffna")]},
        {"day": 3, "base": "jaffna", "activities": [act("jaffna")]},
    ])
    assert "unknown_route" in codes(report)


def test_party_cannot_teleport_between_days():
    report = run([
        {"day": 1, "base": "kandy", "activities": [act("temple_tooth")]},
        {"day": 2, "base": "ella",
         "transfer": {"from_base": "colombo", "to_base": "ella", "hours": 6.0},
         "activities": [act("little_adams_peak")]},
        {"day": 3, "base": "ella", "activities": [act("ella_nine_arch")]},
    ])
    assert "discontinuous_route" in codes(report)


def test_day_count_must_match_nights():
    report = run([{"day": 1, "base": "galle", "activities": [act("galle_fort")]}])
    assert "day_count_mismatch" in codes(report)


def test_budget_breach_is_critical():
    report = run([
        {"day": 1, "base": "yala", "activities": [act("yala_safari", 5, 70)]},
        {"day": 2, "base": "yala", "activities": [act("udawalawe_safari", 4, 50)]},
        {"day": 3, "base": "yala", "activities": [act("yala_safari", 5, 70)]},
    ])
    assert "budget_exceeded" in codes(report)
    assert not report["passed"]


def test_pace_cap_and_duplicates_are_warnings_not_failures():
    """An otherwise substantial trip must not fail on soft issues alone."""
    report = run([
        {"day": 1, "base": "kandy", "activities": []},
        {"day": 2, "base": "kandy", "activities": [
            act("temple_tooth", 2, 10), act("kandy_lake_market", 2, 0),
            act("peradeniya_gardens", 2.5, 10)]},
        {"day": 3, "base": "kandy", "activities": [
            act("temple_tooth", 2, 10), act("kandy_cultural_show", 1, 8)]},
        {"day": 4, "base": "kandy", "activities": [act("kandy_ella_train", 7, 10)]},
        {"day": 5, "base": "kandy", "activities": []},
    ], profile=PROFILE | {"nights": 4, "budget_usd_total": 2500,
                          "budget_amount": 2500, "budget_currency": "USD"})
    assert {"overpacked_day", "duplicate_place"} <= codes(report)
    assert report["passed"], "soft issues must not fail the run"


def test_seasonality_flags_yala_october_closure():
    profile = PROFILE | {"arrival_date": "2027-09-20"}
    report = run([
        {"day": 1, "base": "yala", "activities": [act("yala_safari", 5, 70)]},
        {"day": 2, "base": "yala", "activities": [act("udawalawe_safari", 4, 50)]},
        {"day": 3, "base": "yala", "activities": [act("udawalawe_safari", 4, 50)]},
    ], profile=profile | {"budget_usd_total": 5000})
    assert "out_of_season" in codes(report)


def test_missing_state_fails_closed():
    report = validate_itinerary(Ctx({}))
    assert not report["passed"]
    assert "missing_state" in codes(report)


@pytest.mark.parametrize("stated,expect", [(60.0, False), (500.0, True)])
def test_cost_mismatch_detection(stated: float, expect: bool):
    report = run([
        {"day": 1, "base": "galle", "activities": [act("galle_fort", 3, 0)]},
        {"day": 2, "base": "galle", "activities": [act("unawatuna_beach", 3, 0)]},
        {"day": 3, "base": "mirissa",
         "transfer": {"from_base": "galle", "to_base": "mirissa", "hours": 1.0},
         "activities": [act("weligama_surf", 2, 20)]},
    ], stated=stated)
    assert ("cost_mismatch" in codes(report)) is expect


# --- lower bounds: the plan must actually deliver the trip -------------------

FULL = {"party_adults": 2, "party_children": 0, "arrival_date": "2027-01-14",
        "nights": 4, "budget_usd_total": 2000, "pace": "relaxed",
        "interests": ["beaches", "wildlife"]}


def five_day(day3: dict) -> list[dict]:
    """Arrival, two working days, the day under test, departure."""
    return [
        {"day": 1, "base": "galle", "activities": []},
        {"day": 2, "base": "galle", "activities": [act("unawatuna_beach", 3, 0)]},
        {"day": 3, "base": "galle", "activities": [act("galle_fort", 3, 0)]},
        day3,
        {"day": 5, "base": "galle", "activities": []},
    ]


def test_empty_mid_trip_day_is_critical():
    report = run(five_day({"day": 4, "base": "galle", "activities": []}), profile=FULL)
    assert "empty_day" in codes(report)
    assert not report["passed"], "a hole in the trip must reach the reviser"


def test_empty_day_is_allowed_when_a_long_transfer_explains_it():
    report = run(five_day({
        "day": 4, "base": "jaffna",
        "transfer": {"from_base": "colombo", "to_base": "jaffna", "hours": 8.0},
        "activities": []}), profile=FULL | {"interests": []})
    assert "empty_day" not in codes(report)


def test_arrival_and_departure_days_may_be_free():
    report = run([
        {"day": 1, "base": "galle", "activities": []},
        {"day": 2, "base": "yala", "activities": [act("yala_safari", 5, 70)]},
        {"day": 3, "base": "galle", "activities": [act("unawatuna_beach", 3, 0)]},
        {"day": 4, "base": "galle", "activities": [act("hikkaduwa_reef", 3, 10)]},
        {"day": 5, "base": "galle", "activities": []},
    ], profile=FULL)
    assert "empty_day" not in codes(report)


def test_stated_interest_with_nothing_answering_it_is_critical():
    """Beaches asked for, only heritage delivered."""
    report = run([
        {"day": 1, "base": "kandy", "activities": []},
        {"day": 2, "base": "kandy", "activities": [act("temple_tooth", 3, 10)]},
        {"day": 3, "base": "kandy", "activities": [act("peradeniya_gardens", 3, 10)]},
        {"day": 4, "base": "kandy", "activities": [act("kandy_lake_market", 3, 0)]},
        {"day": 5, "base": "kandy", "activities": []},
    ], profile=FULL)
    issues = {i["code"]: i for i in report["issues"]}
    assert "interest_unserved" in issues
    assert not report["passed"]


def test_interest_matching_tolerates_plural_forms():
    """'beaches' must match the tag 'beach'."""
    report = run(five_day(
        {"day": 4, "base": "yala", "activities": [act("yala_safari", 5, 70)]}),
        profile=FULL)
    assert "interest_unserved" not in codes(report)


def test_thin_plan_warns_but_degenerate_plan_fails():
    thin = run(five_day(
        {"day": 4, "base": "galle", "activities": [act("unawatuna_beach", 0.5, 0)]}),
        profile=FULL | {"interests": ["beaches"]})
    assert "itinerary_underfilled" in codes(thin)

    ok = run(five_day(
        {"day": 4, "base": "yala", "activities": [act("yala_safari", 5, 70)]}),
        profile=FULL)
    assert "itinerary_underfilled" not in codes(ok), "a good trip must not be flagged"
    assert "itinerary_too_thin" not in codes(ok)


def test_generous_plans_are_never_flagged_as_thin():
    """Guards the floor against over-tuning — these are runs review judged good."""
    import json
    for f in ("fixtures/couple.json", "fixtures/family.json"):
        try:
            raw = json.load(open(Path(__file__).resolve().parent.parent / f))
        except FileNotFoundError:
            continue
        g = lambda k: json.loads(raw[k]) if isinstance(raw.get(k), str) else raw.get(k)
        rep = validate_itinerary(Ctx({"itinerary": g("itinerary"),
                                      "traveller_profile": g("traveller_profile")}))
        assert "itinerary_too_thin" not in codes(rep), f
        assert "interest_unserved" not in codes(rep), f


def test_padding_with_repeats_does_not_satisfy_the_floor():
    """Filling a day by rescheduling the same beach is padding, not planning."""
    report = run([
        {"day": 1, "base": "galle", "activities": []},
        {"day": 2, "base": "galle", "activities": [act("unawatuna_beach", 3, 0)]},
        {"day": 3, "base": "galle", "activities": [act("unawatuna_beach", 3, 0)]},
        {"day": 4, "base": "yala", "activities": [act("yala_safari", 5, 70)]},
        {"day": 5, "base": "galle", "activities": []},
    ], profile=FULL | {"budget_usd_total": 5000})
    assert "insufficient_variety" in codes(report)
    assert "duplicate_place" in codes(report)


def test_short_on_hours_and_places_together_is_critical():
    """Each flag alone is arguable; both at once is under-delivery."""
    report = run([
        {"day": 1, "base": "galle", "activities": []},
        {"day": 2, "base": "galle", "activities": [act("galle_fort", 2.5, 0)]},
        {"day": 3, "base": "galle", "activities": [act("unawatuna_beach", 2.5, 0)]},
        {"day": 4, "base": "galle", "activities": [act("hikkaduwa_reef", 2.5, 10)]},
        {"day": 5, "base": "yala", "activities": [act("yala_safari", 2.5, 70)]},
        {"day": 6, "base": "galle", "activities": [act("unawatuna_beach", 2.5, 0)]},
        {"day": 7, "base": "galle", "activities": []},
    ], profile=FULL | {"nights": 6, "budget_usd_total": 5000})
    assert "itinerary_underfilled" in codes(report)
    assert "insufficient_variety" in codes(report)
    assert "plan_under_delivers" in codes(report)
    assert not report["passed"], "short on hours and places must reach the reviser"


def test_a_good_trip_trips_none_of_the_floors():
    report = run([
        {"day": 1, "base": "galle", "activities": []},
        {"day": 2, "base": "galle", "activities": [act("galle_fort", 3, 0)]},
        {"day": 3, "base": "galle", "activities": [act("unawatuna_beach", 3, 0)]},
        {"day": 4, "base": "yala", "activities": [act("yala_safari", 5, 70)]},
        {"day": 5, "base": "galle", "activities": []},
    ], profile=FULL | {"budget_usd_total": 5000})
    floors = {"empty_day", "itinerary_underfilled", "itinerary_too_thin",
              "insufficient_variety", "plan_under_delivers", "interest_unserved"}
    assert not (floors & codes(report)), codes(report)
    assert report["passed"]


# --- currency and real affordability ------------------------------------------

MONEY = {"party_adults": 4, "party_children": 0, "arrival_date": "2027-04-20",
         "nights": 4, "pace": "moderate", "interests": []}


def four_night_plan() -> list[dict]:
    """A plausible multi-base trip: one transfer a day."""
    return [
        {"day": 1, "base": "kandy",
         "transfer": {"from_base": "colombo", "to_base": "kandy", "hours": 3.5},
         "activities": [act("kandy_lake_market", 2, 0)]},
        {"day": 2, "base": "nuwara_eliya",
         "transfer": {"from_base": "kandy", "to_base": "nuwara_eliya", "hours": 3.0},
         "activities": [act("nuwara_eliya_tea", 2, 8)]},
        {"day": 3, "base": "udawalawe",
         "transfer": {"from_base": "nuwara_eliya", "to_base": "udawalawe", "hours": 3.0},
         "activities": [act("udawalawe_safari", 4, 50)]},
        {"day": 4, "base": "mirissa",
         "transfer": {"from_base": "udawalawe", "to_base": "mirissa", "hours": 2.0},
         "activities": [act("weligama_surf", 2, 20)]},
        {"day": 5, "base": "colombo",
         "transfer": {"from_base": "mirissa", "to_base": "colombo", "hours": 2.5},
         "activities": []},
    ]


def test_lkr_budget_converts_and_verifies():
    report = run(four_night_plan(), profile=MONEY | {
        "budget_amount": 150000, "budget_currency": "LKR", "budget_usd_total": 500})
    assert "currency_conversion_wrong" not in codes(report)
    assert report["computed"]["budget_currency"] == "LKR"


def test_a_wrong_conversion_rate_is_caught():
    """The model claiming 150,000 LKR is 2,000 USD must not pass."""
    report = run(four_night_plan(), profile=MONEY | {
        "budget_amount": 150000, "budget_currency": "LKR", "budget_usd_total": 2000})
    assert "currency_conversion_wrong" in codes(report)
    assert not report["passed"]


def test_an_unknown_currency_is_caught():
    report = run(four_night_plan(), profile=MONEY | {
        "budget_amount": 150000, "budget_currency": "ZWL", "budget_usd_total": 500})
    assert "unknown_currency" in codes(report)


def test_a_plan_that_cannot_be_booked_fails_even_when_tickets_fit():
    """The regression: activities fit the budget, the actual trip does not."""
    report = run(four_night_plan(), profile=MONEY | {
        "budget_amount": 150000, "budget_currency": "LKR", "budget_usd_total": 500})
    assert "budget_exceeded" not in codes(report), "tickets alone do fit — that was the trap"
    assert "budget_impossible" in codes(report)
    assert not report["passed"]
    assert report["computed"]["all_in_low_usd"] > 1000


def test_the_same_plan_passes_on_a_realistic_budget():
    report = run(four_night_plan(), profile=MONEY | {
        "budget_amount": 3000, "budget_currency": "USD", "budget_usd_total": 3000})
    assert "budget_impossible" not in codes(report)
    assert "budget_tight" not in codes(report)


def test_nightly_base_changes_are_flagged_deterministically():
    report = run(four_night_plan(), profile=MONEY | {
        "budget_amount": 5000, "budget_currency": "USD", "budget_usd_total": 5000})
    assert "too_many_base_changes" in codes(report)
    assert report["computed"]["base_changes"] == 4
