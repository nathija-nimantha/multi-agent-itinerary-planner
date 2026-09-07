"""The agent graph.

    interviewer            (conversational intake, its own runner)
        |
    profile_extractor  ->  researcher  ->  planner  ->  [ validator -> reviser ]x2  ->  writer

Model tiering follows the rule that the two agents allowed to make decisions
that are expensive to get wrong — the Planner and the Validator — run on the
strongest model, and everything else runs on a worker tier.

Instruction strings must not contain literal braces: ADK treats every brace pair
as a session-state reference and raises KeyError on an unknown key.
"""
from __future__ import annotations

import json
from typing import AsyncGenerator

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.workflow import RetryConfig

from .config import RETRY_MAX_ATTEMPTS, RETRYABLE_EXCEPTIONS, build_model, model_id
from .schemas import Itinerary, TravellerProfile, ValidationReport
from .tools import kb_search, travel_time, validate_itinerary
from .trace import Tracer

DESTINATION = "Sri Lanka"

# A 503 from the provider killed a run that had already paid for eight intake
# turns plus the researcher and planner. Every LLM node retries transient
# faults with backoff and jitter so one blip cannot discard the whole run.
RETRY = RetryConfig(
    max_attempts=RETRY_MAX_ATTEMPTS,
    initial_delay=2.0,
    max_delay=30.0,
    backoff_factor=2.0,
    exceptions=RETRYABLE_EXCEPTIONS,
)


def build_interviewer(tr: Tracer) -> LlmAgent:
    return LlmAgent(
        name="interviewer",
        model=build_model("worker"),
        description="Interviews the traveller to establish what their trip needs to be.",
        instruction=f"""
You are a tour consultant taking a brief for a trip to {DESTINATION}.

Ask ONE question at a time, in plain conversational language. Never present a
numbered list of everything you still need — that reads as a form, not a
conversation. Acknowledge what the traveller just told you before you ask the
next thing.

You need, in roughly this order of importance:
  - party size and the ages of any children
  - arrival date and how many nights
  - total budget in USD for the whole party
  - what they actually want out of the trip, in their words
  - pace: relaxed, moderate or packed
  - mobility, health or dietary constraints
  - anything they have already decided they must see, or want to avoid

Infer what you reasonably can rather than asking. If someone says "my wife and
I" you have two adults; do not ask. If they name a month but not a date, take
the first of that month and say so.

When you have enough to plan a trip, stop asking, summarise the brief back in
four or five lines, and end your message with the exact token
PROFILE_COMPLETE on its own final line. Do not use that token before then.
""".strip(),
        retry_config=RETRY,
        **tr.callbacks("interviewer", model_id("worker"), "worker"),
    )


def build_profile_extractor(tr: Tracer) -> LlmAgent:
    return LlmAgent(
        name="profile_extractor",
        model=build_model("bulk"),
        description="Turns the intake conversation into a structured traveller profile.",
        instruction="""
Read the conversation or brief you have been given and produce the traveller
profile as structured output.

Record only what the traveller actually said or what follows necessarily from
it. Where something was never established, put a plain-language question into
open_questions instead of inventing a value. An invented budget or an invented
arrival date will silently corrupt every downstream check, so guessing is worse
than admitting the gap.

Budget needs three fields, not one. Put the number they said in budget_amount
and the currency they said it in into budget_currency as an ISO code — LKR,
USD, EUR, GBP, INR. Then convert to budget_usd_total using the rate in the
knowledge base. Record their figure as given; a budget silently redenominated
is a budget nobody can check. The conversion is re-computed and verified
downstream, so a wrong rate will be caught rather than quietly followed.

Defaults you may apply without asking: pace "moderate" when unstated, zero
children when the party was described without them, currency USD only when they
gave a bare number with no currency at all.
""".strip(),
        output_schema=TravellerProfile,
        output_key="traveller_profile",
        retry_config=RETRY,
        **tr.callbacks("profile_extractor", model_id("bulk"), "bulk"),
    )


def build_researcher(tr: Tracer) -> LlmAgent:
    return LlmAgent(
        name="researcher",
        model=build_model("bulk"),
        description="Retrieves grounded options from the destination knowledge base.",
        instruction="""
Traveller profile:
{traveller_profile}

Search the knowledge base for what this specific party needs. Run several
separate kb_search calls — one per interest, one for the practical constraints
(season, pace, children, mobility), one for the regions those interests point
to. Describe the need in the query; do not guess place names.

Then write a briefing for the planner containing:
  - the candidate places, each as "place_id — name — base — cost pp — hours",
    grouped by base location so the planner can see what clusters together
  - which candidates are wrong for these dates, and why
  - which are wrong for this party's children, mobility or pace, and why
  - the practical notes that constrain the plan, quoted

List only place_ids that came back from kb_search. If you cannot find something
the traveller asked for, say so explicitly — the planner must not be left to
fill the gap from memory.
""".strip(),
        tools=[kb_search],
        output_key="research_notes",
        retry_config=RETRY,
        **tr.callbacks("researcher", model_id("bulk"), "bulk"),
    )


def build_planner(tr: Tracer) -> LlmAgent:
    return LlmAgent(
        name="planner",
        model=build_model("reasoning"),
        description="Builds the day-by-day itinerary.",
        instruction="""
Traveller profile:
{traveller_profile}

Researcher briefing:
{research_notes}

Build the day-by-day itinerary as structured output.

Hard rules:
  - Every place_id must have come from the briefing or from your own kb_search
    call. If a place is not in the knowledge base it does not exist.
  - Call travel_time for every base change. Never state a transfer time from
    memory, and never use a route the tool reports as unknown.
  - Day count must equal nights + 1. Day 1 is the arrival day: assume the party
    lands tired and plan it light.
  - The party sleeps at the previous day's base, so each day's transfer must
    depart from where the previous day ended.
  - Respect the pace: relaxed means at most two ticketed activities a day,
    moderate three, packed four. Transfers count against the day too.
  - estimated_cost_usd is entries and activities for the whole party — sum
    cost_usd_pp across every activity and multiply by the number of people.
    It is not the total trip cost; note that in assumptions.
  - The traveller's budget is ALL-IN. Before committing to the plan, add up the
    real cost: activities, plus roughly 30 USD per person per night for
    guesthouses, plus 15 per person per day for meals, plus 55 per day of
    driver-guide for every day that carries a transfer. If that total exceeds
    the budget, the plan is not bookable and must be cut — fewer paid
    attractions, fewer base changes, free activities in place of ticketed ones.
    Search the knowledge base for the current rates rather than assuming these.
    A beautiful plan the traveller cannot pay for is a failed plan.
  - Minimise base changes. Backtracking across the island wastes the trip.
  - Fill the trip. Every day except arrival and departure needs something
    scheduled unless it carries a transfer of four hours or more. A day left
    blank is a day the traveller paid for and did not get.
  - Serve every stated interest at least once. If they said beaches, wildlife
    and food, all three must appear in the plan — an interest the plan ignores
    is a brief you did not answer.
  - Aim for roughly 3 hours of activity per full day at a relaxed pace, 4 at
    moderate, 5.5 at packed. Under-delivering is a failure, not caution: the
    traveller can skip something they were offered, but cannot add something
    that was never planned.
  - Fill days with new places, not repeats. Scheduling the same beach twice to
    occupy a day is padding, not planning — if a day is hard to fill, search the
    knowledge base again rather than reusing a stop.

Every activity needs a one-line "why" tying it to something the traveller
actually asked for. If you cannot write that line honestly, the activity does
not belong in the plan.

Put anything you had to assume into assumptions, and keep the budget headroom
for transport, lodging and meals that the knowledge base notes describe.
""".strip(),
        tools=[kb_search, travel_time],
        output_schema=Itinerary,
        output_key="itinerary",
        retry_config=RETRY,
        **tr.callbacks("planner", model_id("reasoning"), "reasoning"),
    )


def build_validator(tr: Tracer) -> LlmAgent:
    return LlmAgent(
        name="validator",
        model=build_model("reasoning"),
        description="Rejects itineraries that fail the deterministic or qualitative bar.",
        instruction="""
You are the reviewer. You did not write this plan and you are not here to
praise it.

Step 1 — call validate_itinerary. It checks the things that can be checked
exactly: invented places, day count, budget, route validity, route continuity,
pace, duplicates, seasonality. Treat its output as fact. Do not re-derive its
arithmetic and do not argue with it.

Step 2 — judge what it cannot. Read the profile and the itinerary and look for:
  - activities that contradict a stated mobility, age or dietary constraint
  - a "why" line that does not honestly follow from a stated interest
  - a day that is technically legal but miserable in practice — a dawn start
    after a long transfer, a hard climb with a six-year-old, a beach day in
    the wrong monsoon
  - something the traveller explicitly asked for that is simply missing
Raise these as issues with severity "warning", or "critical" if the trip would
genuinely fail for this party.

Step 3 — output the report. passed is true only when the tool reported passed
AND you found no critical problem of your own.

Do not try to end the loop yourself. A separate gate reads your report and
decides; your only job is to be right about passed.

Be specific. "Day 3 is too busy" is useless to the reviser. "Day 3 pairs a 5h
Horton Plains hike with a 3h transfer to Ella after a 05:00 start" is actionable.
""".strip(),
        tools=[validate_itinerary],
        output_schema=ValidationReport,
        output_key="validation",
        retry_config=RETRY,
        **tr.callbacks("validator", model_id("reasoning"), "reasoning"),
    )


def build_reviser(tr: Tracer) -> LlmAgent:
    return LlmAgent(
        name="reviser",
        model=build_model("worker"),
        description="Repairs the itinerary against the validation report.",
        instruction="""
Traveller profile:
{traveller_profile}

Current itinerary:
{itinerary}

Validation report:
{validation}

Fix every critical issue and as many warnings as you can without creating new
ones. Output the complete corrected itinerary as structured output — the whole
thing, not a patch or a diff.

Use kb_search to find replacements and travel_time for any route you change.
A place that is not in the knowledge base cannot be used as a substitute.

If the report says budget_impossible, trimming one activity will not fix it.
Lodging, meals and the driver scale with nights and with base changes, so the
structural levers are: fewer bases (each change adds a driver day), cheaper or
free attractions in place of ticketed ones, and dropping the most expensive
single item. Re-check the arithmetic against the same rates the report used.

Change only what the report identified. Days that were not criticised must come
through byte-identical; silently rewriting a working day loses the traveller's
earlier decisions and makes the next validation pass unreadable.
""".strip(),
        tools=[kb_search, travel_time],
        output_schema=Itinerary,
        output_key="itinerary",
        retry_config=RETRY,
        **tr.callbacks("reviser", model_id("worker"), "worker"),
    )


def build_writer(tr: Tracer) -> LlmAgent:
    return LlmAgent(
        name="writer",
        model=build_model("worker"),
        description="Writes the traveller-facing itinerary document.",
        instruction="""
Traveller profile:
{traveller_profile}

Final itinerary:
{itinerary}

Validation report:
{validation?}

Write the itinerary the traveller will actually read, in markdown.

  - Open with two or three sentences on the shape of the trip and why it suits
    this party specifically.
  - Then a day-by-day section. Each day: a heading with the date and base, the
    transfer if there is one, then the activities with times, durations and
    per-person cost. Keep the "why" — it is the reason they will trust the plan.
  - Close with a cost table: activity and entry costs from the itinerary, then
    the transport, lodging and meal ranges from the knowledge base notes as
    clearly-labelled estimates, then an indicative total range.
  - Then "Before you book": the assumptions, any unresolved open_questions from
    the profile, and every warning still open in the validation report.

Do not add places, times or prices that are not in the itinerary. If the
validation report still lists warnings, surface them plainly under "Before you
book" — a warning the traveller never sees is a warning that did nothing.
""".strip(),
        output_key="final_itinerary",
        retry_config=RETRY,
        **tr.callbacks("writer", model_id("worker"), "worker"),
    )


class PassGate(BaseAgent):
    """Ends the QA loop when the validator's report is clean.

    This is deliberately not the Validator's own decision. An LLM asked to both
    emit a structured report and call exit_loop in the same turn will sometimes
    escalate before its report is committed to state, and the loop then exits
    having recorded nothing. Reading the committed report and escalating in code
    is exact, free, and cannot be talked out of it.
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        report = ctx.session.state.get("validation")
        if isinstance(report, str):
            try:
                report = json.loads(report)
            except json.JSONDecodeError:
                report = None
        passed = False
        if isinstance(report, dict):
            critical = [i for i in report.get("issues", [])
                        if i.get("severity") == "critical"]
            passed = bool(report.get("passed")) and not critical
        yield Event(author=self.name, actions=EventActions(escalate=passed))


def build_pipeline(tr: Tracer) -> SequentialAgent:
    return SequentialAgent(
        name="tour_pipeline",
        description="Traveller brief to validated, written itinerary.",
        sub_agents=[
            build_profile_extractor(tr),
            build_researcher(tr),
            build_planner(tr),
            LoopAgent(
                name="qa_loop",
                description="Validate, then repair, until the plan passes or the budget runs out.",
                max_iterations=2,
                sub_agents=[build_validator(tr),
                            PassGate(name="pass_gate",
                                     description="Exits the loop on a clean report."),
                            build_reviser(tr)],
            ),
            build_writer(tr),
        ],
    )
