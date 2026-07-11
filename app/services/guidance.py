"""Guidance reconciler: the differentiating feature.

When a new quarter is analyzed, every *open* guidance for the company whose
target period has now passed (or equals the new quarter) is matched against the
new quarter's actual metrics and commentary, producing a GuidanceOutcome and
updating the guidance status. This builds the Promise -> Outcome chain.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Guidance,
    GuidanceOutcome,
    GuidanceStatus,
    Metric,
    Transcript,
)


def _find_actual(session: Session, transcript: Transcript, metric_name: str) -> Metric | None:
    """Best-effort match of a guided metric to an actual metric in the new quarter."""
    stmt = select(Metric).where(Metric.transcript_id == transcript.id)
    actuals = session.scalars(stmt).all()
    name = metric_name.lower()
    # exact, then substring match
    for m in actuals:
        if m.name.lower() == name:
            return m
    for m in actuals:
        if name in m.name.lower() or m.name.lower() in name:
            return m
    return None


def _classify(target: float | None, actual: float | None, direction: str | None) -> tuple[str, float | None]:
    """Return (status, variance_pct)."""
    if target is None or actual is None:
        return GuidanceStatus.in_progress.value, None
    variance = (actual - target) / target * 100 if target else None
    # For "up" guidance meeting/beating target is MET; within 10% short is PARTIAL.
    if variance is None:
        return GuidanceStatus.in_progress.value, None
    if variance >= -2:
        return GuidanceStatus.met.value, round(variance, 1)
    if variance >= -10:
        return GuidanceStatus.partial.value, round(variance, 1)
    return GuidanceStatus.missed.value, round(variance, 1)


def reconcile_guidance(session: Session, transcript: Transcript) -> int:
    """Resolve due guidance for this company using the just-analyzed quarter.

    Returns the number of guidance items resolved/updated.
    """
    company_id = transcript.company_id
    new_ord = transcript.period_ordinal

    open_guidance = session.scalars(
        select(Guidance).where(
            Guidance.company_id == company_id,
            Guidance.status == GuidanceStatus.open,
            Guidance.source_transcript_id != transcript.id,  # don't resolve promises made in the same call
            Guidance.target_period_ordinal <= new_ord,
        )
    ).all()

    resolved = 0
    for g in open_guidance:
        actual_metric = _find_actual(session, transcript, g.metric_name)
        actual_value = actual_metric.value_numeric if actual_metric else None
        status, variance = _classify(g.target_value, actual_value, g.direction)

        session.add(GuidanceOutcome(
            guidance_id=g.id,
            resolved_transcript_id=transcript.id,
            resolved_period_ordinal=new_ord,
            actual_value=actual_value,
            status=GuidanceStatus(status),
            variance_pct=variance,
            evidence_quote=(actual_metric.raw_quote if actual_metric else None),
        ))

        # Only close the guidance once its target period is reached (not merely passed
        # by an interim quarter); interim quarters stay IN_PROGRESS.
        if g.target_period_ordinal <= new_ord and status != GuidanceStatus.in_progress.value:
            g.status = GuidanceStatus(status)
        else:
            g.status = GuidanceStatus.in_progress
        resolved += 1

    session.commit()
    return resolved
