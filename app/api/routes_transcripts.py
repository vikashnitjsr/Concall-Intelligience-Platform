"""Company + transcript endpoints, including the upload -> process flow."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Company, Transcript
from app.schemas import CompanyIn, CompanyOut, TranscriptOut
from app.services.ingestion import ingest_transcript
from app.workers.pipeline import process_transcript

router = APIRouter()


@router.post("/companies", response_model=CompanyOut)
def create_company(payload: CompanyIn, session: Session = Depends(get_session)):
    if session.scalar(select(Company).where(Company.ticker == payload.ticker)):
        raise HTTPException(409, f"Company {payload.ticker} already exists")
    c = Company(ticker=payload.ticker, name=payload.name, sector=payload.sector)
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


@router.get("/companies", response_model=list[CompanyOut])
def list_companies(session: Session = Depends(get_session)):
    return session.scalars(select(Company).order_by(Company.ticker)).all()


@router.post("/companies/{company_id}/transcripts", response_model=dict)
async def upload_transcript(
    company_id: int,
    fiscal_year: int = Form(...),
    quarter: int = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Upload a quarterly concall transcript and run the full pipeline synchronously.

    In production this endpoint would only ingest + enqueue; workers process async.
    """
    if quarter not in (1, 2, 3, 4):
        raise HTTPException(422, "quarter must be 1..4")
    data = await file.read()
    try:
        transcript, created = ingest_transcript(
            session, company_id=company_id, fiscal_year=fiscal_year,
            quarter=quarter, data=data, filename=file.filename or "transcript.pdf",
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

    if not created:
        return {"status": "duplicate_no_op", "transcript_id": transcript.id}

    try:
        report = process_transcript(session, transcript)
        report["status"] = "processed"
        return report
    except FileNotFoundError:
        # Running in "agent" mode with no analysis JSON yet: text is extracted and
        # saved; the agent produces the analysis, then POST /internal/agent-analysis.
        return {
            "status": "awaiting_analysis",
            "transcript_id": transcript.id,
            "chars_extracted": len(transcript.raw_text or ""),
            "message": "Transcript extracted. Real insights are produced by the "
                       "agent from the extracted text (no external API key), or set "
                       "LLM_PROVIDER=openai for automatic analysis.",
        }


@router.get("/companies/{company_id}/transcripts", response_model=list[TranscriptOut])
def list_transcripts(company_id: int, session: Session = Depends(get_session)):
    return session.scalars(
        select(Transcript).where(Transcript.company_id == company_id)
        .order_by(Transcript.fiscal_year, Transcript.quarter)
    ).all()
