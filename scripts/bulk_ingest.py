"""
Bulk ingest downloaded BSE concall PDFs into the concall-intel database.

Steps:
  1. Read Downloads/ConcallTranscripts/manifest.csv (rows with status OK/ALREADY).
  2. Derive (fiscal_year, quarter) from the announcement subject ("Quarter Ended
     <Month> <Year>" / "Q<n> FY..") or, failing that, from the filing date.
  3. Rank candidate docs and keep the single best transcript per (company, quarter).
  4. Extract clean text (PyMuPDF); skip short / scanned / non-transcript PDFs.
  5. Ingest into the DB (company get-or-create keyed on NSE symbol) and store raw_text.
  6. Print a company x quarter coverage matrix and write coverage.csv.

Run from the concall-intel project root:
    .venv\Scripts\python.exe scripts\bulk_ingest.py
"""
from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

# make the app package importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal, init_db          # noqa: E402
from app.models import Company                     # noqa: E402
from app.services.extraction import extract_text   # noqa: E402
from app.services.ingestion import ingest_transcript  # noqa: E402

ROOT = Path.home() / "Downloads" / "ConcallTranscripts"
MANIFEST = ROOT / "manifest.csv"

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}

# quarter-end month -> (quarter, fy_offset)  under Indian FY (Apr-Mar, fy=year ending March).
#   Mar->Q4 fy=year ; Jun->Q1 fy=year+1 ; Sep->Q2 fy=year+1 ; Dec->Q3 fy=year+1
END_TO_Q = {3: (4, 0), 6: (1, 1), 9: (2, 1), 12: (3, 1)}

# how well a subject looks like an actual transcript (higher = better)
def doc_rank(subject: str) -> int:
    s = subject.lower()
    if "agm" in s:
        return -10
    if "transcript" in s:
        return 5
    if "management commentary" in s or "management presentation" in s:
        return 4
    if "earnings" in s and ("call" in s or "conference" in s):
        return 3
    if "analyst" in s or "investor" in s or "con. call" in s or "con call" in s:
        return 2
    return 1


def quarter_from_subject(subject: str):
    s = subject
    # "Quarter Ended March 31, 2025" / "Quarter And Year Ended March 31, 2025"
    m = re.search(r"ended\s+([A-Za-z]+)\s+\d{1,2},?\s*(\d{4})", s, re.IGNORECASE)
    if m:
        mon = MONTHS.get(m.group(1).lower())
        yr = int(m.group(2))
        if mon in (3, 6, 9, 12):
            q, off = END_TO_Q[mon]
            return yr + off, q
    # "Q1 FY2026" / "Q1 FY 2025-26" / "Q1FY26"
    m = re.search(r"\bQ([1-4])\s*FY\s*[-]?\s*(\d{2,4})", s, re.IGNORECASE)
    if m:
        q = int(m.group(1))
        yr = int(m.group(2))
        if yr < 100:
            yr += 2000
        return yr, q
    return None


def quarter_from_filing(date_str: str):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_str)
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    if mo in (4, 5, 6):
        return y, 4          # reported Q4 (Jan-Mar), fy=y
    if mo in (7, 8, 9):
        return y + 1, 1      # Q1 (Apr-Jun), fy=y+1
    if mo in (10, 11, 12):
        return y + 1, 2      # Q2 (Jul-Sep), fy=y+1
    return y, 3              # Jan-Mar filing -> Q3 (Oct-Dec prev), fy=y


def ticker_for(nse: str, company: str) -> str:
    if nse and nse.strip():
        return re.sub(r"[^A-Za-z0-9]", "", nse.strip()).upper()
    return re.sub(r"[^A-Za-z0-9]", "", company)[:12].upper()


def is_real_transcript(text: str) -> tuple[bool, str]:
    if text.startswith("[WARN"):
        return False, "low-quality/scanned"
    n = len(text)
    if n < 1800:
        return False, f"too-short({n})"
    letters = sum(c.isalpha() for c in text)
    if letters / max(n, 1) < 0.55:
        return False, "low-letter-ratio"
    low = text.lower()
    markers = ("operator", "thank you", "question", "moderator", "ladies and gentlemen",
               "good morning", "good afternoon", "good evening", "management", "quarter")
    if not any(mk in low for mk in markers):
        return False, "no-transcript-markers"
    return True, "ok"


def main():
    init_db()
    rows = []
    with MANIFEST.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["status"] in ("OK", "ALREADY"):
                rows.append(r)

    # group candidate files per (ticker, fy, quarter); keep best
    best: dict[tuple, dict] = {}
    meta: dict[str, tuple] = {}   # ticker -> (company, nse, isin)
    for r in rows:
        company, nse, isin = r["company"], r["nse"], r["isin"]
        subj, date, saved = r["subject"], r["date"], r["saved_as"]
        if not saved:
            continue
        ticker = ticker_for(nse, company)
        meta[ticker] = (company, nse, isin)
        fyq = quarter_from_subject(subj) or quarter_from_filing(date)
        if not fyq:
            continue
        fy, q = fyq
        key = (ticker, fy, q)
        path = ROOT / re.sub(r"[^\w\- ]+", "", company).replace(" ", "_") / saved
        rank = doc_rank(subj)
        cand = {"path": path, "rank": rank, "subject": subj, "date": date}
        if key not in best or rank > best[key]["rank"]:
            best[key] = cand

    print(f"{len(rows)} manifest rows -> {len(best)} unique (company,quarter) slots", flush=True)

    session = SessionLocal()
    stats = defaultdict(int)
    coverage = defaultdict(set)   # ticker -> set of (fy,q)
    skips = []
    companies_cache: dict[str, Company] = {}
    try:
        for (ticker, fy, q), cand in sorted(best.items()):
            path: Path = cand["path"]
            if not path.exists():
                stats["missing_file"] += 1
                continue
            data = path.read_bytes()
            try:
                text = extract_text(data, filename=str(path))
            except Exception as e:  # noqa: BLE001
                stats["extract_error"] += 1
                skips.append((ticker, fy, q, f"extract_error:{e}"))
                continue
            ok, why = is_real_transcript(text)
            if not ok:
                stats["skipped_nontranscript"] += 1
                skips.append((ticker, fy, q, why))
                continue

            company = companies_cache.get(ticker)
            if company is None:
                company = session.query(Company).filter_by(ticker=ticker).one_or_none()
                if company is None:
                    name, _, _ = meta[ticker]
                    company = Company(ticker=ticker, name=name, sector=None)
                    session.add(company)
                    session.commit()
                    session.refresh(company)
                companies_cache[ticker] = company

            transcript, created = ingest_transcript(
                session, company_id=company.id, fiscal_year=fy, quarter=q,
                data=data, filename=str(path),
            )
            transcript.raw_text = text
            session.commit()
            coverage[ticker].add((fy, q))
            stats["ingested" if created else "already"] += 1
        # ---- report ----
        print("\n=== COVERAGE (quarters loaded per company) ===", flush=True)
        for ticker in sorted(coverage, key=lambda t: -len(coverage[t])):
            qs = sorted(coverage[ticker])
            name = meta[ticker][0]
            span = f"{qs[0][0]}Q{qs[0][1]}..{qs[-1][0]}Q{qs[-1][1]}" if qs else "-"
            print(f"  {len(qs):2d}  {ticker:12s} {name[:34]:34s} {span}", flush=True)

        print("\n=== STATS ===", flush=True)
        for k, v in sorted(stats.items()):
            print(f"  {k}: {v}", flush=True)

        cov_csv = ROOT / "coverage.csv"
        with cov_csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["ticker", "company", "quarters_loaded", "list"])
            for ticker in sorted(coverage):
                qs = sorted(coverage[ticker])
                w.writerow([ticker, meta[ticker][0], len(qs),
                            " ".join(f"FY{fy}Q{q}" for fy, q in qs)])
        print(f"\nWrote {cov_csv}", flush=True)
        total_q = sum(len(v) for v in coverage.values())
        print(f"TOTAL companies={len(coverage)}  transcripts loaded={total_q}", flush=True)
    finally:
        session.close()


if __name__ == "__main__":
    main()
