"""Analysis stage: run the LLM (or stub) over the extracted text and persist the
structured facts (metrics, guidance, red flags, section scores).
"""
from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.llm.client import get_llm
from app.models import (
    Guidance,
    GuidanceStatus,
    Metric,
    RedFlag,
    SectionScore,
    Transcript,
    TranscriptStatus,
)
from app.schemas import TranscriptAnalysis


def _period_ordinal(fy: int, q: int) -> int:
    return fy * 4 + (q - 1)


def analyze_transcript(session: Session, transcript: Transcript) -> TranscriptAnalysis:
    company = transcript.company
    llm = get_llm()
    result = llm.analyze(
        company_name=company.name,
        ticker=company.ticker,
        fiscal_year=transcript.fiscal_year,
        quarter=transcript.quarter,
        text=transcript.raw_text or "",
    )
    return persist_analysis(session, transcript, result)


def persist_analysis(
    session: Session, transcript: Transcript, result: TranscriptAnalysis
) -> TranscriptAnalysis:
    """Write a (LLM- or agent-produced) analysis to the DB. Idempotent per transcript."""
    company = transcript.company

    # Idempotent: clear any previous facts for this transcript before re-inserting.
    session.execute(delete(Metric).where(Metric.transcript_id == transcript.id))
    session.execute(delete(RedFlag).where(RedFlag.transcript_id == transcript.id))
    session.execute(delete(Guidance).where(Guidance.source_transcript_id == transcript.id))

    for m in result.metrics:
        session.add(Metric(transcript_id=transcript.id, name=m.name,
                           value_numeric=m.value_numeric, unit=m.unit,
                           yoy_pct=m.yoy_pct, qoq_pct=m.qoq_pct, raw_quote=m.raw_quote))

    for rf in result.red_flags:
        session.add(RedFlag(transcript_id=transcript.id, type=rf.type, severity=rf.severity,
                           description=rf.description, raw_quote=rf.raw_quote))

    created_ord = _period_ordinal(transcript.fiscal_year, transcript.quarter)
    for g in result.guidance:
        session.add(Guidance(
            company_id=company.id,
            source_transcript_id=transcript.id,
            category=g.category,
            metric_name=g.metric_name,
            direction=g.direction,
            target_value=g.target_value,
            target_unit=g.target_unit,
            target_period_ordinal=_period_ordinal(g.target_fiscal_year, g.target_quarter),
            raw_quote=g.raw_quote,
            confidence=g.confidence,
            created_period_ordinal=created_ord,
            status=GuidanceStatus.open,
        ))

    # Section scores are per-company as-of the transcript period.
    session.execute(
        delete(SectionScore).where(
            SectionScore.company_id == company.id,
            SectionScore.as_of_period_ordinal == created_ord,
        )
    )
    for s in result.section_scores:
        session.add(SectionScore(company_id=company.id, as_of_period_ordinal=created_ord,
                                section_no=s.section_no, section_name=s.section_name,
                                score_0_10=s.score_0_10, rationale=s.rationale))

    transcript.status = TranscriptStatus.analyzed
    session.commit()
    return result
