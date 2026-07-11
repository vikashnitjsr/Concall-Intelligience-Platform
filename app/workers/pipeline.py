"""Pipeline orchestration.

In this scaffold the stages run in-process, sequentially, driven by a function
call. In production each `run_*` step becomes an independent queue consumer
(emit an event at the end of each stage). The orchestration is intentionally
idempotent so a re-run of any transcript is safe.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Transcript, TranscriptStatus
from app.services.analysis import analyze_transcript
from app.services.extraction import extract_text
from app.services.guidance import reconcile_guidance
from app.services.scoring import score_company


def process_transcript(session: Session, transcript: Transcript) -> dict:
    """Run extraction -> analysis -> guidance reconciliation -> scoring."""
    report: dict = {"transcript_id": transcript.id, "period": transcript.period_key}

    # 1. Extract (skip if we already have text and it's not a fresh upload)
    if transcript.status == TranscriptStatus.uploaded or not transcript.raw_text:
        with open(transcript.source_blob, "rb") as fh:
            data = fh.read()
        transcript.raw_text = extract_text(data, filename=transcript.source_blob)
        transcript.status = TranscriptStatus.extracted
        session.commit()
    report["chars_extracted"] = len(transcript.raw_text or "")

    # 2. Analyze (LLM/stub -> structured facts)
    analysis = analyze_transcript(session, transcript)
    report["metrics"] = len(analysis.metrics)
    report["guidance_issued"] = len(analysis.guidance)
    report["red_flags"] = len(analysis.red_flags)

    # 3. Reconcile prior guidance against this quarter's actuals
    report["guidance_resolved"] = reconcile_guidance(session, transcript)
    transcript.status = TranscriptStatus.reconciled
    session.commit()

    # 4. Rescore the company as of this quarter
    score = score_company(session, transcript.company_id, transcript.period_ordinal)
    transcript.status = TranscriptStatus.scored
    session.commit()
    report["total_0_100"] = score.total_0_100
    report["decision_band"] = score.decision_band
    report["guidance_reliability"] = score.guidance_reliability_score

    return report
