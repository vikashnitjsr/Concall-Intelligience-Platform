"""Command line helpers: `initdb` and `demo`.

    python -m app.cli initdb
    python -m app.cli demo
"""
from __future__ import annotations

import os
import sys

from app.db import SessionLocal, init_db
from app.models import Company
from app.services.ingestion import ingest_transcript
from app.workers.pipeline import process_transcript

DEMO_QUARTERS = [
    (2025, 1, """Good morning everyone. Revenue for the quarter was 1200 crore, up 14%
    year on year. EBITDA margin came in at 17%. Going forward we expect revenue growth
    of around 15% for the full year. We are guiding for an EBITDA margin target of 18%
    by FY2026. Our net debt increased slightly this quarter due to capex."""),
    (2025, 2, """Revenue was 1290 crore this quarter. EBITDA margin was 17.5%. We remain
    confident and expect to deliver the revenue growth we guided earlier. We plan capex
    of 500 crore next year. There was some delay in receivables collection."""),
    (2025, 3, """Revenue reached 1350 crore. Margin improved to 18%. Management target of
    18% EBITDA margin is on track. We will continue our expansion plan going forward."""),
    (2025, 4, """Full year revenue was 5100 crore with growth of 15%. EBITDA margin ended
    at 18.2%, meeting our guidance. For next year we target revenue growth of 16% and aim
    for margin of 19% by FY2027. Promoter pledge was reduced during the year."""),
    (2026, 1, """Revenue for Q1 was 1400 crore, up 16%. EBITDA margin was 18.5%. We expect
    to sustain this momentum and guide for 19% margin by the end of the year."""),
]


def cmd_initdb() -> None:
    init_db()
    print("Database initialized.")


def cmd_demo() -> None:
    init_db()
    session = SessionLocal()
    try:
        company = session.query(Company).filter_by(ticker="DEMO").one_or_none()
        if company is None:
            company = Company(ticker="DEMO", name="Demo Industries Ltd", sector="Diversified")
            session.add(company)
            session.commit()
            session.refresh(company)

        for fy, q, text in DEMO_QUARTERS:
            transcript, created = ingest_transcript(
                session, company_id=company.id, fiscal_year=fy, quarter=q,
                data=text.encode("utf-8"), filename=f"demo_{fy}Q{q}.txt",
            )
            if not created:
                print(f"FY{fy}Q{q}: duplicate, skipped")
                continue
            report = process_transcript(session, transcript)
            print(f"FY{fy}Q{q}: total={report['total_0_100']} band={report['decision_band']} "
                  f"issued={report['guidance_issued']} resolved={report['guidance_resolved']} "
                  f"reliability={report['guidance_reliability']}")

        print("\nDemo complete. Start the API: uvicorn app.main:app --reload")
        print("Then GET /companies/1/guidance-chains and /leaderboards")
    finally:
        session.close()


def _get_or_create_company(session, ticker: str, name: str, sector: str | None = None):
    company = session.query(Company).filter_by(ticker=ticker).one_or_none()
    if company is None:
        company = Company(ticker=ticker, name=name, sector=sector)
        session.add(company)
        session.commit()
        session.refresh(company)
    return company


def cmd_extract() -> None:
    """extract <TICKER> <NAME> <FY> <Q> <pdf_path> [out_txt]

    Ingests a PDF, extracts clean text, prints where the text was written so the
    agent can read it and produce an analysis JSON.
    """
    from app.services.extraction import extract_text
    from app.services.ingestion import ingest_transcript

    _, _, ticker, name, fy, q, pdf_path, *rest = sys.argv
    fy, q = int(fy), int(q)
    init_db()
    session = SessionLocal()
    try:
        company = _get_or_create_company(session, ticker, name)
        with open(pdf_path, "rb") as fh:
            data = fh.read()
        transcript, _ = ingest_transcript(
            session, company_id=company.id, fiscal_year=fy, quarter=q,
            data=data, filename=pdf_path,
        )
        text = extract_text(data, filename=pdf_path)
        transcript.raw_text = text
        session.commit()
        out = rest[0] if rest else os.path.join("data", f"{ticker}_{fy}Q{q}.txt")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Extracted {len(text)} chars -> {out}")
        print(f"transcript_id={transcript.id} company_id={company.id}")
    finally:
        session.close()


def cmd_load_analysis() -> None:
    """load-analysis <TICKER> <FY> <Q>

    Persists the agent-produced analysis at data/analyses/{TICKER}_{FY}Q{Q}.json,
    then runs guidance reconciliation + scoring. Requires a prior `extract`.
    """
    from app.models import Transcript
    from app.services.analysis import persist_analysis
    from app.services.guidance import reconcile_guidance
    from app.services.scoring import score_company
    from app.schemas import TranscriptAnalysis
    from app.models import TranscriptStatus

    _, _, ticker, fy, q = sys.argv
    fy, q = int(fy), int(q)
    init_db()
    session = SessionLocal()
    try:
        company = session.query(Company).filter_by(ticker=ticker).one()
        transcript = (
            session.query(Transcript)
            .filter_by(company_id=company.id, fiscal_year=fy, quarter=q)
            .one()
        )
        path = os.path.join("data", "analyses", f"{ticker}_{fy}Q{q}.json")
        with open(path, "r", encoding="utf-8") as fh:
            analysis = TranscriptAnalysis.model_validate_json(fh.read())
        persist_analysis(session, transcript, analysis)
        resolved = reconcile_guidance(session, transcript)
        transcript.status = TranscriptStatus.reconciled
        session.commit()
        score = score_company(session, company.id, transcript.period_ordinal)
        transcript.status = TranscriptStatus.scored
        session.commit()
        print(f"Loaded analysis for {ticker} FY{fy}Q{q}: total={score.total_0_100} "
              f"band={score.decision_band} resolved={resolved} "
              f"reliability={score.guidance_reliability_score}")
    finally:
        session.close()


def main() -> None:
    cmds = {
        "initdb": cmd_initdb,
        "demo": cmd_demo,
        "extract": cmd_extract,
        "load-analysis": cmd_load_analysis,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        raise SystemExit(1)
    cmds[sys.argv[1]]()


if __name__ == "__main__":
    main()
