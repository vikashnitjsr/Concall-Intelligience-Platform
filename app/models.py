"""SQLAlchemy ORM models.

Design notes
------------
* Every extracted fact stores a verbatim `raw_quote` + a link back to the
  transcript for auditability (anti-hallucination).
* `transcript` is unique on (company_id, fiscal_year, quarter) so re-uploads
  are idempotent; `content_hash` guards against duplicate bytes.
* The two guidance tables implement the Promise -> Outcome chain.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TranscriptStatus(str, enum.Enum):
    uploaded = "uploaded"
    extracted = "extracted"
    analyzed = "analyzed"
    reconciled = "reconciled"
    scored = "scored"
    failed = "failed"


class GuidanceStatus(str, enum.Enum):
    open = "open"          # not yet due / unresolved
    met = "MET"
    missed = "MISSED"
    partial = "PARTIAL"
    in_progress = "IN_PROGRESS"
    dropped = "DROPPED"


class Company(Base):
    __tablename__ = "company"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    transcripts: Mapped[list["Transcript"]] = relationship(back_populates="company")


class Transcript(Base):
    __tablename__ = "transcript"
    __table_args__ = (
        UniqueConstraint("company_id", "fiscal_year", "quarter", name="uq_company_quarter"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer)          # e.g. 2026 for FY26
    quarter: Mapped[int] = mapped_column(Integer)              # 1..4
    call_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_blob: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TranscriptStatus] = mapped_column(
        Enum(TranscriptStatus), default=TranscriptStatus.uploaded
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    company: Mapped[Company] = relationship(back_populates="transcripts")
    metrics: Mapped[list["Metric"]] = relationship(back_populates="transcript")
    red_flags: Mapped[list["RedFlag"]] = relationship(back_populates="transcript")

    @property
    def period_key(self) -> str:
        return f"FY{self.fiscal_year % 100:02d}Q{self.quarter}"

    @property
    def period_ordinal(self) -> int:
        """Monotonic integer for ordering/comparison of quarters."""
        return self.fiscal_year * 4 + (self.quarter - 1)


class Metric(Base):
    __tablename__ = "metric"

    id: Mapped[int] = mapped_column(primary_key=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcript.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)   # revenue, ebitda_margin, pat...
    value_numeric: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    yoy_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    qoq_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_quote: Mapped[str | None] = mapped_column(Text, nullable=True)

    transcript: Mapped[Transcript] = relationship(back_populates="metrics")


class Guidance(Base):
    """A forward-looking promise made by management in a specific call."""

    __tablename__ = "guidance"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), index=True)
    source_transcript_id: Mapped[int] = mapped_column(ForeignKey("transcript.id"))
    category: Mapped[str] = mapped_column(String(64))            # revenue/margin/capex/volume...
    metric_name: Mapped[str] = mapped_column(String(128))
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)  # up/down/flat
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_period_ordinal: Mapped[int] = mapped_column(Integer)  # when it should be judged
    raw_quote: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    created_period_ordinal: Mapped[int] = mapped_column(Integer)
    status: Mapped[GuidanceStatus] = mapped_column(Enum(GuidanceStatus), default=GuidanceStatus.open)

    outcomes: Mapped[list["GuidanceOutcome"]] = relationship(back_populates="guidance")


class GuidanceOutcome(Base):
    """Resolution of a Guidance against a later quarter's actuals (the chain link)."""

    __tablename__ = "guidance_outcome"

    id: Mapped[int] = mapped_column(primary_key=True)
    guidance_id: Mapped[int] = mapped_column(ForeignKey("guidance.id"), index=True)
    resolved_transcript_id: Mapped[int] = mapped_column(ForeignKey("transcript.id"))
    resolved_period_ordinal: Mapped[int] = mapped_column(Integer)
    actual_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[GuidanceStatus] = mapped_column(Enum(GuidanceStatus))
    variance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_quote: Mapped[str | None] = mapped_column(Text, nullable=True)

    guidance: Mapped[Guidance] = relationship(back_populates="outcomes")


class RedFlag(Base):
    __tablename__ = "red_flag"

    id: Mapped[int] = mapped_column(primary_key=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcript.id"), index=True)
    type: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))            # low/medium/high
    description: Mapped[str] = mapped_column(Text)
    raw_quote: Mapped[str | None] = mapped_column(Text, nullable=True)

    transcript: Mapped[Transcript] = relationship(back_populates="red_flags")


class SectionScore(Base):
    """One of the 10 template sections, scored 0-10 for a company as of a quarter."""

    __tablename__ = "section_score"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), index=True)
    as_of_period_ordinal: Mapped[int] = mapped_column(Integer, index=True)
    section_no: Mapped[int] = mapped_column(Integer)            # 1..10
    section_name: Mapped[str] = mapped_column(String(64))
    score_0_10: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)


class CompanyScore(Base):
    __tablename__ = "company_score"
    __table_args__ = (
        UniqueConstraint("company_id", "as_of_period_ordinal", name="uq_score_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), index=True)
    as_of_period_ordinal: Mapped[int] = mapped_column(Integer, index=True)
    total_0_100: Mapped[float] = mapped_column(Float)
    decision_band: Mapped[str] = mapped_column(String(32))
    growth_score: Mapped[float] = mapped_column(Float, default=0.0)
    aggression_score: Mapped[float] = mapped_column(Float, default=0.0)
    consistency_score: Mapped[float] = mapped_column(Float, default=0.0)
    guidance_reliability_score: Mapped[float] = mapped_column(Float, default=0.0)
    composite: Mapped[float] = mapped_column(Float, default=0.0)


class ResearchSheet(Base):
    """Auto-filled One-Page Company Research Sheet from the template."""

    __tablename__ = "research_sheet"
    __table_args__ = (
        UniqueConstraint("company_id", "as_of_period_ordinal", name="uq_sheet_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), index=True)
    as_of_period_ordinal: Mapped[int] = mapped_column(Integer, index=True)
    market_cap: Mapped[str | None] = mapped_column(String(64), nullable=True)
    business_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    revenue_cagr_5y: Mapped[float | None] = mapped_column(Float, nullable=True)
    pat_eps_cagr_5y: Mapped[float | None] = mapped_column(Float, nullable=True)
    roe: Mapped[float | None] = mapped_column(Float, nullable=True)
    roce: Mapped[float | None] = mapped_column(Float, nullable=True)
    debt_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    interest_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    moat_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    mgmt_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    valuation_view: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_red_flags: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)  # Buy/Watchlist/Avoid


class FundamentalRanking(Base):
    """Fundamentals-based multi-factor ranking of companies.

    Blends the concall business-quality composite with market/financial factors
    (Stock Price CAGR, Sales CAGR, Profit CAGR, ROE). Each factor is nullable and
    carries a `*_flag` describing its provenance/quality (M=mgmt-disclosed,
    C=computed, G=forward-guidance, P=ROCE-proxy, MD=dated, NA=missing) so gaps
    are transparent rather than fabricated.
    """

    __tablename__ = "fundamental_ranking"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), unique=True, index=True)
    rank: Mapped[int] = mapped_column(Integer, index=True)
    composite_score: Mapped[float] = mapped_column(Float)
    completeness: Mapped[str | None] = mapped_column(String(8), nullable=True)  # e.g. "4/4"

    business_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision_band: Mapped[str | None] = mapped_column(String(32), nullable=True)

    stock_cagr_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    stock_cagr_years: Mapped[float | None] = mapped_column(Float, nullable=True)

    sales_cagr_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sales_cagr_flag: Mapped[str | None] = mapped_column(String(4), nullable=True)
    sales_cagr_note: Mapped[str | None] = mapped_column(String(256), nullable=True)

    profit_cagr_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_cagr_flag: Mapped[str | None] = mapped_column(String(4), nullable=True)
    profit_cagr_note: Mapped[str | None] = mapped_column(String(256), nullable=True)

    roe_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    roe_flag: Mapped[str | None] = mapped_column(String(4), nullable=True)
    roe_note: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Section 9 (Valuation): PEG = trailing PE / growth% ; PEG<1 undervalued
    trailing_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    valuation_growth_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    valuation_growth_source: Mapped[str | None] = mapped_column(String(4), nullable=True)
    peg_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    valuation_verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
