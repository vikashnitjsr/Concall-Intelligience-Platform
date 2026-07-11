"""Ingestion stage: accept an uploaded transcript, persist raw bytes + a
Transcript row. Idempotent on (company, fiscal_year, quarter) and content hash.
"""
from __future__ import annotations

import hashlib
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Company, Transcript, TranscriptStatus


def _store_blob(data: bytes, key: str) -> str:
    os.makedirs(settings.blob_dir, exist_ok=True)
    path = os.path.join(settings.blob_dir, key)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def ingest_transcript(
    session: Session,
    *,
    company_id: int,
    fiscal_year: int,
    quarter: int,
    data: bytes,
    filename: str = "transcript.pdf",
) -> tuple[Transcript, bool]:
    """Returns (transcript, created). If the same period already exists, returns it.

    Re-upload with identical bytes is a no-op; different bytes updates the blob and
    resets status so the pipeline reprocesses.
    """
    company = session.get(Company, company_id)
    if company is None:
        raise ValueError(f"Unknown company_id={company_id}")

    content_hash = hashlib.sha256(data).hexdigest()
    ext = os.path.splitext(filename)[1] or ".bin"

    existing = session.scalar(
        select(Transcript).where(
            Transcript.company_id == company_id,
            Transcript.fiscal_year == fiscal_year,
            Transcript.quarter == quarter,
        )
    )
    if existing is not None:
        if existing.content_hash == content_hash:
            return existing, False  # exact duplicate -> no-op
        # replaced content: update + reprocess
        existing.content_hash = content_hash
        existing.status = TranscriptStatus.uploaded
        existing.source_blob = _store_blob(data, f"{company.ticker}_{fiscal_year}Q{quarter}_{content_hash[:8]}{ext}")
        session.commit()
        return existing, True

    blob = _store_blob(data, f"{company.ticker}_{fiscal_year}Q{quarter}_{content_hash[:8]}{ext}")
    t = Transcript(
        company_id=company_id,
        fiscal_year=fiscal_year,
        quarter=quarter,
        content_hash=content_hash,
        source_blob=blob,
        status=TranscriptStatus.uploaded,
    )
    session.add(t)
    session.commit()
    session.refresh(t)
    return t, True
