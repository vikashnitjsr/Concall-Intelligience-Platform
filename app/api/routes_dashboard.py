"""Dashboard endpoints: per-company insights, guidance chains, leaderboards."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import (
    Company,
    CompanyScore,
    FundamentalRanking,
    Guidance,
    RedFlag,
    ResearchSheet,
    SectionScore,
    Transcript,
)
from app.schemas import (
    GuidanceChain,
    GuidanceChainLink,
    LeaderboardEntry,
    Leaderboards,
)

router = APIRouter()


def _period_key(ordinal: int) -> str:
    fy, q = divmod(ordinal, 4)
    return f"FY{fy % 100:02d}Q{q + 1}"


@router.get("/companies/{company_id}/insights")
def company_insights(company_id: int, session: Session = Depends(get_session)):
    company = session.get(Company, company_id)
    if company is None:
        raise HTTPException(404, "company not found")

    latest_score = session.scalar(
        select(CompanyScore).where(CompanyScore.company_id == company_id)
        .order_by(CompanyScore.as_of_period_ordinal.desc())
    )
    sections = []
    if latest_score:
        sections = session.scalars(
            select(SectionScore).where(
                SectionScore.company_id == company_id,
                SectionScore.as_of_period_ordinal == latest_score.as_of_period_ordinal,
            ).order_by(SectionScore.section_no)
        ).all()

    red_flags = session.scalars(
        select(RedFlag).join(Transcript).where(Transcript.company_id == company_id)
    ).all()

    # Future guidance = forward-looking statements from the most recent call.
    latest_transcript = session.scalar(
        select(Transcript).where(Transcript.company_id == company_id)
        .order_by(Transcript.fiscal_year.desc(), Transcript.quarter.desc())
    )
    future_guidance = []
    if latest_transcript is not None:
        fg = session.scalars(
            select(Guidance).where(Guidance.source_transcript_id == latest_transcript.id)
        ).all()
        future_guidance = [
            {
                "category": g.category,
                "metric_name": g.metric_name,
                "direction": g.direction,
                "target_value": g.target_value,
                "target_unit": g.target_unit,
                "target_period": _period_key(g.target_period_ordinal),
                "quote": g.raw_quote,
            }
            for g in fg
        ]

    # Section 9 (Valuation): PEG from the fundamental ranking table.
    fr = session.scalar(
        select(FundamentalRanking).where(FundamentalRanking.company_id == company_id)
    )
    valuation = None
    if fr is not None:
        valuation = {
            "trailing_pe": fr.trailing_pe,
            "growth_pct": fr.valuation_growth_pct,
            "growth_source": fr.valuation_growth_source,
            "peg": fr.peg_ratio,
            "verdict": fr.valuation_verdict,
            "rank": fr.rank,
            "blended_score": fr.composite_score,
        }

    return {
        "company": {"id": company.id, "ticker": company.ticker, "name": company.name},
        "as_of": _period_key(latest_score.as_of_period_ordinal) if latest_score else None,
        "score": {
            "total_0_100": latest_score.total_0_100 if latest_score else None,
            "decision_band": latest_score.decision_band if latest_score else None,
            "guidance_reliability": latest_score.guidance_reliability_score if latest_score else None,
            "growth": latest_score.growth_score if latest_score else None,
            "aggression": latest_score.aggression_score if latest_score else None,
            "consistency": latest_score.consistency_score if latest_score else None,
        },
        "valuation": valuation,
        "sections": [
            {"no": s.section_no, "name": s.section_name, "score": s.score_0_10, "rationale": s.rationale}
            for s in sections
        ],
        "red_flags": [
            {"type": rf.type, "severity": rf.severity, "description": rf.description, "quote": rf.raw_quote}
            for rf in red_flags
        ],
        "future_guidance": future_guidance,
    }


@router.get("/companies/{company_id}/guidance-chains", response_model=list[GuidanceChain])
def guidance_chains(company_id: int, session: Session = Depends(get_session)):
    """Return every promise made by management and how it resolved over time."""
    guidances = session.scalars(
        select(Guidance).where(Guidance.company_id == company_id)
        .order_by(Guidance.created_period_ordinal)
    ).all()

    chains: list[GuidanceChain] = []
    for g in guidances:
        links = [
            GuidanceChainLink(
                resolved_period=_period_key(o.resolved_period_ordinal),
                status=o.status.value if hasattr(o.status, "value") else str(o.status),
                actual_value=o.actual_value,
                variance_pct=o.variance_pct,
                evidence_quote=o.evidence_quote,
            )
            for o in sorted(g.outcomes, key=lambda x: x.resolved_period_ordinal)
        ]
        chains.append(GuidanceChain(
            guidance_id=g.id,
            created_period=_period_key(g.created_period_ordinal),
            target_period=_period_key(g.target_period_ordinal),
            category=g.category,
            metric_name=g.metric_name,
            target_value=g.target_value,
            target_unit=g.target_unit,
            raw_quote=g.raw_quote,
            current_status=g.status.value if hasattr(g.status, "value") else str(g.status),
            chain=links,
        ))
    return chains


@router.get("/leaderboards", response_model=Leaderboards)
def leaderboards(
    top_n: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session),
):
    """Top-N stocks by high growth / aggressive mgmt / consistent compounders / composite."""
    latest = session.scalar(select(CompanyScore.as_of_period_ordinal)
                            .order_by(CompanyScore.as_of_period_ordinal.desc()))
    if latest is None:
        raise HTTPException(404, "no scored companies yet")

    rows = session.execute(
        select(CompanyScore, Company).join(Company, Company.id == CompanyScore.company_id)
        .where(CompanyScore.as_of_period_ordinal == latest)
    ).all()

    def board(key) -> list[LeaderboardEntry]:
        ordered = sorted(rows, key=lambda r: key(r[0]), reverse=True)[:top_n]
        return [
            LeaderboardEntry(ticker=c.ticker, name=c.name, value=round(key(s), 2),
                             decision_band=s.decision_band)
            for s, c in ordered
        ]

    return Leaderboards(
        as_of_period=_period_key(latest),
        high_growth=board(lambda s: s.growth_score),
        aggressive_management=board(lambda s: s.aggression_score),
        consistent_compounders=board(lambda s: s.consistency_score),
        top_composite=board(lambda s: s.composite),
    )


@router.get("/fundamental-ranking")
def fundamental_ranking(session: Session = Depends(get_session)):
    """Fundamentals-based Rank 1..N blending business quality with
    Stock Price CAGR, Sales CAGR, Profit CAGR and ROE (gaps flagged, not faked)."""
    rows = session.execute(
        select(FundamentalRanking, Company)
        .join(Company, Company.id == FundamentalRanking.company_id)
        .order_by(FundamentalRanking.rank)
    ).all()
    return {
        "methodology": (
            "composite = 0.35*business_quality + 0.30*stock_cagr(capped 100%) "
            "+ 0.20*sales_cagr + 0.15*roe, each min-max normalised over companies "
            "that have the value; weights renormalised to available factors. "
            "Valuation (template section 9): PEG = trailing_PE / growth%; PEG<1 Undervalued else Overvalued. "
            "growth source: C=computed Profit CAGR, S=sustainable Sales CAGR, Y=1yr YoY earnings growth (volatile). "
            "flags: M=mgmt-disclosed C=computed G=forward-guidance P=ROCE-proxy MD=dated NA=missing"
        ),
        "ranking": [
            {
                "rank": r.rank,
                "ticker": c.ticker,
                "name": c.name,
                "composite_score": r.composite_score,
                "completeness": r.completeness,
                "business_quality": r.business_quality,
                "decision_band": r.decision_band,
                "stock_price_cagr_pct": r.stock_cagr_pct,
                "stock_cagr_years": r.stock_cagr_years,
                "sales_cagr_pct": r.sales_cagr_pct,
                "sales_cagr_flag": r.sales_cagr_flag,
                "sales_cagr_note": r.sales_cagr_note,
                "profit_cagr_pct": r.profit_cagr_pct,
                "profit_cagr_flag": r.profit_cagr_flag,
                "profit_cagr_note": r.profit_cagr_note,
                "roe_pct": r.roe_pct,
                "roe_flag": r.roe_flag,
                "roe_note": r.roe_note,
                "trailing_pe": r.trailing_pe,
                "valuation_growth_pct": r.valuation_growth_pct,
                "valuation_growth_source": r.valuation_growth_source,
                "peg_ratio": r.peg_ratio,
                "valuation_verdict": r.valuation_verdict,
            }
            for r, c in rows
        ],
    }
