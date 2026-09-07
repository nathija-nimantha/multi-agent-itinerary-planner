"""Structured contracts every agent writes against.

These exist so the pipeline fails loudly on malformed agent output instead of
carrying a half-formed plan downstream.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Pace = Literal["relaxed", "moderate", "packed"]
Severity = Literal["critical", "warning"]


class TravellerProfile(BaseModel):
    party_adults: int = Field(..., description="Number of adults")
    party_children: int = Field(0, description="Number of children")
    child_ages: list[int] = Field(default_factory=list)
    arrival_date: str = Field(..., description="ISO date, YYYY-MM-DD")
    nights: int = Field(..., description="Nights in country")
    budget_amount: float = Field(
        ..., description="The budget figure the traveller gave, in their own currency"
    )
    budget_currency: str = Field(
        "USD",
        description="ISO code of the currency the traveller used — LKR, USD, EUR, GBP, INR. "
        "Record what they said; never silently convert.",
    )
    budget_usd_total: float = Field(
        ...,
        description="The same budget in USD. Convert using the rate in the knowledge base. "
        "This is re-computed and checked against budget_amount, so a wrong rate is caught.",
    )
    interests: list[str] = Field(default_factory=list)
    pace: Pace = "moderate"
    mobility_notes: str = ""
    dietary_notes: str = ""
    must_see: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(
        default_factory=list, description="Gaps the intake agent could not resolve"
    )


class Activity(BaseModel):
    place_id: str = Field(..., description="Must match a place id in the knowledge base")
    name: str
    start_time: str = Field(..., description="HH:MM")
    duration_hours: float
    cost_usd_pp: float
    why: str = Field(..., description="One line tying this to a stated traveller interest")


class Transfer(BaseModel):
    from_base: str
    to_base: str
    hours: float
    mode: str = "car"


class Day(BaseModel):
    day: int
    date: str
    base: str = Field(..., description="Where the party sleeps that night")
    transfer: Optional[Transfer] = None
    activities: list[Activity] = Field(default_factory=list)


class Itinerary(BaseModel):
    title: str
    summary: str
    days: list[Day]
    estimated_cost_usd: float = Field(..., description="Entries and activities for the whole party")
    assumptions: list[str] = Field(default_factory=list)


class Issue(BaseModel):
    severity: Severity
    code: str
    day: Optional[int] = None
    message: str


class ValidationReport(BaseModel):
    passed: bool
    issues: list[Issue] = Field(default_factory=list)
    notes: str = ""
