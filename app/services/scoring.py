"""Scoring stage: aggregate section scores into a /100 total + decision band,
compute the extra ranking axes (growth, aggression, consistency, guidance
reliability), and expose leaderboard queries.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CompanyScore,
    Guidance,
    GuidanceStatus,
    SectionScore,
    Transcript,
)
from app.schemas import decision_band


def _guidance_reliability(session: Session, company_id: int) -> float:
    """MET / (MET + MISSED + PARTIAL) over all resolved guidance for the company."""
    counts = dict(
        session.execute(
            select(Guidance.status, func.count())
            .where(Guidance.company_id == company_id)
            .group_by(Guidance.status)
        ).all()
    )
    met = counts.get(GuidanceStatus.met, 0)
    missed = counts.get(GuidanceStatus.missed, 0)
    partial = counts.get(GuidanceStatus.partial, 0)
    denom = met + missed + partial
    return (met / denom) if denom else 0.0


def _aggression(session: Session, company_id: int) -> float:
    """Proxy: number of forward guidance items issued (normalized)."""
    n = session.scalar(
        select(func.count()).select_from(Guidance).where(Guidance.company_id == company_id)
    ) or 0
    return min(n / 12.0, 1.0)


def score_company(session: Session, company_id: int, as_of_period_ordinal: int) -> CompanyScore:
    """Recompute and upsert the CompanyScore for a company at a given quarter."""
    section_total = session.scalar(
        select(func.coalesce(func.sum(SectionScore.score_0_10), 0.0)).where(
            SectionScore.company_id == company_id,
            SectionScore.as_of_period_ordinal == as_of_period_ordinal,
        )
    ) or 0.0
    total_100 = round(float(section_total) * (100.0 / 100.0), 1)  # 10 sections * 10 = 100

    # growth = revenue-growth section (2) score scaled; consistency = inverse variance proxy
    growth = session.scalar(
        select(SectionScore.score_0_10).where(
            SectionScore.company_id == company_id,
            SectionScore.as_of_period_ordinal == as_of_period_ordinal,
            SectionScore.section_no == 2,
        )
    ) or 0.0
    reliability = _guidance_reliability(session, company_id)
    aggression = _aggression(session, company_id)
    consistency = round((reliability * 0.7 + (float(growth) / 10.0) * 0.3), 3)
    composite = round(total_100 * 0.6 + reliability * 100 * 0.25 + aggression * 100 * 0.15, 1)

    existing = session.scalar(
        select(CompanyScore).where(
            CompanyScore.company_id == company_id,
            CompanyScore.as_of_period_ordinal == as_of_period_ordinal,
        )
    )
    if existing is None:
        existing = CompanyScore(company_id=company_id, as_of_period_ordinal=as_of_period_ordinal)
        session.add(existing)

    existing.total_0_100 = total_100
    existing.decision_band = decision_band(total_100)
    existing.growth_score = round(float(growth), 2)
    existing.aggression_score = round(aggression, 3)
    existing.consistency_score = consistency
    existing.guidance_reliability_score = round(reliability, 3)
    existing.composite = composite
    session.commit()
    return existing


def latest_period(session: Session) -> int | None:
    return session.scalar(select(func.max(CompanyScore.as_of_period_ordinal)))
