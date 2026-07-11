"""Pydantic schemas: API I/O + the LLM structured-extraction contract.

The `TranscriptAnalysis` model is the JSON schema we ask the LLM to fill. It maps
directly to the Business Analysis Template (10 sections + metrics + guidance + red
flags). Keeping it as a Pydantic model gives us validation and a ready-made JSON
schema for function-calling.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# --- Template constant: the 10 scoring sections ---------------------------------
TEMPLATE_SECTIONS: list[tuple[int, str]] = [
    (1, "Business simplicity"),
    (2, "Revenue growth"),
    (3, "Profit growth"),
    (4, "Return on capital"),
    (5, "Debt safety"),
    (6, "Moat"),
    (7, "Management quality"),
    (8, "Industry opportunity"),
    (9, "Valuation"),
    (10, "Red flags & governance"),
]


def decision_band(total_0_100: float) -> str:
    if total_0_100 >= 85:
        return "Exceptional"
    if total_0_100 >= 75:
        return "High quality"
    if total_0_100 >= 65:
        return "Good"
    if total_0_100 >= 50:
        return "Average"
    return "Avoid"


# --- LLM extraction contract ----------------------------------------------------
class MetricOut(BaseModel):
    name: str = Field(description="canonical metric key, e.g. revenue, ebitda_margin, pat, net_debt")
    value_numeric: float | None = None
    unit: str | None = None
    yoy_pct: float | None = None
    qoq_pct: float | None = None
    raw_quote: str | None = None


class GuidanceOut(BaseModel):
    category: str = Field(description="revenue|margin|capex|volume|debt|other")
    metric_name: str
    direction: str | None = Field(default=None, description="up|down|flat")
    target_value: float | None = None
    target_unit: str | None = None
    target_fiscal_year: int
    target_quarter: int
    raw_quote: str
    confidence: float = 0.5


class RedFlagOut(BaseModel):
    type: str
    severity: str = Field(description="low|medium|high")
    description: str
    raw_quote: str | None = None


class SectionScoreOut(BaseModel):
    section_no: int
    section_name: str
    score_0_10: float
    rationale: str | None = None


class TranscriptAnalysis(BaseModel):
    """Full structured output the analysis stage produces for one transcript."""

    business_summary: str | None = None
    sentiment: float = Field(default=0.0, description="-1 (very negative) .. +1 (very positive)")
    aggression: float = Field(default=0.0, description="0..1, how aggressive the guidance is")
    metrics: list[MetricOut] = Field(default_factory=list)
    guidance: list[GuidanceOut] = Field(default_factory=list)
    red_flags: list[RedFlagOut] = Field(default_factory=list)
    section_scores: list[SectionScoreOut] = Field(default_factory=list)


# --- API request/response models ------------------------------------------------
class CompanyIn(BaseModel):
    ticker: str
    name: str
    sector: str | None = None


class CompanyOut(BaseModel):
    id: int
    ticker: str
    name: str
    sector: str | None = None

    class Config:
        from_attributes = True


class TranscriptOut(BaseModel):
    id: int
    company_id: int
    fiscal_year: int
    quarter: int
    period_key: str
    status: str

    class Config:
        from_attributes = True


class GuidanceChainLink(BaseModel):
    resolved_period: str
    status: str
    actual_value: float | None
    variance_pct: float | None
    evidence_quote: str | None


class GuidanceChain(BaseModel):
    guidance_id: int
    created_period: str
    target_period: str
    category: str
    metric_name: str
    target_value: float | None
    target_unit: str | None
    raw_quote: str
    current_status: str
    chain: list[GuidanceChainLink]


class LeaderboardEntry(BaseModel):
    ticker: str
    name: str
    value: float
    decision_band: str | None = None


class Leaderboards(BaseModel):
    as_of_period: str
    high_growth: list[LeaderboardEntry]
    aggressive_management: list[LeaderboardEntry]
    consistent_compounders: list[LeaderboardEntry]
    top_composite: list[LeaderboardEntry]
