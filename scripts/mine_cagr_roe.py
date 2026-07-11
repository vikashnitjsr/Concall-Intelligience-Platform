import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from app.db import SessionLocal
from app import models as m

s = SessionLocal()
comps = {c.id: c.ticker for c in s.query(m.Company).all()}

# sentence-level search for CAGR / ROE / ROCE mentions with a number
PAT = re.compile(r"(CAGR|compound(?:ed)?\s+annual|return on equity|\bROE\b|\bROCE\b|return on capital)", re.I)
NUM = re.compile(r"\d{1,3}(?:\.\d+)?\s*%")

for cid, tick in sorted(comps.items(), key=lambda x: x[1]):
    txs = s.query(m.Transcript).filter(m.Transcript.company_id == cid).all()
    found = []
    for t in txs:
        txt = t.raw_text or ""
        if len(txt) < 5000:
            continue
        # split into rough sentences
        for sent in re.split(r"(?<=[.!?])\s+", txt):
            if PAT.search(sent) and NUM.search(sent) and len(sent) < 320:
                s2 = " ".join(sent.split())
                found.append((f"FY{t.fiscal_year}Q{t.quarter}", s2))
    # dedupe
    seen = set(); uniq = []
    for p, s2 in found:
        k = s2[:60]
        if k in seen: continue
        seen.add(k); uniq.append((p, s2))
    print(f"\n===== {tick} ({len(uniq)} hits) =====")
    for p, s2 in uniq[:6]:
        print(f"  [{p}] {s2[:240]}")
