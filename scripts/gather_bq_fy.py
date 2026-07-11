import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from app.db import SessionLocal
from app import models as m

s = SessionLocal()
comps = {c.id: c.ticker for c in s.query(m.Company).all()}

# latest company score (business quality)
out = {}
for cid, tick in comps.items():
    cs = (s.query(m.CompanyScore)
            .filter(m.CompanyScore.company_id == cid)
            .order_by(m.CompanyScore.as_of_period_ordinal.desc())
            .first())
    total = getattr(cs, "total_score", None) if cs else None
    # gather revenue_fyXX and pat_fyXX metrics
    mets = s.query(m.Metric).join(m.Transcript, m.Metric.transcript_id == m.Transcript.id)\
            .filter(m.Transcript.company_id == cid).all()
    rev = {}; pat = {}
    for mm in mets:
        n = mm.name.lower()
        if n.startswith("revenue_fy") and n[-4:].isdigit() is False:
            pass
        import re
        r = re.match(r"revenue_fy(\d{2,4})$", n)
        p = re.match(r"pat_fy(\d{2,4})$", n)
        rc = re.match(r"revenue_fy(\d{2,4})_consol$", n)
        pc = re.match(r"pat_fy(\d{2,4})_consol$", n)
        ti = re.match(r"total_income_fy(\d{2,4})_consol$", n)
        def fy(x):
            x=int(x); return 2000+x if x<100 else x
        if r: rev[fy(r.group(1))]=mm.value_numeric
        if rc: rev[fy(rc.group(1))]=mm.value_numeric
        if ti: rev.setdefault(fy(ti.group(1)), mm.value_numeric)
        if p: pat[fy(p.group(1))]=mm.value_numeric
        if pc: pat[fy(pc.group(1))]=mm.value_numeric
    out[tick] = {"business_quality": total, "revenue_by_fy": rev, "pat_by_fy": pat}

for t in sorted(out):
    d = out[t]
    print(f"{t:12} BQ={d['business_quality']}  rev={d['revenue_by_fy']}  pat={d['pat_by_fy']}")
with open("data/bq_and_fy.json","w",encoding="utf-8") as f:
    json.dump(out, f, indent=2)
